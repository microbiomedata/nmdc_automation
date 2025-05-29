"""
Run reports for the NMDC pipeline.
"""
import logging
from itertools import islice
import json
import requests

import click

from nmdc_automation.config import SiteConfig


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    pass


@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.argument("study_id")
def study_report(config_file, study_id):
    """
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
    logger.info(f"{len(metagenome_ids_not_done)}Data generations not done:")
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
