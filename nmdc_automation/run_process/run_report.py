"""
Run reports for the NMDC pipeline.
"""
import logging
from itertools import islice
import json
import requests
from typing import List
import click

from nmdc_automation.api import NmdcRuntimeApi
from nmdc_automation.config import SiteConfig


logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
                    )
logger = logging.getLogger(__name__)


@click.group()
def cli():
    pass


@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.argument("study_id")
def study_report(config_file, study_id, pipeline = None):
    """
    Generate a report for a specific study.
    """
    logger.info(f"Generating report for study {study_id} from {config_file}")
    site_config = SiteConfig(config_file)
    runtime_api = NmdcRuntimeApi(site_config)
    username = site_config.username
    password = site_config.password

    study_status_query = build_query()
    

    

    # Set up the API URL
    api_url = site_config.api_url
    headers = {'accept': 'application/json', 'Authorization': f'Basic {username}:{password}'}

    # get default aggregation for a study_id
    incomplete_runs = run_aggregation(api_url, headers, study_id, pipeline)
    logger.info(f"Found {len(incomplete_runs)} categories of incomplete runs")



def run_aggregation(runtime_api, api_url, headers, study_id: str, pipeline: List[dict], aggregate = "data_generation_set",
                    analyte_category = "metagenome", manifest = False, qc_status_exists = False, 
                    qc_comment_exists = False, dg_output = True, wf_type = "nmdc:MagsAnalysis", len_wfe = 5):
    """
    Submit an aggregation pipeline to the NMDC run_query endpoint.

    :param api_url: Base API URL (e.g. https://api.microbiomedata.org)
    :param aggregate: Collection name (e.g. 'biosample_set')
    :param pipeline: MongoDB aggregation pipeline (list of dicts)
    :return: Parsed JSON response
    """

    query_url = f"{api_url}/queries:run"
    if not pipeline:
        pipeline = build_pipeline(study_id, analyte_category, manifest, qc_status_exists, qc_comment_exists, dg_output,wf_type, len_wfe)

    payload = {
        "aggregate": aggregate,
        "pipeline": pipeline
    }
    resp = runtime_api.run_query(data_generation_update_query)

    query_response = requests.post(query_url, headers=headers, json=payload)
    query_response.raise_for_status()

    return query_response.json()


def build_pipeline(study_id: str, analyte_category: str, 
                      manifest: bool, qc_status_exists: bool, qc_comment_exists: bool, dg_output: bool,
                      wf_type: str, len_wfe: int) -> dict:
    """
    Consolidate the above query stages into aggregation for submission to api
    """
    pipeline = sum([study_and_analyte(study_id, analyte_category),
                lookup_do_wf_job(),
                manifest_and_qc(manifest, qc_status_exists, qc_comment_exists, dg_output),
                set_completion_reqs(wf_type, len_wfe),
                group_results()
                ], [])
    return pipeline

def agg_match(field: str, value: str) -> List[dict]:
    """
    For personalized match queries
    
    :param field: Schema slot
    :param value: Schema value
    """
    return [{"$match": {field: value}}]

def study_and_analyte(study_id: str, analyte_category = "metagenome") -> List[dict]:
    """
    Looks up by study ID and analyte type
    :param study_id: Study ID
    :param analyte_category: analyte cagetogry, can be metagenome, metatranscriptome, and maybe one day, more options
    """
    return [{"$match": {"associated_studies": study_id, "analyte_category": analyte_category}}]

def lookup_do_wf_job() -> List[dict]:
    """
    Performs a lookup / join from the data object set (do), workflow execution set (wf), and job collections.
    DO for checking if in manifest
    WF for seeing what executions exist
    JOB for seeing what's been attempted
    WF and JOB are sorted for easier grouping later on.
    """
    return [{"$lookup": {"from": "data_object_set", "localField": "has_output", "foreignField": "id", "as": "data_object_set"}}, 
            {"$lookup": {"from": "workflow_execution_set", "localField": "id", "foreignField": "was_informed_by", 
                         "pipeline": [{"$sort": {"type": 1}}], "as": "workflow_execution_set"}}, 
            {"$lookup": {"from": "jobs", "localField": "id", "foreignField": "config.was_informed_by", 
                         "pipeline": [{"$sort": {"config.activity.type": 1}}], "as": "jobs"}}]

def manifest_and_qc(manifest = False, qc_status_exists = False, qc_comment_exists = False, dg_output = True) -> List[dict]:
    """
    Docstring for manifest_and_qc
    
    :param types: Booleans
    :param manifest: Whether the data object exists in the manifest (pooling). For now we want False (unpooled)
    :param qc_status_exists: Whether there's qc status Fail or not. We want good QC to submit, so False
    :param qc_comment_exists: Same as qc_status, just an extra check in case only one exists due to oversight
    :param dg_output: Whether there's an output from data_generation_set. This is what goes into our RQC workflows. 
        If there isn't an output, we don't have an input. 
    """
    return [{"$match": {"data_object_set.in_manifest": {"$exists": manifest},
                        "workflow_execution_set.qc_status": {"$exists": qc_status_exists},
                        "workflow_execution_set.qc_comment": {"$exists": qc_comment_exists},
                        "has_output": {"$exists": dg_output}}}]

def set_completion_reqs(wf_type = "nmdc:MagsAnalysis", len_wfe = 5) -> List[dict]:
    """
    What we define to be "completed"
    Typically, we look for the 5 workflow types (RQC, Assembly, Annotation, MAGs, and ReadsbasedTaxonomy (RBT/RBA))
    This is per data generation set ID.
    :param wf_type: Can be any of the define WorkflowExecution slot https://microbiomedata.github.io/nmdc-schema/WorkflowExecution/
    :param len_wfe: Whatever number of workflows you're looking for
    """
    return[{"$match": {"$or": [{"$expr": {"$lt": [{"$size": "$workflow_execution_set"}, len_wfe]}}, 
                               {"workflow_execution_set": {"$not": {"$elemMatch": {"type": wf_type}}}}]}}]

def group_results() -> List[dict]:
    """
    This grouping allows us to compare what exists in WFE and Jobs with dates of when they were run.
    Allows us to look at whether there's a specific set of dates where a lot of issues may have occurred.
    """
    return [{"$group": {"_id": {"wfex_type": "$workflow_execution_set.type", "job_wfex_type": "$jobs.config.activity.type"}, 
                        "dgs_count": {"$sum": 1},
                        "executions": {"$push": {"id": "$id", "wfex_id": "$workflow_execution_set.id", "wfex_end": "$workflow_execution_set.ended_at_time", 
                                                 "job_id": "$jobs.id", "job_wfid": "$jobs.config.activity_id", "job_start": "$jobs.created_at"}}}}]



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
