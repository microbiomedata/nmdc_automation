import configparser
import sys
from datetime import datetime
import pandas as pd
import numpy as np
import requests
import os
import logging
import time
import argparse
from pathlib import Path
from itertools import chain
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from nmdc_automation.db.nmdc_mongo import get_db
from nmdc_automation.jgi_file_staging.models import Sample, SequencingProject
from typing import List, Dict, Any
from pydantic import ValidationError

logging.basicConfig(filename='file_staging.log',
                    format='%(asctime)s.%(msecs)03d %(levelname)s {%(module)s} [%(funcName)s] %(message)s',
                    datefmt='%Y-%m-%d,%H:%M:%S', level=logging.DEBUG, force=True)

"""
1. Get sample metadata and enter into mongodb
2. Restore files from tape
    repeat until all files restored
3. Get Globus manifests for restored files
4. Create and submit Globus batch file

Config file contains parameters that can change.
"""

ACCEPT = "application/json"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    reraise=True
)
def get_request(url: str, ACCESS_TOKEN: str) -> List[Dict[str, Any]]:
    """
    Make a GET request to the specified URL with the provided access token.
    
    :param url: URL to send the request to.
    :param ACCESS_TOKEN: Access token for authorization.
    :return: A list of dictionaries containing the JSON response data if the request is successful.
             Returns an empty list if the status code is 404 (Not Found) or 403 (Forbidden).
             Raises a requests.exceptions.RequestException for other HTTP errors.
    """
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "accept": ACCEPT, 'User-agent': 'nmdc bot 0.1'}
    response = requests.get( url, headers=headers, verify=_verify())
    if response.status_code == 200:
        return response.json()
    # warn and carry on if not found / forbidden
    elif response.status_code == 404:
        logging.warning(f"404 Not Found: {url}")
        return []
    elif response.status_code == 403:
        logging.warning(f"403 Forbidden: {url}")
        return []
    # raise an exception for other errors
    else:
        logging.error(f"Error {response.status_code}: {response.text}")
        raise requests.exceptions.RequestException(f"Error {response.status_code}: {response.text}")


def get_samples_data(project_name: str, config_file: str, mdb, csv_file: str = None) -> None:
    """
    Get JGI sample metadata using the gold API and store in a mongodb
    :param project_name: Name of project_name (e.g., GROW, Bioscales, NEON)
    :param config_file: Config file with parameters
    :param csv_file: csv file with files to stage
    :return:
    """
    # check_restore_status()
    config = configparser.ConfigParser()
    config.read(config_file)
    ACCESS_TOKEN = get_access_token()
    seq_project = mdb.sequencing_projects.find_one({'project_name': project_name})
    if csv_file is not None:
        gold_analysis_files_df = pd.read_csv(csv_file)
    else:
        files_df = get_sample_files(seq_project['proposal_id'], ACCESS_TOKEN)
        gold_analysis_files_df = get_analysis_files_df(seq_project['proposal_id'], files_df, ACCESS_TOKEN,
                                                       eval(config['JDP']['remove_files']))

    gold_analysis_files_df['project_name'] = project_name
    logging.debug(f'number of samples to insert: {len(gold_analysis_files_df)}')
    logging.debug(gold_analysis_files_df.head().to_dict('records'))

    sample_objects = sample_records_to_sample_objects(gold_analysis_files_df.to_dict('records'))
    if len(sample_objects) > 0:
        mdb.samples.insert_many(sample_objects)
        logging.info(f"Inserted {len(sample_objects)} samples into mongodb")


def get_analysis_files_df(proposal_id: int, files_df: pd.DataFrame, ACCESS_TOKEN: str, remove_files: List[str]) -> pd.DataFrame:
    gold_analysis_data = get_analysis_projects_from_proposal_id(proposal_id, ACCESS_TOKEN)
    gold_analysis_data_df = pd.DataFrame(gold_analysis_data)
    gold_analysis_files_df = pd.merge(gold_analysis_data_df, files_df, left_on='itsApId',
                                      right_on='analysis_project_id')
    gold_analysis_files_df['file_type'] = gold_analysis_files_df["file_type"].astype(str)
    gold_analysis_files_df['analysis_project_id'] = gold_analysis_files_df['analysis_project_id'].astype(str)
    gold_analysis_files_df['seq_id'] = gold_analysis_files_df['seq_id'].astype(str)
    gold_analysis_files_df['update_date'] = datetime.now()
    gold_analysis_files_df['request_id'] = None
    gold_analysis_files_df = remove_unneeded_files(gold_analysis_files_df, remove_files)
    return gold_analysis_files_df


def get_access_token() -> str:
    url = f'https://gold-ws.jgi.doe.gov/exchange?offlineToken={os.environ.get("OFFLINE_TOKEN")}'
    verify = _verify()

    response = requests.get(url, verify=verify)
    sys.exit(f"get_access_token: {response.text}") if response.status_code != 200 else None

    return response.text


def _verify() -> bool:
    """
    Handle different variations of the Verify environment var. This var may not be set in all environments,
    or may be set to different values. This function will return True or False based on the value of the
    environment variable.
    """
    verify = os.getenv('VERIFY', 'False').strip().lower()
    if verify == 'true':
        return True
    elif verify == 'false':
        return False
    else:
        raise ValueError(f"Invalid value for VERIFY environment variable: {verify}")


def check_access_token(ACCESS_TOKEN: str) -> str:
    url = 'https://gold-ws.jgi.doe.gov/api/v1/projects?biosampleGoldId=Gb0291582'
    gold_biosample_response = get_request(url, ACCESS_TOKEN)
    if gold_biosample_response:
        return ACCESS_TOKEN
    else:
        return get_access_token()


def get_sample_files(proposal_id: int, ACCESS_TOKEN: str) -> pd.DataFrame:
    """
    Get all sample files for a project_name
    :param proposal_id: proposal id
    :param ACCESS_TOKEN: gold api token
    :return: list of sample files for each biosample
    """

    samples_df = pd.DataFrame({'Biosample ID': get_biosample_ids(proposal_id, ACCESS_TOKEN)})
    all_files_list = []
    for idx, biosample_id in samples_df.itertuples():
        logging.debug(f"biosample {biosample_id}")
        ACCESS_TOKEN = check_access_token(ACCESS_TOKEN)
        seq_id_list = get_sequence_id(biosample_id, ACCESS_TOKEN)
        for seq_id in seq_id_list:
            sample_files_list = get_files_and_agg_ids(seq_id, ACCESS_TOKEN)
            create_all_files_list(sample_files_list, biosample_id, seq_id, all_files_list)

    return pd.DataFrame(all_files_list)


def get_biosample_ids(proposal_id: int, ACCESS_TOKEN: str) -> List[str]:
    url = f'https://gold-ws.jgi.doe.gov/api/v1/biosamples?itsProposalId={proposal_id}'
    response_json = get_request(url, ACCESS_TOKEN)
    biosample_ids = [sample['biosampleGoldId'] for sample in response_json]
    return biosample_ids


def get_sequence_id(biosample_id: str, ACCESS_TOKEN: str) -> List[str]:
    """
    Given a GOLD biosample ID, retrieve the list of JGI analysis id.

    :param biosample_id: The GOLD biosample ID.
    :param ACCESS_TOKEN: The API access token.
    :return: A list of sequencing IDs associated with the biosample.
    """
    gold_biosample_url = f'https://gold-ws.jgi.doe.gov/api/v1/analysis_projects?biosampleGoldId={biosample_id}'
    gold_biosample_response = get_request(gold_biosample_url, ACCESS_TOKEN)
    sequence_id_list = []
    if not gold_biosample_response:
        return sequence_id_list
    for seq in gold_biosample_response:
        # only get the sequencing id for metagenome and metatranscriptome
        ap_type = seq.get('apType')
        if ap_type in ["Metagenome Analysis", "Metatranscriptome Analysis"]:
            sequence_id = seq.get('itsApId')
            if sequence_id:
                sequence_id_list.append(sequence_id)

    return sequence_id_list


def get_analysis_projects_from_proposal_id(proposal_id: int, ACCESS_TOKEN: str) -> List[dict]:
    gold_analysis_url = f'https://gold-ws.jgi.doe.gov/api/v1/analysis_projects?itsProposalId={proposal_id}'
    gold_analysis_data = get_request(gold_analysis_url, ACCESS_TOKEN)
    ap_type_gold_analysis_data = [proj for proj in gold_analysis_data if
                                  proj['apType'] in ["Metagenome Analysis", "Metatranscriptome Analysis"]]
    return ap_type_gold_analysis_data


def get_files_and_agg_ids(sequencing_id: str, ACCESS_TOKEN: str) -> List[dict]:
    # Given a JGI sequencing ID, get the list of files and agg_ids associated with the biosample
    logging.debug(f"sequencing_id {sequencing_id}")
    seqid_url = f"https://files.jgi.doe.gov/search/?q={sequencing_id}&f=project_id&a=false&h=false&d=asc&p=1&x=10&api_version=2"
    files_data = get_request(seqid_url, ACCESS_TOKEN)
    files_data_list = []
    if 'organisms' in files_data.keys():
        for org in files_data['organisms']:
            files_data_list.append({'files': org['files'], 'agg_id': org['agg_id']})
    return files_data_list


def create_all_files_list(sample_files_list, biosample_id, seq_id, all_files_list) -> None:
    for sample in sample_files_list:
        for files_dict in sample['files']:
            seq_unit_name = None if 'seq_unit_name' not in files_dict['metadata'].keys() else files_dict['metadata'][
                'seq_unit_name']
            seq_unit_name = [seq_unit_name] if type(seq_unit_name) is str else seq_unit_name
            file_format = None if 'file_format' not in files_dict[
                'metadata'].keys() else files_dict['metadata']['file_format']
            md5sum = files_dict['md5sum'] if 'md5sum' in files_dict.keys() else None
            all_files_list.append({'biosample_id': biosample_id, 'seq_id': seq_id, 'file_name': files_dict['file_name'],
                                   'file_status': files_dict['file_status'], 'file_type': files_dict['file_type'],
                                   'file_size': files_dict['file_size'],
                                   'jdp_file_id': files_dict['_id'], 'md5sum': md5sum,
                                   'file_format': file_format,
                                   'analysis_project_id': sample['agg_id'], 'seq_unit_name': seq_unit_name})
            if 'metadata' not in files_dict.keys():
                print(f"biosample_id {biosample_id}, seq_id{seq_id}")


def remove_unneeded_files(seq_files_df: pd.DataFrame, remove_files_list: list) -> pd.DataFrame:
    """
    Remove files that are not needed
    large files (*.domtblout and *.img_nr.last.blasttab)
    fastq and filtered fastq files from duplicate analyses
    :param seq_files_df:
    :param remove_files_list
    :return: DataFrame
    """
    seq_files_df = remove_large_files(seq_files_df, remove_files_list)
    seq_files_df = remove_duplicate_analysis_files(seq_files_df)
    return seq_files_df


def remove_large_files(seq_files_df: pd.DataFrame, remove_files_list: list) -> pd.DataFrame:
    pattern = '|'.join(remove_files_list)
    return seq_files_df[~(seq_files_df.file_name.str.contains(pattern))]


def remove_duplicate_analysis_files(seq_files_df: pd.DataFrame) -> pd.DataFrame:
    """
    remove fastq and filtered fastq files from duplicate analyses
    :param seq_files_df:
    :return: DataFrame
    """
    ap_gold_ids = list(seq_files_df.apGoldId.unique())

    drop_idx = []
    for gold_id in ap_gold_ids:
        print(gold_id)
        seq_unit_names_list = get_seq_unit_names(seq_files_df, gold_id)
        for idx, row in seq_files_df.loc[(seq_files_df.apGoldId == gold_id) &
                                         (seq_files_df.file_name.str.contains('fastq')) &
                                         (seq_files_df.file_name != 'input.corr.fastq.gz'), :].iterrows():
            # find rows with fastq files to remove (fastq file name is not in list of seq_unit_names and is not
            # input.corr.fastq.gz)
            if not any([seq in row.file_name for seq in seq_unit_names_list]):
                drop_idx.append(idx)
    seq_files_df.drop(drop_idx, inplace=True)
    return seq_files_df


def get_seq_unit_names(analysis_files_df, gold_id):
    seq_unit_names = []
    for idx, row in analysis_files_df.loc[pd.notna(analysis_files_df.seq_unit_name)
                                          & (analysis_files_df.apGoldId == gold_id)
                                          & (analysis_files_df.file_type == "['contigs']")].iterrows():
        seq_unit_names.extend(row.seq_unit_name)

    seq_unit_names_list = list(set(seq_unit_names))
    seq_unit_names_list = [
        ".".join(filename.split(".")[:4]) for filename in seq_unit_names_list
    ]
    return seq_unit_names_list


def sample_records_to_sample_objects(sample_records: List[Dict[str, Any]]) -> List[Sample]:
    """
    Convert sample records to Sample objects
    :param sample_records: list of sample records
    :return: list of Sample objects
    """
    sample_objects = []
    for sample_record in sample_records:
        try:
            sample_object = Sample(**sample_record)
            sample_objects.append(sample_object.model_dump())
        except ValidationError as e:
            logging.exception(f"Validation error: {e}")
            continue
    return sample_objects




def get_nmdc_study_id(proposal_id: int, ACCESS_TOKEN: str, config: configparser.ConfigParser) -> str:
    """
    Get NMDC study from proposal id
    """
    if config['PROJECT']['nmdc_study_id']:
        return config['PROJECT']['nmdc_study_id']
    url = f'https://api.microbiomedata.org/nmdcschema/study_set?filter= \
    {{"jgi_portal_study_identifiers":"jgi.proposal:{proposal_id}"}}'

    response_json = get_request(url, ACCESS_TOKEN)
    return response_json['resources'][0]['id']


def insert_new_project_into_mongodb(config_file: str, mdb) -> None:
    """
    Create a new project in mongodb
    """
    config = configparser.ConfigParser()
    config.read(config_file)

    nmdc_study_id = get_nmdc_study_id(int(config['PROJECT']['proposal_id']), get_access_token(), config)

    insert_dict = {'proposal_id': config['PROJECT']['proposal_id'], 'project_name': config['PROJECT']['name'],
                   'nmdc_study_id': nmdc_study_id, 'analysis_projects_dir': config['PROJECT']['analysis_projects_dir']}
    insert_object = SequencingProject(**insert_dict)
    mdb.sequencing_projects.insert_one(insert_object.dict())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project_name')
    parser.add_argument('config_file')
    parser.add_argument('-i', '--insert_project', action='store_true',
                        help='insert new project into mongodb',
                        default=False)
    parser.add_argument('-f', '--file', help='csv file with files to stage')
    args = vars((parser.parse_args()))

    project_name = args['project_name']
    config_file = args['config_file']
    insert_project = args['insert_project']
    file = args['file']
    mdb = get_db()
    if insert_project:
        insert_new_project_into_mongodb(config_file, mdb)
    else:
        get_samples_data(project_name, config_file, mdb, file)
        print("Sample metadata inserted into mongodb")
