"""
Run reports for the NMDC pipeline.
"""
import logging
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

    biosamples = _get_biosamples(api_url, study_id, headers)
    logger.info(f"Found {len(biosamples)} biosamples for study {study_id}")

    # Sort biosamples by analysis type
    analysis_type_count = {}
    # analysis type is a list of strings
    for biosample in biosamples:
        analysis_types = biosample.get("analysis_type", [])
        for analysis_type in analysis_types:
            if analysis_type not in analysis_type_count:
                analysis_type_count[analysis_type] = 0
            analysis_type_count[analysis_type] += 1

    # Summarize the biosample analysis types
    logger.info(f"Analysis types found: {json.dumps(analysis_type_count, indent=2)}")

    # Get DataGenerations for the study
    data_generations = _get_data_generations(api_url, study_id, headers)
    logger.info(f"Found {len(data_generations)} data generations for study {study_id}")

    # Sort data generations by analyte category
    metagenome_data_generations = [dg for dg in data_generations if dg.get("analyte_category") == "metagenome"]

    # Find workflow executions for each data generation and assess their status
    metagenome_workflow_status = {}
    for data_generation in metagenome_data_generations:
        data_generation_id = data_generation.get("id")
        workflow_executions = _get_workflow_executions(api_url, data_generation_id, headers)
        # logger.info(f"Found {len(workflow_executions)} workflow executions for data generation {data_generation_id}")

        # Classify where the data generation is in the pipeline
        if len(workflow_executions) == 0:
            metagenome_workflow_status[data_generation_id] = "Not started"
            continue

        # Workflows always have a type
        workflow_types = [we.get("type") for we in workflow_executions]

        if 'nmdc:MagsAnalysis' in workflow_types:
            metagenome_workflow_status[data_generation_id] = "Done"
            continue
        if 'nmdc:MetagenomeAnnotaiton' in workflow_types:
            metagenome_workflow_status[data_generation_id] = "Annotated"
            continue
        if 'nmdc:MetagenomeAssembly' in workflow_types:
            metagenome_workflow_status[data_generation_id] = "Assembled"
            continue
        if 'nmdc:ReadQcAnalysis' in workflow_types:
            metagenome_workflow_status[data_generation_id] = "Reads QC"
            continue

    # Count and summarize the workflow status
    workflow_status_count = {}
    for status in metagenome_workflow_status.values():
        if status not in workflow_status_count:
            workflow_status_count[status] = 0
        workflow_status_count[status] += 1
    logger.info(f"Workflow status found: {json.dumps(workflow_status_count, indent=2)}")







def _get_biosamples(api_url, study_id, headers):
    """
    Get biosamples for a specific study.
    """
    biosample_params = {
        'filter': json.dumps({"associated_studies": study_id}),
        'max_page_size': '10000',
        'projection': 'id, type, analysis_type, associated_studies, ecosystem, ecosystem_category, ecosystem_type',
    }
    biosample_url = f"{api_url}/nmdcschema/biosample_set"
    biosample_response = requests.get(biosample_url, params=biosample_params, headers=headers)
    if biosample_response.status_code != 200:
        logger.error(f"Error in response: {biosample_response.status_code}")
        return

    biosamples = biosample_response.json().get("resources", [])
    return biosamples

def _get_data_generations(api_url, study_id, headers):
    """
    Get data generations for a specific study.
    """
    data_generation_params = {
        'filter': json.dumps({"associated_studies": study_id}),
        'max_page_size': '10000',
        'projection': 'id, type, analyte_category, has_output',
    }
    data_generation_url = f"{api_url}/nmdcschema/data_generation_set"
    data_generation_response = requests.get(data_generation_url, params=data_generation_params, headers=headers)
    if data_generation_response.status_code != 200:
        logger.error(f"Error in response: {data_generation_response.status_code}")
        return
    data_generations = data_generation_response.json().get("resources", [])
    return data_generations

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



if __name__ == "__main__":
    cli()
