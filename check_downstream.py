#!/usr/bin/env python
"""
Standalone script to check that all necessary downstream data objects/
workflow executions have been created for a given set of workflow process nodes.

Usage:
    python check_downstream.py --site-config <path/to/site_configuration.toml> \\
                               (--study-id <id> | --allowlist-file <file>) \\
                               [--verbose] \\
                               [--output-path]

The site config TOML must have [nmdc] api_url and [credentials] client_id/client_secret.
The packaged workflows YAML (nmdc_automation/config/workflows/workflows.yaml) is always used.
Outputs are written to a folder named <study_id>_<date> or <allowlist_stem>_<date>.

"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import importlib.resources

from nmdc_automation.api.nmdcapi import NmdcRuntimeApi
from nmdc_automation.config import SiteConfig
from nmdc_automation.workflow_automation.workflow_process import load_workflow_process_nodes
from nmdc_automation.workflow_automation.workflows import load_workflow_configs
from nmdc_automation.workflow_automation.sched import within_range

_PACKAGED_WORKFLOWS_YAML = importlib.resources.files("nmdc_automation.config.workflows").joinpath("workflows.yaml")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check that all necessary downstream workflow executions "
                    "and data objects have been created."
    )
    parser.add_argument(
        "--site-config",
        required=True,
        help="Path to site_configuration.toml",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--study-id",
        default=None,
        help="NMDC study ID (e.g. nmdc:sty-11-abc123). Fetches all associated "
             "data_generation_set IDs automatically.",
    )
    source.add_argument(
        "--allowlist-file",
        default=None,
        help="Path to a plain-text file with one data_generation ID per line.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )
    parser.add_argument(
        "--output-path",
        default=None,
        help="Path to output directory (default: <study_id>_<date> or <allowlist_stem>_<date>).",
    )
    return parser.parse_args()


def build_allowlist(args, api):
    """Return a list of data_generation IDs from --study-id or --allowlist-file."""
    if args.study_id:
        records = api.list_from_collection(
            "data_generation_set",
            {"associated_studies": args.study_id},
        )
        ids = [rec["id"] for rec in records]
        if not ids:
            sys.exit(f"ERROR: no data_generation records found for study {args.study_id}")
        logging.info(f"Study {args.study_id}: found {len(ids)} data_generation record(s)")
        return ids
    if args.allowlist_file:
        path = Path(args.allowlist_file)
        if not path.exists():
            sys.exit(f"ERROR: allowlist file not found: {path}")
        return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def make_output_path(args) -> Path:
    """Return a Path for the output directory, creating it if needed."""
    today = date.today().isoformat()
    if args.study_id:
        # Replace colons so the name is filesystem-safe
        stem = args.study_id.replace(":", "-")
    else:
        stem = Path(args.allowlist_file).stem
    if not args.output_path:
        out_path = Path(f"{stem}_{today}")
    else:
        out_path = Path(f"{args.output_path}/{stem}_{today}")
    return out_path


def check_downstream(wfp_nodes, manifest_map, force=False):
    """
    Walk the resolved workflow process node graph and find nodes whose
    expected child workflows are not yet represented.

    Returns
    -------
    complete : list[(node, child_wf)]   – pairs where the child execution exists
    missing  : list[(node, child_wf)]   – pairs where nothing satisfies the child wf
    """
    complete = []
    missing = []
    grouped_checks_seen = set()

    for node in wfp_nodes:
        grouped_dg_ids = None
        if getattr(node.workflow, "collection", None) == "data_generation_set" and len(getattr(node, "manifest", [])) == 1:
            manifest_id = node.manifest[0]
            grouped_dg_ids = sorted(manifest_map.get(manifest_id, {}).get("data_generation_set", []))
            if len(grouped_dg_ids) <= 1:
                grouped_dg_ids = None

        for child_wf in node.workflow.children:
            #print(f"\nChecking node {node.id}  [{node.type}]  ver={node.version or 'N/A'}  for child workflow type '{child_wf.type}' …")
            #print(f"    Child workflow1 version: {[child_node.workflow.version.lstrip('b').lstrip('v') for child_node in node.children]}")
            #print(f"    Child workflow2 version: {child_wf.version.lstrip('b').lstrip('v')}")
            #print(f"    Satisfied: {any(within_range(child_node.workflow, child_wf, force=force) for child_node in node.children)}")
            if not child_wf.enabled:
                continue

            # For manifest groups, evaluate each child workflow exactly once for the full DG set.
            if grouped_dg_ids is not None:
                grouped_key = ("/".join(grouped_dg_ids), child_wf.name)
                if grouped_key in grouped_checks_seen:
                    continue
                grouped_checks_seen.add(grouped_key)

                satisfied = any(
                    within_range(candidate.workflow, child_wf, force=force)
                    and sorted(candidate.was_informed_by) == grouped_dg_ids
                    for candidate in wfp_nodes
                )
            else:
                # Is there already a child node that satisfies this workflow?
                satisfied = any(
                    within_range(child_node.workflow, child_wf, force=force)
                    for child_node in node.children
                )

            if satisfied:
                complete.append((node, child_wf))
            else:
                missing.append((node, child_wf))

    return complete, missing


def _get_manifest_dg_key(node, manifest_map):
    manifest_ids = getattr(node, "manifest", [])
    if len(manifest_ids) != 1:
        return None

    manifest_id = manifest_ids[0]
    manifest_data = manifest_map.get(manifest_id, {})
    dg_ids = manifest_data.get("data_generation_set", [])
    if len(dg_ids) <= 1:
        return None

    return _build_was_informed_by_key(dg_ids)


def _build_was_informed_by_key(was_informed_by):
    if not was_informed_by:
        return None
    if len(was_informed_by) == 1:
        return was_informed_by[0]
    return "_".join(sorted(was_informed_by))


def _get_pending_job_triggers(node, manifest_map):
    if getattr(node.workflow, "collection", None) != "data_generation_set":
        return [node.id]

    manifest_ids = getattr(node, "manifest", [])
    if len(manifest_ids) == 1:
        manifest_id = manifest_ids[0]
        dg_ids = sorted(manifest_map.get(manifest_id, {}).get("data_generation_set", []))
        if dg_ids:
            return dg_ids

    return list(node.was_informed_by)


def _get_output_dg_ids(node, manifest_map):
    manifest_dg_key = _get_manifest_dg_key(node, manifest_map)
    if manifest_dg_key:
        manifest_id = node.manifest[0]
        dg_ids = manifest_map.get(manifest_id, {}).get("data_generation_set", [])
        return ["/".join(sorted(dg_ids))]

    return list(node.was_informed_by)


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    # ── Load config ──────────────────────────────────────────────────────────
    site_cfg_path = Path(args.site_config)
    if not site_cfg_path.exists():
        sys.exit(f"ERROR: site config not found: {site_cfg_path}")

    site_cfg = SiteConfig(site_cfg_path)

    wf_yaml = Path(str(_PACKAGED_WORKFLOWS_YAML))

    logging.info(f"Site config   : {site_cfg_path}")
    logging.info(f"Workflow YAML : {wf_yaml}")
    logging.info(f"API URL       : {site_cfg.api_url}")

    # ── Initialise API + load workflows ──────────────────────────────────────
    api = NmdcRuntimeApi(site_cfg)
    workflows = load_workflow_configs(wf_yaml)
    logging.info(f"Loaded {len(workflows)} workflow config(s)")

    # ── Build allowlist ───────────────────────────────────────────────────────
    allowlist = build_allowlist(args, api)
    if allowlist:
        logging.info(f"Allowlist     : {len(allowlist)} IDs")

    # ── Create output directory ───────────────────────────────────────────────
    out_path = make_output_path(args)
    logging.info(f"Output path   : {out_path}")

    # ── Load workflow process nodes ───────────────────────────────────────────
    logging.info("Loading workflow process nodes …")
    wfp_nodes, manifest_map = load_workflow_process_nodes(api, workflows, allowlist)
    logging.info(f"Found {len(wfp_nodes)} workflow process node(s)")

    if not wfp_nodes:
        logging.warning("No workflow process nodes found – nothing to check.")
        sys.exit(0)
    
    # ── Check downstream completeness ─────────────────────────────────────────
    complete, missing = check_downstream(wfp_nodes, manifest_map)

    # Make list of DG IDs in allow list but with no downstream workflows
    dg_ids_no_workflows = set(allowlist) - {dg_id for node in wfp_nodes for dg_id in node.was_informed_by}

    # Fetch processing_institution for all DG IDs in allowlist
    CHUNK_SIZE = 100
    dg_processing_institution: dict[str, str] = {}
    dg_has_output: dict[str, bool] = {}
    allowlist_list = list(allowlist)
    for i in range(0, len(allowlist_list), CHUNK_SIZE):
        id_chunk = allowlist_list[i:i + CHUNK_SIZE]
        dg_records = api.list_from_collection("data_generation_set", {"id": {"$in": id_chunk}}, max=10000)
        for rec in dg_records:
            dg_processing_institution[rec["id"]] = rec.get("processing_institution", "")
            dg_has_output[rec["id"]] = bool(rec.get("has_output"))

    # Fetch job ids where the trigger activity was the last workflow id or the dg id if no existing workflows
    pending_job: dict[str, str] = {}
    last_wf_ids_list = list({
        trigger_id
        for node, _ in missing
        for trigger_id in _get_pending_job_triggers(node, manifest_map)
    } | set(dg_ids_no_workflows))
    for i in range(0, len(last_wf_ids_list), CHUNK_SIZE):
        id_chunk = last_wf_ids_list[i:i + CHUNK_SIZE]
        job_records = api.list_jobs({"config.trigger_activity": {"$in": id_chunk}}, max=10000)
        for rec in job_records:
            pending_job[rec["config"]["trigger_activity"]] = rec.get("id", "")

    # Fetch DG IDs associated with workflow executions with qc_status == 'fail'
    failed_dg_ids: set[str] = set()
    for i in range(0, len(allowlist_list), CHUNK_SIZE):
        id_chunk = allowlist_list[i:i + CHUNK_SIZE]
        q_fail = {"was_informed_by": {"$in": id_chunk}, "qc_status": "fail"}
        failed_execs = api.list_from_collection("workflow_execution_set", q_fail, max=10000)
        for rec in failed_execs:
            for dg_id in rec.get("was_informed_by", []):
                failed_dg_ids.add(dg_id)

    # Make output rows for DG ids that are missing some downstream workflow
    missing_rows = set()
    for node, child_wf in missing:
        output_dg_ids = _get_output_dg_ids(node, manifest_map)
        for dg_id in output_dg_ids:
            is_data_generation = getattr(node.workflow, "collection", None) == "data_generation_set"
            last_wf_id = "" if is_data_generation else node.id
            grouped_dg_ids = dg_id.split("/")
            processing_institution = "/".join(
                dg_processing_institution.get(grouped_dg_id, "") for grouped_dg_id in grouped_dg_ids
            )
            has_output = all(dg_has_output.get(grouped_dg_id, False) for grouped_dg_id in grouped_dg_ids)
            trigger_ids = _get_pending_job_triggers(node, manifest_map) if is_data_generation else [last_wf_id]
            last_job_id = ""
            for trigger_id in trigger_ids:
                if trigger_id in pending_job:
                    last_job_id = pending_job[trigger_id]
                    break
            fail_flag = "fail" if any(grouped_dg_id in failed_dg_ids for grouped_dg_id in grouped_dg_ids) else ""
            missing_rows.add((dg_id, last_wf_id, last_job_id, child_wf.type, fail_flag, processing_institution, has_output))

    # Make output rows for DG IDs with no downstream workflows (never made it into wfp_nodes at all (ie malformed input DOs))
    for dg_id in sorted(dg_ids_no_workflows):
        fail_flag = "fail" if dg_id in failed_dg_ids else ""
        processing_institution = dg_processing_institution.get(dg_id, "")
        has_output = dg_has_output.get(dg_id, "")
        missing_rows.add((dg_id, "", "", "nmdc:ReadQcAnalysis", fail_flag, processing_institution, has_output))

    # Make TSV output for missing workflows
    missing_lines = []
    for dg_id, last_wf_id, last_job_id, missing_type, fail_flag, processing_institution, has_output in sorted(
        missing_rows,
        key=lambda row: (row[2], row[3], row[6]),
    ):
        missing_lines.append(f"{dg_id}\t{last_wf_id}\t{last_job_id}\t{missing_type}\t{fail_flag}\t{processing_institution}\t{has_output}")
    tsv_output = (
        "data_generation_id\tlast_workflow_id\tlast_job_id\tmissing_workflow_type\tfail\tprocessing_institution\thas_output\n"
        + "\n".join(missing_lines)
        + "\n"
    )
    Path(f"{out_path}_unfinished_details.tsv").write_text(tsv_output)
    logging.info(f"Wrote ({len(missing_lines)} entries) to {out_path}_unfinished_details.tsv")

    # Make a list of DG IDs that are finished (i.e. can be removed from allow lst) and unfinished (i.e. keep in allow list or add to allow list if it has outputs)
    all_dg_ids_unfinished = set()
    for line in missing_lines:
        dg_id = line.split("\t")[0]
        all_dg_ids_unfinished.add(dg_id)
    ready_for_processing_but_unfinished = {dg_id for dg_id in all_dg_ids_unfinished if dg_has_output.get(dg_id, "TRUE")}
    Path(f"{out_path}_unfinished.lst").write_text("\n".join(ready_for_processing_but_unfinished) + "\n")
    logging.info(f"Wrote ({len(ready_for_processing_but_unfinished)} entries) to {out_path}_unfinished.lst")
    dg_ids_finished = sorted(set(allowlist) - all_dg_ids_unfinished)
    Path(f"{out_path}_finished.lst").write_text("\n".join(dg_ids_finished) + "\n")
    logging.info(f"Wrote ({len(dg_ids_finished)} entries) to {out_path}_finished.lst")


if __name__ == "__main__":
    main()
