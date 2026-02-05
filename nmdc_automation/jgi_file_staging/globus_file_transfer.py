import configparser
import sys
from datetime import datetime
import pandas as pd
import os
import logging
from pathlib import Path, PurePosixPath
import subprocess
import argparse
from typing import List, Optional, Union
from nmdc_automation.jgi_file_staging.file_restoration import update_sample_in_mongodb, update_file_statuses
from nmdc_automation.config import SiteConfig, StagingConfig
from nmdc_api_utilities.auth import NMDCAuth
from nmdc_api_utilities.data_staging import JGISampleSearchAPI, GlobusTaskAPI

logging.basicConfig(filename='file_staging.log',
                    format='%(asctime)s.%(msecs)03d %(levelname)s {%(module)s} [%(funcName)s] %(message)s',
                    datefmt='%Y-%m-%d,%H:%M:%S', level=logging.DEBUG, force=True)

OUTPUT_DIR = Path(".")


def get_project_globus_manifests(project_name: str, site_configuration: SiteConfig, staging_configuration: StagingConfig) -> List[str]:
    """
    Retrieve all of the globus manifest files for sample files to be transferred from Globus to MongoDB for a sequencing project
    :param project_name: name of sequencing project
    :param site_configuration: 
   
    :return: list of manifest file names
    """
    query_dict = {'sequencing_project_name': project_name, 'file_status': {'$nin': ['PURGED', 'EXPIRED']}}
    samples_list = JGISampleSearchAPI(env=site_configuration.env,
                                       auth=NMDCAuth(client_id=site_configuration.client_id,
                                                      client_secret=site_configuration.client_secret,
                                                      env=site_configuration.env)
                                       ).list_jgi_samples(query_dict)
    # Get all samples for the project that we would like to be restored (are not PURGED or EXPIRED)
    
    samples_df = pd.DataFrame(samples_list)
    samples_df = samples_df[pd.notna(samples_df.request_id)]
    samples_df['request_id'] = samples_df['request_id'].astype(int)
    manifests_list = []
    globus_manifest_files = [get_globus_manifest(int(request_id), project_name, staging_configuration) for request_id in
                             samples_df.request_id.unique()]

    return globus_manifest_files


def get_globus_manifest(request_id: int, project_name: str, staging_configuration: StagingConfig) -> str:
    """
    Retrieve the globus manifest file for a given request ID from JGI via Globus
    :param request_id: JGI file restoration request ID
    :param config_file: path to configuration file
    :param config: configparser object with parameters for globus transfers
    :return: manifest file name
    """
    
    jgi_globus_id = staging_configuration.jgi_globus_id
    nersc_globus_id = staging_configuration.nersc_globus_id
    nersc_manifests_directory = Path(staging_configuration.staging_dir, project_name, 'globus_manifests')
    globus_root_dir = staging_configuration.globus_root_dir.strip('/')

    globus_path = PurePosixPath(globus_root_dir) / f"R{request_id}"

    sub_output = subprocess.run(['globus', 'ls', f'{jgi_globus_id}:/{globus_path}'],
                                capture_output=True, text=True)
    sub_output.check_returncode()
    sub_output_split = sub_output.stdout.split('\n')
    logging.debug(f"request_id: {request_id} globus ls: {sub_output_split}")

    manifest_files = [fn for fn in sub_output_split if 'Globus_Download' in fn]
    if not manifest_files:
        logging.warning("No Globus_Download file found")
        return ''
    manifest_file_name = manifest_files[0]
    logging.debug(f"manifest filename {manifest_file_name}")

    if Path(nersc_manifests_directory, manifest_file_name).exists():
        return manifest_file_name

    logging.debug(f"transferring {manifest_file_name}")
    manifest_sub_out = subprocess.run(['globus', 'transfer', '--sync-level', 'exists',
        f"{jgi_globus_id}:/{globus_path}/{manifest_file_name}",
        f"{nersc_globus_id}:{nersc_manifests_directory}/{manifest_file_name}"],
        capture_output=True, text=True)
    manifest_sub_out.check_returncode()
    logging.debug(f"manifest globus transfer: {manifest_sub_out.stdout}, errors: {manifest_sub_out.stderr}")

    return manifest_file_name


def create_globus_dataframe(project_name: str, staging_configuration: StagingConfig, site_configuration: StagingConfig) -> pd.DataFrame:
    """
    Create a dataframe from the globus manifest files for a given project
    :param project_name: name of project
    :param config: configparser object with parameters for globus transfers
    :return: dataframe with globus manifest file information"""

    globus_manifest_files = get_project_globus_manifests(project_name, site_configuration, staging_configuration)

    globus_df = pd.DataFrame()
    nersc_manifests_directory = os.path.join(staging_configuration.staging_dir, project_name, 'globus_manifests')
    for manifest in globus_manifest_files:
        mani_df = pd.read_csv(os.path.join(nersc_manifests_directory, manifest))
        subdir = f"R{manifest.split('_')[2]}"
        mani_df['subdir'] = subdir
        globus_df = pd.concat([globus_df, mani_df], ignore_index=True)
    return globus_df


def create_globus_batch_file(project: str, site_configuration: SiteConfig, staging_configuration: StagingConfig,
                             output_dir: Optional[Union[str, Path]]=None) -> tuple[str, pd.DataFrame]:
    """
    Creates batch file for the globus file transfer
    :param project: name of sequencing project
    :param site_configuration: site configuration object for API credentials necessary to query the database
    :param staging_configuration: staging configuration object for globus parameters
    :param output_dir: directory to write the globus batch file to
    :return: globus batch file name and dataframe with sample files being transferred
    1) update statuses of files
    1) get samples from database that have been restored from tape (file_status: 'ready')
    2) create a dataframe from the Globus manifests
    3) write to globus batch file
    """
    if output_dir is None:
        output_dir = Path(".")
    else:
        output_dir = Path(output_dir)

    update_file_statuses(project=project, site_configuration=site_configuration)
    samples_list = JGISampleSearchAPI(env=site_configuration.env,
                                       auth=NMDCAuth(client_id=site_configuration.client_id,
                                                      client_secret=site_configuration.client_secret,
                                                      env=site_configuration.env)
                                       ).list_jgi_samples({'jgi_sequencing_project': project, 'jdp_file_status': 'ready'})
    samples_df = pd.DataFrame(samples_list)
    if samples_df.empty:
        logging.debug(f"no samples ready to transfer")
        sys.exit('no samples ready to transfer, try running file_restoration.py -u')
    samples_df = samples_df[pd.notna(samples_df.request_id)]
    samples_df['request_id'] = samples_df['request_id'].astype(int)
    # logging.debug(f"nan request_ids {samples_df['request_id']}")
    root_dir = staging_configuration.globus_root_dir
    # e.g. /global/cfs/cdirs/m3408/aim2/dev/staged_files/blanchard_ficus/analysis_files
    dest_root_dir = os.path.join(site_configuration.stage_dir, f'{project}', 'analysis_files')
    globus_df = create_globus_dataframe(project, staging_configuration, site_configuration)

    logging.debug(f"samples_df columns {samples_df.columns}, globus_df columns {globus_df.columns}")
    globus_analysis_df = pd.merge(samples_df, globus_df, left_on='jdp_file_id', right_on='file_id')
    write_list = []
    for idx, row in globus_analysis_df.iterrows():
        filepath = os.path.join(root_dir, row.subdir, row['directory/path'], row.file_name)
        dest_file_path = os.path.join(dest_root_dir, row.ap_gold_id, row.file_name)
        write_list.append(f"{filepath} {dest_file_path}")
    globus_batch_filename = (
            output_dir / f"{project}_{samples_df['request_id'].unique()[0]}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_globus_batch_file.txt"
    )

    with open(globus_batch_filename, 'w') as f:
        f.write('\n'.join(write_list))
    return str(globus_batch_filename), globus_analysis_df


def submit_globus_batch_file(project: str, staging_configuration: StagingConfig, site_configuration: SiteConfig) -> str:
    """
    *Must run globus login first!*
    create a globus batch file and submit it to globus
    :param project: name of project
    :param config_file: path to configuration file
    1) create the globus batch file
    2) submit the globus batch file using the globus CLI
    3) insert globus task into the database
    """
    jgi_globus_id = staging_configuration.jgi_globus_id
    nersc_globus_id = staging_configuration.nersc_globus_id

    batch_file, globus_analysis_df = create_globus_batch_file(project,
                                                              staging_configuration, site_configuration=site_configuration)
    output = subprocess.run(['globus', 'transfer', '--batch', batch_file, jgi_globus_id,
                             nersc_globus_id], capture_output=True, text=True)

    logging.debug(output.stdout)
    globus_analysis_df.apply(lambda x: update_sample_in_mongodb(x, {'file_status': 'READY'}, site_configuration), axis=1)

    insert_globus_status_into_mongodb(output.stdout.split('\n')[1].split(':')[1], 'IN_PROGRESS', site_configuration)
    return output.stdout


def insert_globus_status_into_mongodb(task_id: str, task_status: str, site_configuration):
    """
    Insert globus task into MongoDB via the GlobusTaskAPI
    :param task_id: globus task id
    :param task_status: task status"""
    globus_api = GlobusTaskAPI(env=site_configuration.env,
                              auth=NMDCAuth(client_id=site_configuration.client_id,
                                             client_secret=site_configuration.client_secret,
                                             env=site_configuration.env)
                              )
    globus_api.create_globus_task({'task_id': task_id, 'task_status':task_status})


def get_globus_task_status(task_id: str):
    """
    Get globus task status via the globus CLI
    :param task_id: globus task id
    :return: task status"""
    output = subprocess.run(['globus', 'task', 'show', task_id], capture_output=True, text=True)
    return output.stdout.split('\n')[6].split(':')[1].strip()


def update_globus_task_status(task_id: str, task_status: str, site_configuration):
    """
    Update globus task status in MongoDB via the GlobusTaskAPI
    :param task_id: globus task id
    :param task_status: new task status
    :param site_configuration: Site configuration object"""
    globus_api = GlobusTaskAPI(env=site_configuration.env,
                              auth=NMDCAuth(client_id=site_configuration.client_id,
                                             client_secret=site_configuration.client_secret,
                                             env=site_configuration.env)
                              ).update_globus_task(task_id, {'task_status': task_status})

def update_globus_statuses(site_configuration: SiteConfig):
    """
    Get all Globus tasks that are not in the 'SUCCEEDED' status and update their status
    """
    tasks = GlobusTaskAPI(env=site_configuration.env,
                              auth=NMDCAuth(client_id=site_configuration.client_id, 
                                            client_secret=site_configuration.client_secret, 
                                            env=site_configuration.env)
                              ).get_globus_tasks({'task_status': {'$ne': 'SUCCEEDED'}})
    for task in tasks:
        task_status = get_globus_task_status(task['task_id'])
        update_globus_task_status(task['task_id'], task_status, site_configuration)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project_name')
    parser.add_argument('config_file')
    parser.add_argument('-r', '--request_id', help='Globus request id (from file restoration api)')
    parser.add_argument('-u', '--update_globus_statuses', action='store_true',
                        help='update globus task statuses', default=False)
    parser.add_argument('-g', '--get_project_manifests', action='store_true',
                        help='get all globus project manifests', default=False)

    args = vars((parser.parse_args()))
    config_file = args['config_file']
    site_configuration = SiteConfig(args['site_config_file'])
    
    if args['request_id']:
        get_globus_manifest(args['request_id'], config_file=config_file)
    elif args['update_globus_statuses']:
        update_globus_statuses(site_configuration)
    elif args['get_project_manifests']:
        get_project_globus_manifests(args['project_name'], site_configuration, config_file)
    else:
        submit_globus_batch_file(args['project_name'], args['config_file'], site_configuration)

