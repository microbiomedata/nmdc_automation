"""
DB Tools.
"""
import logging
import json
import os
import requests

import click
import requests

from nmdc_automation.config import SiteConfig
from nmdc_automation.api import NmdcRuntimeApi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    pass


@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.option("--update-db", is_flag=True, help="Update the database")
def update_zero_size_files(config_file, update_db):

    # logger.info(f"Updating zero size files from {config_file}")

    site_config = SiteConfig(config_file)
    username = site_config.username
    password = site_config.password


    import requests
    headers = {'accept': 'application/json', 'Authorization': f'Basic {username}:{password}'}

    params = {
        'filter': '{"$or": [{"file_size_bytes": {"$exists": false}},{"file_size_bytes": null},{"file_size_bytes": 0}],"$and": [{"url": {"$exists": true}},{"url": {"$regex": "^https://data.microbiomedata.org/data/"}}]}',
        'max_page_size': '10000', }

    response = requests.get(
        'https://api-dev.microbiomedata.org/nmdcschema/data_object_set', params=params, headers=headers
    )
    if response.status_code != 200:
        logger.error(f"Error in response: {response.status_code}")
        return
    data_objects = response.json().get("resources", [])

    logger.info(f"Found {len(data_objects)} data objects with zero size data files")


    update_query = {
        "update": "data_object_set",
        "updates": [],
    }
    num_zero_size_files = 0
    num_files_not_found = 0
    num_with_file_size = 0
    for dobj in data_objects:
        # get everything after 'data/' in the url
        file_path = dobj['url'].split('data/')[1]
        file_path = os.path.join(site_config.data_dir, file_path)

        logger.info(f"Updating {dobj['id']} /  File size: {dobj.get('file_size_bytes', None)} / File: {file_path}")
        # try to get the file size in bytes
        try:
            file_size = os.path.getsize(file_path)
            logger.info(f"File size: {file_size}")

            # There are zero size files on the file system - log a warning and continue
            if file_size == 0:
                logger.warning(f"Zero size file: {file_path}")
                num_zero_size_files += 1
                continue

            num_with_file_size += 1
            update = {
                "q": {"id": dobj['id']},
                "u": {"$set": {"file_size_bytes": file_size}},
            }
            update_query["updates"].append(update)
        except FileNotFoundError:
            logger.warning(f"File not found: {file_path}")
            num_files_not_found += 1
            continue

    logger.info(f"Number of zero size files: {num_zero_size_files}")
    logger.info(f"Number of files not found: {num_files_not_found}")
    logger.info(f"Number of files with file size: {num_with_file_size}")


    if update_db:
        response = requests.post(
            'https://api-dev.microbiomedata.org/queries:run', json=update_query, headers=headers
        )
        if response.status_code != 200:
            logger.error(f"Error in response: {response.status_code}")
            return
        logger.info("Successfully updated the database")
    else:
        logger.info("Dry run. Database not updated")
        print(json.dumps(update_query, indent=2))



@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.option("--update-db", is_flag=True, help="Update the database")
def fix_data_object_urls(config_file, update_db):

    site_config = SiteConfig(config_file)
    username = site_config.username
    password = site_config.password

    runtime_api = NmdcRuntimeApi(site_config)

    import requests
    headers = {'accept': 'application/json', 'Authorization': f'Basic {username}:{password}'}

    params = {
        'filter': '{"url": {"$regex": "/ficus/"}}',
        'max_page_size': '10000', }

    response = requests.get(
        'https://api.microbiomedata.org/nmdcschema/data_object_set', params=params, headers=headers
    )
    if response.status_code != 200:
        logger.error(f"Error in response: {response.status_code}")
        return
    data_objects = response.json().get("resources", [])

    logger.info(f"Found {len(data_objects)} data objects with incorrect urls")

    data_object_set = []


    for dobj in data_objects:

        logger.info(f"Updating {dobj['id']} {dobj['data_object_type']}")
        # Raw reads don't get a URL
        if dobj['data_object_type'] == 'Metagenome Raw Reads':
            # delete the url
            if 'url' in dobj:
                dobj.pop('url')
            data_object_set.append(dobj)
            continue

        # splitting on / and taking the last 3 elements
        url_parts = dobj['url'].split('/')[-3:]
        new_url = f"https://data.microbiomedata.org/data/{url_parts[0]}/{url_parts[1]}/{url_parts[2]}"
        # logger.info(f"New URL: {new_url}")
        dobj['url'] = new_url
        data_object_set.append(dobj)

    data_objects_update = {"data_object_set": data_object_set}
    data_objects_json = json.dumps(data_objects_update, indent=2)

    # check that the json is valid
    logger.info("Validating metadata")
    val_result = runtime_api.validate_metadata(data_objects_update)
    if val_result['result'] == "All Okay!":
        logger.info("Metadata is valid")

        if update_db:
            logger.info("Updating the database")
            resp = runtime_api.submit_metadata(data_objects_update)
            logger.info(resp)

        else:
            logger.info("Dry run. Database not updated")
            print(data_objects_json)
            return

    else:
        logger.error("Metadata is not valid")
        logger.error(val_result)
        print(data_objects_json)
        return


@cli.command()
@click.argument("site_config_file", type=click.Path(exists=True))
@click.argument("study_id")
def report_study_progress(site_config_file, study_id):
    """
    Generate a study progress report for the NMDC database.

    Arguments:

    - site_config_file: YAML file with site configuration

    The report will be generated in the current directory.
    """
    site_config = SiteConfig(site_config_file)
    username = site_config.username
    password = site_config.password

@cli.command()
@click.argument("config_file", type=click.Path(exists=True))
@click.argument("id_list_file", type=click.Path(exists=True))
def release_jobs(config_file, id_list_file):
    """
    Release jobs from a list of IDs.
    """
    logger.info(f"Releasing jobs from {id_list_file} using config {config_file}")

    site_config = SiteConfig(config_file)

    nmdc_api = NmdcRuntimeApi(site_config)
    # Set up the API URL
    api_url = site_config.api_url

    # Read the job IDs from the file
    with open(id_list_file, 'r') as f:
        job_ids = [line.strip() for line in f if line.strip()]
    logger.info(f"Found {len(job_ids)} job IDs to release")
    for job_id in job_ids:
        logger.info(f"Releasing job {job_id}")
        resp = nmdc_api.release_job(job_id)
        if resp is None:
            logger.warning(f"Failed to release job {job_id}: No response returned (job not found or already released).")
        else:
            logger.info(resp)

    headers = {'accept': 'application/json', 'Authorization': f'Basic {username}:{password}'}
    # Get the study from the studies/{study_id} endpoint, e.g. https://api.microbiomedata.org/studies/nmdc%3Asty-11-33fbta56
    # encode the study_id
    study_id = study_id.replace(":", "%3A")
    study_resp = requests.get(
        f'https://api.microbiomedata.org/studies/{study_id}', headers=headers
    )

    if study_resp.status_code != 200:
        logger.error(f"Error in response: {study_resp.status_code}")
        return
    study = study_resp.json()
    # study_name is not always present
    study_name = study.get("name", "Unnamed Study")
    logger.info(f"Study: {study['id']}, Name: {study_name}")

    # Get the data generations for the study
    data_generation_params = {
        'filter': f'{{"associated_studies": "{study["id"]}"}}',
        'max_page_size': '5000'
    }
    data_generation_response = requests.get(
        'https://api.microbiomedata.org/nmdcschema/data_generation_set', params=data_generation_params, headers=headers
    )
    if data_generation_response.status_code != 200:
        logger.error(f"Error in response: {data_generation_response.status_code}")
        return
    data_generations = data_generation_response.json().get("resources", [])
    logger.info(f"Found {len(data_generations)} data generations for study {study['id']}")
    # Organized by type and analyte category
    study_progress = {}
    for dg in data_generations:
        dg_type = dg['type']
        analyte_category = dg.get('analyte_category', 'UnknownCategory')
        if dg_type not in study_progress:
            study_progress[dg_type] = {}
        if analyte_category not in study_progress[dg_type]:
            study_progress[dg_type][analyte_category] = {}

        # Get workflow_execution(s) that was_informed_by the data generation and
        # determine if annotation is complete, partially complete, or not started
        workflow_execution_params = {
            'filter': f'{{"was_informed_by": "{dg["id"]}"}}',
            'max_page_size': '1000'
        }
        workflow_execution_response = requests.get(
            'https://api.microbiomedata.org/nmdcschema/workflow_execution_set', params=workflow_execution_params, headers=headers
        )
        if workflow_execution_response.status_code != 200:
            logger.error(f"Error in response: {workflow_execution_response.status_code}")
            return
        workflow_executions = workflow_execution_response.json().get("resources", [])
        logger.info(f"Found {len(workflow_executions)} workflows for {dg_type} / {analyte_category} :  {dg['id']}")



    #
    #         # Get workflow_execution(s) that was_informed_by the data generation
    #         data_gen_workflows= {dg['id']: []}
    #         workflow_execution_params = {
    #             'filter': f'{{"was_informed_by": "{dg["id"]}"}}',
    #             'max_page_size': '1000'
    #         }
    #         workflow_execution_response = requests.get(
    #             'https://api.microbiomedata.org/nmdcschema/workflow_execution_set', params=workflow_execution_params, headers=headers
    #         )
    #         if workflow_execution_response.status_code != 200:
    #             logger.error(f"Error in response: {workflow_execution_response.status_code}")
    #             return
    #         workflow_executions = workflow_execution_response.json().get("resources", [])
    #         logger.info(f"Found {len(workflow_executions)} workflow executions for data generation {dg['id']}")
    #         # Count the number of workflow executions by type and version
    #         for we in workflow_executions:
    #             we_type = we.get('type', 'UnknownType')
    #             # version may not be present
    #             we_version = we.get('version', 'UnknownVersion')
    #
    #             data_gen_workflows[dg['id']].append((we_type, we_version))
    #
    #         report[study['id']]['data_generations'][dg_type][analyte_category].append(data_gen_workflows)
    #
    # # Summarize the report -
    # # Study ID, Study Name, Data Generation Type, Analyte Category, Number of Data Generations, Min/Max/Average Workflow Executions
    # # Report format:
    # # Study ID, Study Name, Data Generation Type, Analyte Category, Number of Data Generations, Min/Max/Average Workflow Executions
    # report_summary = []
    # for study_id, study in report.items():
    #      for sstudy_name, data_generations in study['data_generations'].items():
    #         for dg_type, analyte_categories in data_generations.items():
    #             for analyte_category, data_gen_workflows in analyte_categories.items():
    #                 num_data_generations = len(data_gen_workflows)
    #                 min_workflow_executions = min([len(workflows) for workflows in data_gen_workflows])
    #                 max_workflow_executions = max([len(workflows) for workflows in data_gen_workflows])
    #                 avg_workflow_executions = sum([len(workflows) for workflows in data_gen_workflows]) / num_data_generations
    #                 report_summary.append((study_id, study['name'], dg_type, analyte_category, num_data_generations, min_workflow_executions, max_workflow_executions, avg_workflow_executions))
    # # Write the report to a CSV file
    # report_file = os.path.join(os.getcwd(), "study_progress_report.csv")
    # with open(report_file, "w") as f:
    #     f.write("Study ID, Study Name, Data Generation Type, Analyte Category, Number of Data Generations, Min Workflow Executions, Max Workflow Executions, Average Workflow Executions\n")
    #     for row in report_summary:
    #         f.write(",".join([str(x) for x in row]) + "\n")


def _measure_annotation_completeness(dg_type, analyte_category, workflow_executions: list) -> str:
    """
    Measure the completeness of the annotation for a given workflow execution.

    Args:
        workflow_executions (list): List of workflow executions.

    Returns:
        str: Completeness status.
    """
    if not workflow_executions:
        return "Not Started"

    # Completeness status depends on the type and analyte category
    # Metagenome sequencing
    if dg_type == 'nmdc:NucleotideSequencing' and analyte_category == 'metagenome':
        # Annotation is complete if there are 5 or more workflow executions and at least one MagsAnalysis workflow
        mags_analysis_workflows = [we for we in workflow_executions if we['type'] == 'nmdc:MagsAnalysis']
        if len(workflow_executions) >= 5 and mags_analysis_workflows:
            return "Complete"
        else:
            return "Partially Complete"
    # Metatranscriptome sequencing
    elif dg_type == 'nmdc:NucleotideSequencing' and analyte_category == 'metatranscriptome':
        pass

    # Mass Spectrometry
    elif dg_type == 'nmdc:MassSpectrometry':
        # Annotation is complete if there are 3 or more workflow executions and at least one MagsAnalysis workflow
        pass




if __name__ == "__main__":
    cli()
