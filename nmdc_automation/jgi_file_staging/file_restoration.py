import configparser

import pandas as pd
import requests
import os
import logging
from datetime import datetime
from mongo import get_mongo_db
from models import Sample
from pydantic import ValidationError
import argparse

logging.basicConfig(filename='file_staging.log',
                    format='%(asctime)s.%(msecs)03d %(levelname)s {%(module)s} [%(funcName)s] %(message)s',
                    datefmt='%Y-%m-%d,%H:%M:%S', level=logging.DEBUG)


def update_sample_in_mongodb(sample: dict, update_dict: dict) -> bool:
    mdb = get_mongo_db()
    update_dict.update({'update_date': datetime.now()})
    sample.update(update_dict)
    try:
        sample_update = Sample(**sample)
        sample_update_dict = sample_update.dict()
        mdb.samples.update_one({'jdp_file_id': sample_update_dict['jdp_file_id']}, {'$set': update_dict})
        return True
    except ValidationError as e:
        logging.debug(f'Update error: {e}')
        return False


def restore_files(project: str, config_file: str) -> str:
    """
    restore files from tape backup on JGI
    1) update file statuses
    2) for any files that are still PURGED, submit request to restore from tape
    There is a limit of 10TB/day for restore requests
    :param project: name of project (i.e. grow or bioscales)
    :param config_file: config file
    :return:
    """
    config = configparser.ConfigParser()
    config.read(config_file)
    update_file_statuses(project, config_file)
    mdb = get_mongo_db()
    restore_df = pd.DataFrame(
        [sample for sample in mdb.samples.find({'project': project,
                                                'file_status': {'$ne': ['in transit', 'transferred']}})])
    if restore_df.empty:
        return 'No samples'
    JDP_TOKEN = os.environ.get('JDP_TOKEN')
    headers = {'Authorization': JDP_TOKEN, "accept": "application/json"}
    url = 'https://files.jgi.doe.gov/download_files/'
    proxies = eval(config['JDP']['proxies'])
    begin_idx = restore_df.iloc[0, :].name
    # break requests up into batches because of the limit to the size of the request
    batch_size = 750
    count = 0
    # total size of files requested for restoration must be less than 10TB per day, set in config file
    sum_files = 0
    while begin_idx < len(restore_df):
        end_idx = begin_idx + batch_size
        sum_files += restore_df.loc[begin_idx:end_idx, 'file_size'].sum()
        if sum_files > float(config['JDP']['max_restore_request']):
            break
        request_ids = list(restore_df.loc[begin_idx:end_idx, 'jdp_file_id'].values)
        if request_ids:
            data = {'ids': request_ids, "restore_related_ap_data": 'false', "api_version": "2",
                    "globus_user_name": config['GLOBUS']['globus_user_name'],
                    "href": f"mailto: {config['GLOBUS']['mailto']}", "send_mail": "true"}

            r = requests.post(url, headers=headers, json=data, proxies=proxies)
            if r.status_code != 200:
                logging.debug(count)
                logging.debug(r.text)
                return r.text
            request_json = r.json()
            count += len(request_ids)
            restore_df.loc[begin_idx:end_idx, 'request_id'] = request_json['request_id']
            restore_df.loc[begin_idx:end_idx, 'file_status'] = 'pending'
            logging.debug(f"{begin_idx, end_idx, restore_df.loc[begin_idx:end_idx, 'file_size'].sum(), sum_files}")
        begin_idx = end_idx
    restore_df.apply(lambda x: update_sample_in_mongodb(x, {'request_id': x['request_id'],
                                                            'file_status': x['file_status']}), axis=1)

    return f"requested restoration of {count} files"


def get_file_statuses(samples_df, config):
    jdp_response_df = pd.DataFrame()
    for request_id in samples_df[pd.notna(samples_df.request_id)].request_id.unique():
        JDP_TOKEN = os.environ.get('JDP_TOKEN')
        headers = {'Authorization': JDP_TOKEN, "accept": "application/json"}
        url = f"https://files.jgi.doe.gov/request_archived_files/requests/{request_id}?api_version=1"
        r = requests.get(url, headers=headers, proxies=eval(config['JDP']['proxies']))
        response_json = r.json()
        file_status_list = [response_json['status'] for i in range(len(response_json['file_ids']))]
        jdp_response_df = pd.concat([jdp_response_df, pd.DataFrame({'jdp_file_id': response_json['file_ids'],
                                                                    'file_status': file_status_list})])
        logging.debug(jdp_response_df.jdp_file_id.unique())
        logging.debug(jdp_response_df[pd.isna(jdp_response_df['jdp_file_id'])])
    restore_response_df = pd.merge(samples_df, jdp_response_df, left_on='jdp_file_id', right_on='jdp_file_id')
    return restore_response_df


def update_file_statuses(project: str, config_file: str):
    config = configparser.ConfigParser()
    config.read(config_file)
    mdb = get_mongo_db()
    samples_df = pd.DataFrame([sample for sample in mdb.samples.find({'project': project})])
    samples_df = samples_df[pd.notna(samples_df.request_id)]
    if samples_df.empty:
        logging.debug(f"no samples to update for {project}")
        return
    samples_df['request_id'] = samples_df['request_id'].astype(int)
    restore_response_df = get_file_statuses(samples_df, config)
    for idx, row in restore_response_df.loc[
                    restore_response_df.file_status_x != restore_response_df.file_status_y, :].iterrows():
        sample = row[row.keys().drop(['file_status_x', 'file_status_y'])].to_dict()
        update_sample_in_mongodb(sample, {'jdp_file_id': row.jdp_file_id, 'file_status': row.file_status_y})


def check_restore_status(restore_request_id, config):
    """
    Status of a restore request made to the JGI Data Portal restore API
    :param restore_request_id: ID of request returned by restore_files
    :param JDP_TOKEN: Token from JDP website
    :return:
    """
    JDP_TOKEN = os.environ.get('JDP_TOKEN')
    headers = {'Authorization': JDP_TOKEN, "accept": "application/json"}

    url = f"https://files.jgi.doe.gov/request_archived_files/requests/{restore_request_id}?api_version=1"
    r = requests.get(url, headers=headers, proxies=eval(config['JDP']['proxies']))
    if r.status_code == 200:
        return r.json()
    else:
        logging.exception(r.text)
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project_name')
    parser.add_argument('config_file')
    parser.add_argument('-u', '--update_file_statuses', action='store_true', help='update status of file restorations',
                        default=False)
    args = vars((parser.parse_args()))
    if args['update_file_statuses']:
        update_file_statuses(args['project_name'], args['config_file'])
    else:
        restore_files(args['project_name'], args['config_file'])
