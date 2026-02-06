import sys
import pandas as pd
import requests
import os
import logging
from datetime import datetime
from pydantic import ValidationError
import argparse

from nmdc_automation.models.wfe_file_stages import JGISample
from nmdc_automation.config import SiteConfig, StagingConfig
from nmdc_api_utilities.data_staging import JGISampleSearchAPI
from nmdc_api_utilities.auth import NMDCAuth

logging.basicConfig(filename='file_restore.log',
                    format='%(asctime)s.%(msecs)03d %(levelname)s {%(module)s} [%(funcName)s] %(message)s',
                    datefmt='%Y-%m-%d,%H:%M:%S', level=logging.DEBUG, force=True)


def update_sample_in_mongodb(sample: dict, update_dict: dict, site_configuration: SiteConfig) -> bool:
    """
    Update a sample document in MongoDB with new values via the runtime API. 
    Validates the updated document against the JGISample model.
    :param sample: Original sample document as a dictionary.
    :param update_dict: Dictionary of fields to update with their new values.
    :param site_configuration: SiteConfig object with site configuration.
    :return: True if update is successful, False otherwise.
    """
    try:
        sample_update = JGISample(**sample)
        sample_update_dict = sample_update.model_dump()
        sample_update_dict.update({'update_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        sample_update_dict['create_date'] = sample_update_dict['create_date'].strftime('%Y-%m-%d %H:%M:%S')
        JGISampleSearchAPI(env=site_configuration.env, 
                           auth=NMDCAuth(client_id=site_configuration.client_id, 
                                         client_secret=site_configuration.client_secret, 
                                         env=site_configuration.env)
                           ).update_jgi_sample(sample_update_dict['jdp_file_id'], sample_update_dict)
        return True
    except ValidationError as e:
        logging.error(f'Validation error when updating Sample: {sample.get("jdp_file_id")} Error Details: {e}')
        return False


def restore_files(project: str, site_configuration: SiteConfig, 
                  staging_configuration: StagingConfig, restore_csv=None) -> str:
    """
    Restore files from tape backup at JGI.

    1. Update file statuses
    2. Submit restore requests for files that are not in transit, transferred, or restored
    Limitations: max restore request size is 10TB/day, and max number of files is 750

    :param project: Name of project (e.g., 'grow', 'bioscales').
    :param site_configuration: SiteConfig object with site configuration.
    :param restore_csv: Optional CSV file with files to restore.
    :return: Status message.
    """
    
    # Update statuses first
    update_file_statuses(project, site_configuration)
    JDP_TOKEN = os.environ.get('JDP_TOKEN')
    if not JDP_TOKEN:
        sys.exit('JDP_TOKEN environment variable not set')
    # Load restore DataFrame
    if restore_csv:
        restore_df = pd.read_csv(restore_csv)
    else:
        query = {"sequencing_project_name":project, "$or":[{"jdp_file_status": {"$ne":"pending"}},{"jdp_file_status":{"$ne":"RESTORED"}}]}
        samples = JGISampleSearchAPI(env= site_configuration.env,
                                     auth=NMDCAuth(client_id=site_configuration.client_id, 
                                                        client_secret=site_configuration.client_secret, 
                                                        env=site_configuration.env)
                                     ).list_jgi_samples(query, all_pages=True, max_page_size=100)
        if not samples:
            return 'No samples to restore'
        restore_df = pd.DataFrame(samples)

    
    
    headers = {'Authorization': JDP_TOKEN, "accept": "application/json"}
    url = 'https://files.jgi.doe.gov/download_files/'

    begin_idx = restore_df.iloc[0, :].name
    # break requests up into batches because of the limit to the size of the request
    batch_size = staging_configuration.restore_batch_size
    count = 0
    # total size of files requested for restoration must be less than 10TB per day, set in config file
    sum_files = 0
    while begin_idx < len(restore_df):
        end_idx = begin_idx + batch_size
        sum_files, count = send_restore_request(begin_idx, end_idx, restore_df, url, headers, staging_configuration, sum_files, count)
        begin_idx = end_idx

    restore_df['request_id'] = restore_df['request_id'].astype(int)
    restore_df['its_ap_id'] = restore_df['its_ap_id'].astype(str)
    restore_df['gold_seq_id'] = restore_df['gold_seq_id'].astype(str)
    restore_df['jgi_ap_id'] = restore_df['jgi_ap_id'].astype(str)
    restore_df.apply(lambda x: update_sample_in_mongodb(x, {'request_id': x['request_id'],
                                                            'jdp_file_status': x['jdp_file_status']}, site_configuration), axis=1)
    return f"requested restoration of {count} files"


def send_restore_request(begin_idx, end_idx, restore_df: pd.DataFrame, url: str, headers: dict, 
                         staging_configuration: StagingConfig, sum_files: int, count: int) -> tuple[int, int]:
    """
    Send a restore request to JGI Data Portal for a batch of files that is a slice of the restore_df DataFrame.
    :param begin_idx: Beginning index of batch
    :param end_idx: Ending index of batch
    :param restore_df: DataFrame with files to restore
    :param url: URL of JGI Data Portal restore API
    :param headers: Headers for JGI Data Portal restore API
    :param staging_configuration: StagingConfig object with staging configuration.
    :param sum_files: Current sum of file sizes requested for restoration
    :param count: Current count of files requested for restoration
    :return: Updated sum_files and count
    """
    sum_files += restore_df.loc[begin_idx:end_idx, 'jdp_file_size'].sum()
    if sum_files > float(staging_configuration.max_restore_request):
        logging.debug(f"Reached maximum restore size for the day: {sum_files} > {staging_configuration.max_restore_request}")
        return 0, 0
    request_ids = list(restore_df.loc[begin_idx:end_idx, 'jdp_file_id'].values)
    if not request_ids:
        logging.debug("No request IDs to process")
        return 0, 0
    else:
        data = {'ids': request_ids, "restore_related_ap_data": 'false', "api_version": "2",
                "globus_user_name": staging_configuration.globus_user_name,
                "href": f"mailto: {staging_configuration.globus_mailto}", "send_mail": "true"}

        r = requests.post(url, headers=headers, json=data)
        if r.status_code != 200:
            logging.debug(count)
            logging.error(f"Error submitting restore request: {r.status_code} {r.text}")
            return sum_files, count
        request_json = r.json()
        count += len(request_ids)
        restore_df.loc[begin_idx:end_idx, 'request_id'] = request_json['request_id']
        restore_df.loc[begin_idx:end_idx, 'jdp_file_status'] = 'pending'
        logging.debug(f"{begin_idx, end_idx, restore_df.loc[begin_idx:end_idx, 'jdp_file_size'].sum(), sum_files}")
        return sum_files, count


def get_file_statuses(samples_df: pd.DataFrame) -> pd.DataFrame:
    """
    Get file statuses from JGI Data Portal for files with a request_id
    :param samples_df: DataFrame with samples to check
    :param config: ConfigParser instance
    :return: DataFrame with file statuses

    """
    jdp_response_df = pd.DataFrame()
    for request_id in samples_df[pd.notna(samples_df.request_id)].request_id.unique():
        response_json = check_restore_status(request_id)
        file_status_list = [response_json['status'] for _ in response_json['file_ids']]
        jdp_response_df = pd.concat([jdp_response_df, pd.DataFrame({'jdp_file_id': response_json['file_ids'],
                                                                    'file_status': file_status_list})])
        logging.debug(jdp_response_df.jdp_file_id.unique())
        logging.debug(jdp_response_df[pd.isna(jdp_response_df['jdp_file_id'])])
    restore_response_df = pd.merge(samples_df, jdp_response_df, left_on='jdp_file_id', right_on='jdp_file_id')
    return restore_response_df


def update_file_statuses(project: str, site_configuration: SiteConfig):
    """
    Update file restoration status for sample files in a given project from JGI Data Portal
    :param project: Name of project (e.g., 'grow', 'bioscales').
    :param site_configuration: SiteConfig object with site configuration.
    :return: None"""
    

    # get all samples for sequencing project
    samples_list = JGISampleSearchAPI(env=site_configuration.env, 
                                      auth=NMDCAuth(client_id=site_configuration.client_id, 
                                                     client_secret=site_configuration.client_secret, 
                                                     env=site_configuration.env)
                                      ).list_jgi_samples({'sequencing_project_name': project})
    if not samples_list:
        logging.debug(f"no samples to update for {project}")
        return
    samples_df = pd.DataFrame(samples_list)

    if 'request_id' not in samples_df.columns:
        logging.debug(f"no samples with request_id to update for {project}")
        return

    # get file statuses from JGI Data Portal
    try:
        restore_response_df = get_file_statuses(samples_df)
    except Exception as e:
        logging.error(f"Error getting file statuses: {e}")
        return

    if 'file_status_x' not in restore_response_df.columns or 'file_status_y' not in restore_response_df.columns:
        logging.debug(f"no file statuses to update for {project}")
        return

    changed_rows = restore_response_df.loc[
        restore_response_df.file_status_x != restore_response_df.file_status_y, :]
    if changed_rows.empty:
        logging.debug(f"no file statuses changed for {project}")
        return
    logging.debug(f"updating {len(changed_rows)} file statuses for {project}")

    # update file statuses in MongoDB
    for idx, row in changed_rows.iterrows():
        sample = row[row.keys().drop(['file_status_x', 'file_status_y'])].to_dict()
        try:
            update_sample_in_mongodb(sample, {'jdp_file_id': row.jdp_file_id, 'file_status': row.file_status_y}, site_configuration)
        except Exception as e:
            logging.error(f"Error updating sample {sample['jdp_file_id']}: {e}")
            continue


def check_restore_status(restore_request_id: str) -> dict:
    """
    Status of a restore request made to the JGI Data Portal restore API
    :param restore_request_id: ID of request returned by restore_files
    :return:
    """
    JDP_TOKEN = os.environ.get('JDP_TOKEN')
    headers = {'Authorization': JDP_TOKEN, "accept": "application/json"}

    url = f"https://files.jgi.doe.gov/request_archived_files/requests/{restore_request_id}?api_version=1"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json()
    else:
        logging.exception(r.text)
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project_name')
    parser.add_argument('site_config_file')
    parser.add_argument('-u', '--update_file_statuses', action='store_true', help='update status of file restorations',
                        default=False)
    parser.add_argument('-r', '--restore_csv', default=None,  help='csv with files to restore')
    args = vars((parser.parse_args()))

    site_configuration = SiteConfig(args['site_config_file'])
    staging_configuration = StagingConfig(args['site_config_file'])

    if args['update_file_statuses']:
        update_file_statuses(args['project_name'], site_configuration)
    else:
        restore_files(args['project_name'], staging_configuration, site_configuration, args['restore_csv'])
