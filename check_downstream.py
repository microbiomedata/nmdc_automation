#!/usr/bin/env python
"""
Standalone script to check that all necessary downstream data objects/
workflow executions have been created for a given set of workflow process nodes.

Usage:
    python check_downstream.py --site-config <path/to/site_configuration.toml> \\
                               (--study-id <id> | --allowlist-file <file>) \\
                               [--verbose]

The site config TOML must have [nmdc] api_url and [credentials] client_id/client_secret.
The packaged workflows YAML (nmdc_automation/config/workflows/workflows.yaml) is always used.
Outputs are written to a folder named <study_id>_<date> or <allowlist_stem>_<date>.

Exit codes:
    0 - all downstream data objects/executions are present
    1 - one or more downstream workflows are missing
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


def make_output_dir(args) -> Path:
    """Return a Path for the output directory, creating it if needed."""
    today = date.today().isoformat()
    if args.study_id:
        # Replace colons so the name is filesystem-safe
        stem = args.study_id.replace(":", "-")
    else:
        stem = Path(args.allowlist_file).stem
    out_dir = Path(f"{stem}_{today}")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def check_downstream(wfp_nodes, force=False):
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

    for node in wfp_nodes:
        for child_wf in node.workflow.children:
            if not child_wf.enabled:
                continue
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
    out_dir = make_output_dir(args)
    logging.info(f"Output dir    : {out_dir}")

    # ── Load workflow process nodes ───────────────────────────────────────────
    logging.info("Loading workflow process nodes …")
    wfp_nodes, manifest_map = load_workflow_process_nodes(api, workflows, allowlist)
    logging.info(f"Found {len(wfp_nodes)} workflow process node(s)")

    if not wfp_nodes:
        logging.warning("No workflow process nodes found – nothing to check.")
        sys.exit(0)

    # ── Check downstream completeness ─────────────────────────────────────────
    complete, missing = check_downstream(wfp_nodes)

    missing_rows = set()
    for node, child_wf in missing:
        for dg_id in node.was_informed_by:
            missing_rows.add((dg_id, node.id, child_wf.type))
    missing_lines = sorted(f"{dg_id}\t{last_wf_id}\t{missing_type}" for dg_id, last_wf_id, missing_type in missing_rows)
    tsv_output = "data_generation_id\tlast_workflow_id\tmissing_workflow_type\n" + "\n".join(missing_lines) + "\n"
    (out_dir / "missing.tsv").write_text(tsv_output)
    logging.info(f"Wrote missing.tsv ({len(missing_lines)} entries) to {out_dir}")

    # ── Data object summary per node ─────────────────────────────────────────
    if args.verbose:
        do_lines = []
        for node in wfp_nodes:
            do_lines.append(f"\n  {node.id}  [{node.type}]  ver={node.version or 'N/A'}")
            if node.data_objects_by_type:
                for do_type, do_obj in node.data_objects_by_type.items():
                    do_lines.append(f"    {do_type}: {do_obj.id}")
            else:
                do_lines.append("    (no required data objects mapped)")
        do_text = "\n".join(do_lines)
        print("\n=== Data Objects by Node ===")
        print(do_text)
        (out_dir / "data_objects.txt").write_text(do_text + "\n")

    # ── Exit code ─────────────────────────────────────────────────────────────
    if missing:
        sys.exit(1)
    sys.exit(0)


def _collect_tree(node, indent: int, lines: list, seen=None):
    """Recursively collect tree lines into a list."""
    if seen is None:
        seen = set()
    if node.id in seen:
        lines.append("  " * indent + f"[{node.id}] (already shown)")
        return
    seen.add(node.id)
    do_count = len(node.data_objects_by_type)
    lines.append("  " * indent + f"- {node.id}  [{node.type}]  ver={node.version or 'N/A'}  data_objects={do_count}")
    for child in node.children:
        _collect_tree(child, indent + 1, lines, seen)


if __name__ == "__main__":
    main()
