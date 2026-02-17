"""
Unit tests for the file restoration process in the JGI file staging system.
"""
import os
from unittest.mock import patch, MagicMock
import pytest
from tests.fixtures import db_utils
import pandas as pd
import logging

from nmdc_automation.jgi_file_staging.file_restoration import restore_files, update_file_statuses, send_restore_request
from nmdc_automation.jgi_file_staging.jgi_file_metadata import sample_records_to_sample_objects
from nmdc_automation.config.siteconfig import StagingConfig, SiteConfig

@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.requests.post')
def test_restore_files(mock_post, mock_sample_api, grow_analysis_df, monkeypatch, site_config, staging_config):
    
    # Set the JDP_TOKEN in environment
    monkeypatch.setenv('JDP_TOKEN', 'fake-token')

    # mock API call for file restore request
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        'updated_count': 0, 'restored_count': 4, 'request_id': '220699', 'request_status_url':
            'https://files.jgi.doe.gov/request_archived_files/requests/220699'}

    # insert samples into database
    grow_analysis_df.loc[grow_analysis_df['jdp_file_size'] > 30000, 'jdp_file_status'] = 'PURGED'
    grow_analysis_df['request_id'] = '220699'
    grow_analysis_df['sequencing_project_name'] = 'Gp0587070'
    sample_records = grow_analysis_df[grow_analysis_df['jdp_file_status'] == 'PURGED'].to_dict('records')
    sample_objects = sample_records_to_sample_objects(sample_records)
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    
    num_restore_samples = len(grow_analysis_df[grow_analysis_df['jdp_file_status'] == 'PURGED'])
    output = restore_files('Gp0587070', site_config, staging_config)
    assert output == f"requested restoration of {num_restore_samples} files"

@patch('nmdc_automation.jgi_file_staging.file_restoration.requests.post')
def test_send_restore_request(mock_post, grow_analysis_df, staging_config):
    """
    Test the send_restore_request function.
    """
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        'updated_count': 0, 'restored_count': 4, 'request_id': '220699', 'request_status_url':
            'https://files.jgi.doe.gov/request_archived_files/requests/220699'}

    sum_files, count = send_restore_request(0, 100,  grow_analysis_df, 'example.com', {'Authorization': 'fake-token', "accept": "application/json"}, staging_config, 0, 0)
    assert sum_files == 7967322253
    assert count == 10

@patch('nmdc_automation.jgi_file_staging.file_restoration.requests.post')
def test_send_restore_request_max_request(mock_post, grow_analysis_df, staging_config):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        'updated_count': 0, 'restored_count': 4, 'request_id': '220699', 'request_status_url':
            'https://files.jgi.doe.gov/request_archived_files/requests/220699'}
    grow_analysis_df.loc[:, 'jdp_file_size'] = 10**13  # set large file sizes to trigger max restore request
    _, count = send_restore_request(0, 100,  grow_analysis_df, 'example.com', {'Authorization': 'fake-token', "accept": "application/json"}, staging_config, 0, 0)
    assert count == 0

@patch('nmdc_automation.jgi_file_staging.file_restoration.requests.post')
def test_send_restore_request_api_failure(mock_post, grow_analysis_df, staging_config):
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = 'Internal Server Error'
    _, count = send_restore_request(0, 100,  grow_analysis_df, 'example.com', {'Authorization': 'fake-token', "accept": "application/json"}, staging_config, 0, 0)
    assert count == 0


@patch('nmdc_automation.jgi_file_staging.file_restoration.requests.post')
def test_send_restore_request_no_request_ids(mock_post, grow_analysis_df, staging_config):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        'updated_count': 0, 'restored_count': 4, 'request_id': '220699', 'request_status_url':
            'https://files.jgi.doe.gov/request_archived_files/requests/220699'}
    # Set empty request IDs
    grow_analysis_df.loc[:, 'jdp_file_id'] = ''
    _, count = send_restore_request(100, 200,  grow_analysis_df, 'example.com', {'Authorization': 'fake-token', "accept": "application/json"}, staging_config, 0, 0)
    assert count == 0


@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.requests.post')
def test_restore_files_no_samples(mock_post, mock_sample_api, monkeypatch, base_test_dir, staging_config, site_config):
    """
    Test the restore_files function when there are no samples to restore.
    """
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = {}
    mock_sample_api.return_value = mock_sample_api_instance
    monkeypatch.setenv('JDP_TOKEN', 'fake-token')

    output = restore_files('Gp0587070', site_config, staging_config)
    assert output == 'No samples to restore'
    mock_post.assert_not_called()


def test_restore_files_missing_token(import_config_file, monkeypatch, base_test_dir):
    """
    Test that the restore_files function raises a SystemExit when the JDP_TOKEN is not set.
    """
    site_configuration = SiteConfig(base_test_dir / "site_configuration_test.toml")
    staging_configuration = StagingConfig(base_test_dir / "site_configuration_test.toml")   
    monkeypatch.delenv('JDP_TOKEN', raising=False)

    with pytest.raises(SystemExit):
        restore_files('Gp0587070', site_configuration, staging_configuration)

@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.requests.post')
def test_restore_files_api_failure(mock_post, mock_sample_api, monkeypatch, grow_analysis_df, site_config, staging_config):
    monkeypatch.setenv('JDP_TOKEN', 'fake-token')

    mock_post.return_value.status_code = 500
    mock_post.return_value.text = 'Internal Server Error'
    sample_records = grow_analysis_df.to_dict('records')
    sample_objects = sample_records_to_sample_objects(sample_records)

    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    
    output = restore_files('Gp0587070', site_config, staging_config)
    assert output == 'requested restoration of 0 files'


@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.requests.post')
def test_restore_files_with_restore_csv(mock_post, tmp_path, monkeypatch, site_config, staging_config):
    """
    Test the restore_files function with a restore CSV file.
    """
    monkeypatch.setenv('JDP_TOKEN', 'fake-token')
    
    # Create restore CSV
    csv_file = tmp_path / 'restore.csv'
    df = pd.DataFrame([{
        'sequencing_project_name': 'Gp0587070',
        'jdp_file_status': 'PURGED',
        'jdp_file_size': 1,
        'jdp_file_id': 'id1'
    }])
    df.to_csv(csv_file, index=False)

    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {'request_id': '123'}

    output = restore_files('Gp0587070',  site_config, staging_config, restore_csv=str(csv_file))
    assert 'requested restoration of' in output

@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.get_file_statuses')
@patch('nmdc_automation.jgi_file_staging.file_restoration.update_sample_in_mongodb')
def test_update_file_statuses_no_samples(mock_update, mock_get, mock_sample_api, caplog, base_test_dir):
    caplog.set_level(logging.DEBUG)
    site_configuration = SiteConfig(base_test_dir / "site_configuration_test.toml")  
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = []
    mock_sample_api.return_value = mock_sample_api_instance
    update_file_statuses('Gp123', site_configuration)
    assert "no samples to update" in caplog.text
    mock_get.assert_not_called()
    mock_update.assert_not_called()


@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.get_file_statuses')
@patch('nmdc_automation.jgi_file_staging.file_restoration.update_sample_in_mongodb')
def test_update_file_statuses_no_request_id(mock_update, mock_get, mock_sample_api, caplog, base_test_dir, grow_analysis_df):
    caplog.set_level(logging.DEBUG)
    site_configuration = SiteConfig(base_test_dir / "site_configuration_test.toml")  
    mock_sample_api = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    update_file_statuses('Gp123', site_configuration)
    assert "no samples with request_id to update" in caplog.text
    mock_get.assert_not_called()
    mock_update.assert_not_called()

@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.get_file_statuses')
@patch('nmdc_automation.jgi_file_staging.file_restoration.update_sample_in_mongodb')
def test_update_file_statuses_no_file_status_columns(mock_update, mock_get, mock_sample_api, caplog, base_test_dir, grow_analysis_df):
    caplog.set_level(logging.DEBUG)
    df = pd.DataFrame([{'request_id': 1, 'jdp_file_id': 'id1'}])
    mock_get.return_value = df
    site_configuration = SiteConfig(base_test_dir / "site_configuration_test.toml")  
    sample_records = grow_analysis_df.to_dict('records')
    sample_objects = sample_records_to_sample_objects(sample_records)

    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    update_file_statuses('Gp123', site_configuration)
    assert "no samples with request_id to update for" in caplog.text
    mock_update.assert_not_called()


@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.get_file_statuses')
@patch('nmdc_automation.jgi_file_staging.file_restoration.update_sample_in_mongodb')
def test_update_file_statuses_no_changes(mock_update, mock_get, mock_sample_api, caplog, grow_analysis_df, base_test_dir):  
    caplog.set_level(logging.DEBUG)
    site_configuration = SiteConfig(base_test_dir / "site_configuration_test.toml")  
    sample_records = grow_analysis_df.to_dict('records')
    sample_objects = sample_records_to_sample_objects(sample_records)

    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    df = pd.DataFrame([{
        'request_id': 1,
        'jdp_file_id': 'id1',
        'file_status_x': 'RESTORED',
        'file_status_y': 'RESTORED'
    }])
    mock_get.return_value = df

    update_file_statuses('Gp123', site_configuration)
    assert "no file statuses changed" in caplog.text
    mock_update.assert_not_called()

@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.get_file_statuses')
@patch('nmdc_automation.jgi_file_staging.file_restoration.update_sample_in_mongodb')
def test_update_file_statuses_success(mock_update, mock_get, mock_sample_api, grow_analysis_df, test_db, caplog, base_test_dir):
    caplog.set_level(logging.DEBUG)
    test_db.samples.insert_one({'project_name': 'Gp123', 'file_status': 'RESTORED', 'request_id': 1, 'jdp_file_id': 'id1'})
    df = pd.DataFrame([{
        'request_id': 1,
        'jdp_file_id': 'id1',
        'file_status_x': 'RESTORED',
        'file_status_y': 'PURGED'
    }])
    mock_get.return_value = df
    site_configuration = SiteConfig(base_test_dir / "site_configuration_test.toml")  
    sample_records = grow_analysis_df.to_dict('records')
    sample_objects = sample_records_to_sample_objects(sample_records)

    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    update_file_statuses('Gp123', site_configuration)
    assert "updating 1 file statuses" in caplog.text
    mock_update.assert_called_once()

@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.file_restoration.get_file_statuses', side_effect=Exception("boom"))
@patch('nmdc_automation.jgi_file_staging.file_restoration.update_sample_in_mongodb')
def test_update_file_statuses_get_file_statuses_exception(mock_update, mock_get, mock_sample_api, grow_analysis_df, caplog, base_test_dir):
    site_configuration = SiteConfig(base_test_dir / "site_configuration_test.toml")  
    sample_records = grow_analysis_df.to_dict('records')
    sample_objects = sample_records_to_sample_objects(sample_records)
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    update_file_statuses('Gp123', site_configuration)
    assert "Error getting file statuses" in caplog.text
    mock_update.assert_not_called()