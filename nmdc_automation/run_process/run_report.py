"""
Run reports for the NMDC pipeline.

Usage: python -m nmdc_automation.run_process.run_report study-report 
           [OPTIONS] SITE_CONFIG STUDY_ID
"""

from pathlib import Path
from datetime import date
import json
import logging
from typing import List, Union
import click

from itertools import islice
import requests

from nmdc_automation.api import NmdcRuntimeApi
from nmdc_automation.config import SiteConfig


logging.basicConfig(level=logging.DEBUG,
    format="%(asctime)s %(levelname)s: %(message)s"
                    )
logger = logging.getLogger(__name__)
WF_TYPES = [
    "nmdc:ReadQcAnalysis",
    "nmdc:MetagenomeAssembly", 
    "nmdc:MetagenomeAnnotation",
    "nmdc:MagsAnalysis",
    "nmdc:ReadBasedTaxonomyAnalysis"
]

@click.group()
def cli():
    pass

@cli.command()
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("study_id")
# Output options
@click.option("--write-files", is_flag=True, help="Write output files")
@click.option("--outdir", type=click.Path(), help="Output directory (auto-generated if not specified)")
# Filter options
@click.option("--analyte-category", 
              type=click.Choice(['metagenome', 'metatranscriptome', 'metaproteome'], case_sensitive=False),
              default="metagenome", show_default=True, help="Analyte category to filter")
@click.option("--manifest/--no-manifest", default=False, help="Filter by manifest presence")
@click.option("--good-qc/--bad-qc", default=True, help="Filter by QC status")
@click.option("--dg-output/--no-dg-output", default=True, help="Require data generation output")
# Workflow options
@click.option("--wf-type", multiple=True, default=WF_TYPES, 
              help="Workflow types to check (repeatable). Defaults to all 5 standard workflows.")
@click.option("--len-wfe", default=5, show_default=True, 
              help="Expected number of workflow executions")
# Display options
@click.option("--show", 
              type=click.Choice(['all', 'incomplete', 'complete'], case_sensitive=False),
              default='all', show_default=True, help="Filter results display")
# Advanced
@click.option("--pipeline", help="Custom MongoDB pipeline as JSON string")
@click.option("--aggregate", default="data_generation_set", show_default=True,
              help="MongoDB collection to aggregate")
def study_report(site_config, study_id, write_files, outdir, pipeline, wf_type, show, **pipeline_params):
    """
    Generate a workflow completion report for a specific study.

    Analyzes data generation sets to identify complete and incomplete workflow
    executions, showing which workflows are missing and which jobs have been
    attempted.

    Examples: \n
      Basic usage - show all incomplete runs:\n
        $ study-report config.yaml STUDY123

      Show only complete runs: \n
        $ study-report config.yaml STUDY123 --show complete

      Write output files: \n
        $ study-report config.yaml STUDY123 --write-files

      Check specific workflows: \n
        $ study-report config.yaml STUDY123 --wf-type nmdc:MagsAnalysis --wf-type nmdc:ReadBasedTaxonomyAnalysis

      Check metatranscriptome data with bad QC: \n
        $ study-report config.yaml STUDY123 --analyte-category metatranscriptome --bad-qc
    """
    logger.info(f"Generating report for study {study_id}")
    
    # Load configuration
    site_config = SiteConfig(site_config)
    runtime_api = NmdcRuntimeApi(site_config)
    
    # Convert wf_type tuple to list for processing
    if wf_type:
        pipeline_params['wf_type'] = list(wf_type)
    
    # Run aggregation query
    all_runs = run_aggregation(runtime_api, study_id, pipeline, **pipeline_params)
    
    if "cursor" in all_runs:
        all_runs = all_runs['cursor']['batch']
    
    # Process results and categorize
    complete_runs = []
    incomplete_runs = []
    
    for group in all_runs:
        wfex_type = group['_id'].get('wfex_type', [])
        job_wfex_type = group['_id'].get('job_wfex_type', [])
        
        # Determine what's missing
        missing_wfex = [wf for wf in pipeline_params.get('wf_type', WF_TYPES) if wf not in wfex_type]
        incomplete_jobs = [wf for wf in job_wfex_type if wf not in wfex_type]
        complete = len(missing_wfex) == 0
        
        # Add computed fields to the group
        group['_id']['missing_wfex'] = missing_wfex
        group['_id']['incomplete_jobs'] = incomplete_jobs
        group['complete'] = complete
        
        # Categorize
        if complete:
            complete_runs.append(group)
        else:
            incomplete_runs.append(group)
    
    # Calculate summary statistics
    total_complete = sum(run['n_dgs'] for run in complete_runs)
    total_incomplete = sum(run['n_dgs'] for run in incomplete_runs)
    
    workflow_status_count = {
        "complete": total_complete,
        "incomplete": total_incomplete,
        "total": total_complete + total_incomplete
    }
    
    logger.info(f"Workflow status: {json.dumps(workflow_status_count, indent=2)}")
    logger.info(f"Found {len(incomplete_runs)} categories of incomplete data generations")
    
    # Determine what to display based on --show flag
    if show == 'incomplete':
        display_runs = incomplete_runs
        display_title = "Incomplete Runs"
    elif show == 'complete':
        logger.info(f"Found {len(complete_runs)} categories of complete data generations")
        display_runs = complete_runs
        display_title = "Complete Runs"
    else:  # 'all'
        display_runs = incomplete_runs  # Show incomplete by default when 'all'
        display_title = "Incomplete Runs"
    
    # Print table if there are runs to display
    if display_runs:
        print_results_table(display_runs, pipeline_params.get('wf_type', WF_TYPES), display_title)
    else:
        print(f"\nNo {show} runs found.")
    
    # Write files if requested
    if write_files:
        output_dir = write_output_files(study_id, complete_runs, incomplete_runs, 
                                        workflow_status_count, outdir)
        logger.info(f"Files written to {output_dir}")
    
    return {
        'complete_runs': complete_runs,
        'incomplete_runs': incomplete_runs,
        'summary': workflow_status_count
    }


def print_results_table(runs: List[dict], wf_types: List[str], title: str = "Results"):
    """
    Print a formatted table of workflow execution results.
    
    :param runs: List of run groups to display
    :param wf_types: List of workflow types being checked
    :param title: Title for the table
    """
    max_width = len(max(wf_types, key=len))
    columns = ['wfex_type', 'job_wfex_type', 'missing_wfex', 'incomplete_jobs']
    widths = {'n_dgs': 7, **{col: max_width for col in columns}}
    
    header = " ".join(f"{col:<{widths[col]}}" for col in ['n_dgs'] + columns)
    separator = "=" * len(header)
    
    print(f"\n{separator}")
    print(f"{title}")
    print(f"{separator}")
    print(header)
    print("-" * len(header))
    
    for run in runs:
        max_len = max(len(run["_id"].get(col, [])) for col in columns)
        
        for i in range(max_len):
            row_values = {
                'n_dgs': run['n_dgs'] if i == 0 else "",
                **{col: run["_id"].get(col, [])[i] if i < len(run["_id"].get(col, [])) else "" 
                   for col in columns}
            }
            print(" ".join(f"{str(row_values[col]):<{widths[col]}}" for col in ['n_dgs'] + columns))
        
        print("-" * len(header))


def write_output_files(study_id: str, complete_runs: List[dict], 
                       incomplete_runs: List[dict], summary: dict, 
                       outdir: Union[str, Path, None] = None) -> Path:
    """
    Write complete and incomplete runs to JSON files.
    
    :param study_id: Study identifier
    :param complete_runs: List of complete run groups
    :param incomplete_runs: List of incomplete run groups
    :param summary: Summary statistics dictionary
    :param outdir: Output directory path (auto-generated if None)
    :return: Path to output directory
    """
    # Determine output directory
    if outdir:
        output_dir = Path(outdir)
    else:
        base_name = f"{study_id}_report_{date.today()}"
        output_dir = Path.cwd() / base_name
        counter = 1
        while output_dir.exists():
            output_dir = Path.cwd() / f"{base_name}_{counter}"
            counter += 1
    
    # Create directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write summary
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    
    # Write complete runs
    if complete_runs:
        (output_dir / "complete_runs.json").write_text(
            json.dumps(complete_runs, indent=2)
        )
    
    # Write incomplete runs (both as bulk and individual files)
    if incomplete_runs:
        (output_dir / "incomplete_runs.json").write_text(
            json.dumps(incomplete_runs, indent=2)
        )
        
        # Also write individual files for each incomplete group
        for i, data in enumerate(incomplete_runs):
            (output_dir / f"incomplete_group_{i}.json").write_text(
                json.dumps(data, indent=2)
            )
    
    return output_dir


def run_aggregation(runtime_api, study_id: str, pipeline: Union[str, List[dict], None] = None, 
                    aggregate: str = "data_generation_set", **pipeline_params) -> dict:
    """
    Submit an aggregation pipeline to the NMDC run_query endpoint.
    
    :param runtime_api: NMDC Runtime API instance
    :param study_id: Study identifier
    :param pipeline: Custom MongoDB aggregation pipeline (JSON string or list of dicts)
    :param aggregate: MongoDB collection name to aggregate
    :param pipeline_params: Additional parameters for building the pipeline
    :return: Query response as dictionary
    """
    # Handle custom pipeline
    if pipeline:
        if isinstance(pipeline, str):
            pipeline = json.loads(pipeline)
    else:
        pipeline = build_pipeline(study_id=study_id, **pipeline_params)
    
    payload = {
        "aggregate": aggregate,
        "pipeline": pipeline
    }
    
    logger.debug(f"Query payload: {json.dumps(payload, indent=2)}")
    
    # function takes a dictionary
    query_response = runtime_api.run_query(payload)
    return query_response


def build_pipeline(study_id: str, **pipeline_params) -> List[dict]:
    """
    Build a complete MongoDB aggregation pipeline.
    
    Combines multiple pipeline stages:
    1. Match by study and analyte category
    2. Lookup data objects, workflow executions, and jobs
    3. Filter by manifest, QC status, and output presence
    4. Filter by completion requirements
    5. Group results
    
    :param study_id: Study identifier
    :param pipeline_params: Parameters for each pipeline stage
    :return: Complete aggregation pipeline
    """
    pipeline = sum([
        study_and_analyte(study_id=study_id, **pipeline_params),
        lookup_do_wf_job(),
        manifest_and_qc(**pipeline_params),
        set_completion_reqs(**pipeline_params),
        group_results()
    ], [])
    
    return pipeline


def study_and_analyte(study_id: str, analyte_category: str = "metagenome", **kwargs) -> List[dict]:
    """
    Create match stage for study ID and analyte category.
    
    :param study_id: Study identifier to filter
    :param analyte_category: Analyte category (metagenome, metatranscriptome, metaproteome)
    :return: Match stage pipeline
    """
    return [{
        "$match": {
            "associated_studies": study_id,
            "analyte_category": analyte_category
        }
    }]


def lookup_do_wf_job() -> List[dict]:
    """
    Create lookup stages to join data objects, workflow executions, and jobs.
    
    Performs three lookups:
    - data_object_set: Check manifest presence
    - workflow_execution_set: See what executions exist
    - jobs: See what's been attempted
    
    Results are sorted in reverse alphabetical order for easier grouping.
    
    :return: Lookup stages pipeline
    """
    return [{"$lookup": {"from": "data_object_set", "localField": "has_output", "foreignField": "id", "as": "data_object_set"}}, 
            {"$lookup": {"from": "workflow_execution_set", "localField": "id", "foreignField": "was_informed_by", 
                         "pipeline": [{"$sort": {"type": -1}}], "as": "workflow_execution_set"}}, 
            {"$lookup": {"from": "jobs", "localField": "id", "foreignField": "config.was_informed_by", 
                         "pipeline": [{"$sort": {"config.activity.type": -1}}], "as": "jobs"}}]


def manifest_and_qc(manifest: bool = False, good_qc: bool = True, 
                    dg_output: bool = True, **kwargs) -> List[dict]:
    """
    Create match stage for manifest, QC status, and output filters.
    
    :param manifest: Include items in manifest (pooled data)
    :param good_qc: Exclude items with QC failures (qc_status, qc_comment, has_failure_categorization)
    :param dg_output: Require data_generation_set output
    :return: Match stage pipeline
    """
    # When good_qc=True, QC failure fields should NOT exist
    has_qc_failures = not good_qc
    
    return [{
        "$match": {
            "data_object_set.in_manifest": {"$exists": manifest},
            "has_output": {"$exists": dg_output},
            "workflow_execution_set.qc_status": {"$exists": has_qc_failures},
            "workflow_execution_set.qc_comment": {"$exists": has_qc_failures},
            "workflow_execution_set.has_failure_categorization": {"$exists": has_qc_failures}
        }
    }]


def set_completion_reqs(show: str = 'all', wf_type: List[str] = None, 
                       len_wfe: int = 5, **kwargs) -> List[dict]:
    """
    Create match stage for completion requirements.
    
    Defines what constitutes "complete" based on:
    - Number of workflow executions (len_wfe)
    - Presence of specific workflow types (wf_type)
    
    :param show: Filter for 'all', 'incomplete', or 'complete' runs
    :param wf_type: List of required workflow types
    :param len_wfe: Expected number of workflow executions
    :return: Match stage pipeline (empty list if show='all')
    """
    if wf_type is None:
        wf_type = WF_TYPES
    
    if show == 'incomplete':
        # Match items that are INCOMPLETE
        or_list = [{"$expr": {"$lt": [{"$size": "$workflow_execution_set"}, len_wfe]}}]
        for wf in wf_type:
            or_list.append({
                "workflow_execution_set": {
                    "$not": {"$elemMatch": {"type": wf}}
                }
            })
        return [{"$match": {"$or": or_list}}]
    
    elif show == 'complete':
        # Match items that are COMPLETE
        and_list = [{"$expr": {"$gte": [{"$size": "$workflow_execution_set"}, len_wfe]}}]
        for wf in wf_type:
            and_list.append({
                "workflow_execution_set": {
                    "$elemMatch": {"type": wf}
                }
            })
        return [{"$match": {"$and": and_list}}]
    
    else:  # 'all'
        # No filtering - return empty pipeline stage
        return []


def group_results() -> List[dict]:
    """
    Create group stage to aggregate results by workflow types.
    
    Groups data generation sets by their workflow execution types and job types,
    allowing comparison of what exists in workflow_execution_set vs jobs,
    along with timestamps to identify patterns in failures.
    
    :return: Group stage pipeline
    """
    return [{
        "$group": {
            "_id": {
                "wfex_type": "$workflow_execution_set.type",
                "job_wfex_type": "$jobs.config.activity.type"
            },
            "n_dgs": {"$sum": 1},
            "executions": {
                "$push": {
                    "id": "$id",
                    "wfex_id": "$workflow_execution_set.id",
                    "wfex_end": "$workflow_execution_set.ended_at_time",
                    "job_id": "$jobs.id",
                    "job_wfid": "$jobs.config.activity_id",
                    "job_start": "$jobs.created_at"
                }
            }
        }
    }]

def agg_match(field: str, value: str, **kwargs) -> List[dict]:
    """
    For personalized match queries
    
    :param field: Schema slot
    :param value: Schema value
    """
    return [{"$match": {field: value}}]

# ----Legacy code-----

@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.argument("study_id")
def study_report_legacy(config_file, study_id):
    """
    This is the older version of study_report. Less specific and less customized.
    Generate a report for a specific study.
    """
    logger.info(f"Generating report for study {study_id} from {config_file}")
    site_config = SiteConfig(config_file)

    username = site_config.username
    password = site_config.password

    # Set up the API URL
    api_url = site_config.api_url
    headers = {'accept': 'application/json', 'Authorization': f'Basic {username}:{password}'}

    # Get Un-pooled Data Generation ID for the study
    unpooled_dg_ids = get_unpooled_data_generation_ids(site_config, study_id)
    logger.info(f"Found {len(unpooled_dg_ids)} Un-pooled Data Generation IDs")

    metagenome_workflow_status = {}
    metagenome_ids_not_done = []
    for data_generation_id in unpooled_dg_ids:

        workflow_executions = _get_workflow_executions(api_url, data_generation_id, headers)
        # logger.info(f"Found {len(workflow_executions)} workflow executions for data generation {data_generation_id}")

        # Classify where the data generation is in the pipeline
        if len(workflow_executions) == 0:
            metagenome_workflow_status[data_generation_id] = "Not started"
            metagenome_ids_not_done.append(data_generation_id)
            continue

        # Workflows always have a type
        workflow_types = [we.get("type") for we in workflow_executions]

        if 'nmdc:MagsAnalysis' in workflow_types:
            metagenome_workflow_status[data_generation_id] = "Done"
            continue
        else:
            metagenome_workflow_status[data_generation_id] = "Not done"
            metagenome_ids_not_done.append(data_generation_id)

    # Count and summarize the workflow status
    workflow_status_count = {}
    for status in metagenome_workflow_status.values():
        if status not in workflow_status_count:
            workflow_status_count[status] = 0
        workflow_status_count[status] += 1
    logger.info(f"Workflow status found: {json.dumps(workflow_status_count, indent=2)}")

    # print the IDs of data generations that are not done to standard out 1 id per line
    logger.info(f"{len(metagenome_ids_not_done)} Data generations not done:")
    for data_generation_id in metagenome_ids_not_done:
        print(data_generation_id)


def _get_workflow_executions(api_url, data_generation_id, headers):
    """
    Get workflow executions for a specific data generation.
    """
    workflow_execution_params = {
        'filter': json.dumps({"was_informed_by": data_generation_id}),
        'max_page_size': '10000',
        'projection': 'id, type, version',
    }
    workflow_execution_url = f"{api_url}/nmdcschema/workflow_execution_set"
    workflow_execution_response = requests.get(workflow_execution_url, params=workflow_execution_params, headers=headers)
    if workflow_execution_response.status_code != 200:
        logger.error(f"Error in response: {workflow_execution_response.status_code}")
        return
    workflow_executions = workflow_execution_response.json().get("resources", [])
    return workflow_executions

def batched(iterable, batch_size):
    """Yield successive batches from iterable."""
    it = iter(iterable)
    while batch := list(islice(it, batch_size)):
        yield batch

def get_unpooled_data_generation_ids(site_config, study_id):
    """
    Pool data is in manifest
    
    :param site_config: Description
    :param study_id: Description
    """
    headers = {
        'accept': 'application/json',
        'Authorization': f'Basic {site_config.username}:{site_config.password}'
    }

    api_url = site_config.api_url
    dg_url = f"{api_url}/nmdcschema/data_generation_set"
    do_url = f"{api_url}/nmdcschema/data_object_set"

    # Step 1: Get relevant DataGenerations
    dg_filter = {
        "associated_studies": study_id,
        "analyte_category": "metagenome"
    }
    dg_response = requests.get(
        dg_url,
        params={
            "filter": json.dumps(dg_filter),
            "projection": "id,has_output",
            "max_page_size": "10000"
        },
        headers=headers
    )
    dg_response.raise_for_status()
    data_generations = dg_response.json().get("resources", [])

    # Map DG ID to its has_output DO IDs
    dg_to_outputs = {
        dg["id"]: dg.get("has_output", [])
        for dg in data_generations
    }

    all_do_ids = {do_id for do_ids in dg_to_outputs.values() for do_id in do_ids}

    # Step 2: Get DataObject records in batches
    do_records = {}
    for batch in batched(list(all_do_ids), 100):
        do_filter = {"id": {"$in": batch}}
        do_response = requests.get(
            do_url,
            params={
                "filter": json.dumps(do_filter),
                "projection": "id,in_manifest",
                "max_page_size": "10000"
            },
            headers=headers
        )
        do_response.raise_for_status()
        for do in do_response.json().get("resources", []):
            do_records[do["id"]] = do

    # Step 3: Identify DGs with only unpooled outputs
    unpooled_dg_ids = []
    for dg_id, do_ids in dg_to_outputs.items():
        if all(not do_records.get(do_id, {}).get("in_manifest") for do_id in do_ids):
            unpooled_dg_ids.append(dg_id)

    return unpooled_dg_ids

if __name__ == "__main__":
    cli()
