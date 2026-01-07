"""Test the globus_file_transfer module."""
import ast
import os
from unittest.mock import patch, Mock, MagicMock
import pandas as pd
from pathlib import Path
from testfixtures import Replace, mock_datetime

from nmdc_automation.jgi_file_staging.globus_file_transfer import (
    get_globus_manifest,
    create_globus_batch_file,
    create_globus_dataframe,
    get_project_globus_manifests
)
from nmdc_automation.jgi_file_staging.jgi_file_metadata import sample_records_to_sample_objects
from nmdc_automation.config.siteconfig import StagingConfig, SiteConfig

def test_get_globus_manifests(monkeypatch, staging_config):
    mock_run = Mock()
    process_mocks = []
    side_effects = [
        {"stdout": "ERLowmetatpilot/\nGlobus_Download_201670_File_Manifest.csv\n", "returncode": 0},
        {"stdout": "", "returncode": 0},
        {"stdout": "NGESur0720SPAdes_8/\nRivsedcS19S_0091_2/\nGlobus_Download_201984_File_Manifest.csv", "returncode": 0},
        {"stdout": "", "returncode": 0},
        {"stdout": "ERLowmetatpilot/\nGlobus_Download_201670_File_Manifest.csv", "returncode": 0},
        {"stdout": "", "returncode": 0},
    ]
    for attrs in side_effects:
        p = Mock()
        p.configure_mock(**attrs)
        process_mocks.append(p)

    mock_run.side_effect = process_mocks
    monkeypatch.setattr("nmdc_automation.jgi_file_staging.globus_file_transfer.subprocess.run", mock_run)

    get_globus_manifest(201670, 'grow_project', staging_config)
    assert mock_run.call_count == 2
    expected_path = f"ae777bc6-e080-11ec-990f-3b4cfda38030:/{staging_config.globus_root_dir}/R201670"
    assert mock_run.mock_calls[0].args[0][2] == expected_path

@patch('nmdc_automation.jgi_file_staging.globus_file_transfer.JGISampleSearchAPI')
def test_get_project_globus_manifests(mock_sample_api, monkeypatch, grow_analysis_df, site_config, staging_config):
    mock_manifest = Mock(side_effect=[
        "Globus_Download_201545_File_Manifest.csv",
        "Globus_Download_201547_File_Manifest.csv",
        "Globus_Download_201572_File_Manifest.csv",
    ])
    monkeypatch.setattr("nmdc_automation.jgi_file_staging.globus_file_transfer.get_globus_manifest", mock_manifest)

    
    # grow_analysis_df['projects'] = grow_analysis_df['projects'].apply(ast.literal_eval)
    grow_analysis_df.loc[:5, 'jdp_file_status'] = 'in transit'
    grow_analysis_df.loc[:5, 'request_id'] = 201545
    grow_analysis_df.loc[5:8, 'request_id'] = 201547
    grow_analysis_df.loc[9, 'request_id'] = 201572

    sample_objects = sample_records_to_sample_objects(grow_analysis_df.to_dict("records"))
    
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    
    get_project_globus_manifests("grow_project", site_config, staging_config) 

    assert mock_manifest.call_count == 3
    assert mock_manifest.mock_calls[0].args[0] == 201545
    assert mock_manifest.mock_calls[1].args[0] == 201547

@patch('nmdc_automation.jgi_file_staging.globus_file_transfer.JGISampleSearchAPI')
def test_create_globus_df(mock_sample_api,  monkeypatch,grow_analysis_df, staging_config, site_config):
    class _StagingConfig(StagingConfig):
        staging_dir = Path(Path(__file__).parent / "fixtures").resolve()

    grow_analysis_df.loc[:5, 'file_status'] = 'in transit'
    grow_analysis_df.loc[:5, 'request_id'] = 201545
    grow_analysis_df.loc[5:8, 'request_id'] = 201547
    grow_analysis_df.loc[9, 'request_id'] = 201572

    sample_records = grow_analysis_df.to_dict("records")
    sample_objects = sample_records_to_sample_objects(grow_analysis_df.to_dict("records"))
    
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    assert len(sample_objects) == 10

    mock_manifest = Mock(side_effect=[
        "Globus_Download_201545_File_Manifest.csv",
        "Globus_Download_201547_File_Manifest.csv",
        "Globus_Download_201572_File_Manifest.csv",
    ])
    monkeypatch.setattr("nmdc_automation.jgi_file_staging.globus_file_transfer.get_globus_manifest", mock_manifest)
    staging_config.__class__ = _StagingConfig

    globus_df = create_globus_dataframe("grow_project", staging_config, site_config)

    assert len(globus_df) == 76
    assert globus_df.loc[0, "directory/path"] == "ERLowmetatpilot/IMG_Data"
    assert globus_df.loc[0, "filename"] == "Ga0502004_genes.fna"
    assert globus_df.loc[0, "file_id"] == "6141a2b4cc4ff44f36c8991a"
    assert globus_df.loc[0, "subdir"] == "R201545"
    assert globus_df.loc[1, "directory/path"] == "ERLowmetatpilot/Metagenome_Report_Tables"
    assert globus_df.loc[1, "md5 checksum"] == "d2b6bf768939813dca151f530e118c50"
    assert globus_df.loc[1, "filename"] == "Table_6_-_Ga0502004_sigs_annotation_parameters.txt"
    assert globus_df.loc[1, "subdir"] == "R201547"

@patch('nmdc_automation.jgi_file_staging.file_restoration.JGISampleSearchAPI')
@patch('nmdc_automation.jgi_file_staging.globus_file_transfer.JGISampleSearchAPI')
def test_create_globus_batch_file(mock_sample_api, mock_sample_restore, monkeypatch, grow_analysis_df, 
                                  tmp_path, staging_config, site_config):
    import os
    class _StagingConfig(StagingConfig):
        staging_dir = Path(Path(__file__).parent / "fixtures").resolve()
    staging_config.__class__ = _StagingConfig
    mock_manifest = Mock(return_value="Globus_Download_201572_File_Manifest.csv")
    monkeypatch.setattr("nmdc_automation.jgi_file_staging.globus_file_transfer.get_globus_manifest", mock_manifest)
    grow_analysis_df["jdp_file_status"] = "ready"
    grow_analysis_df["request_id"] = "201572"

    sample_records = grow_analysis_df.to_dict("records")
    sample_objects = sample_records_to_sample_objects(sample_records)
    assert len(sample_objects) == 10
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objects
    mock_sample_api.return_value = mock_sample_api_instance
    mock_sample_restore.return_value = mock_sample_api_instance

    # Patch where the file gets written to go into tmp_path
    monkeypatch.setattr("nmdc_automation.jgi_file_staging.globus_file_transfer.OUTPUT_DIR", tmp_path)

    with Replace(
        "nmdc_automation.jgi_file_staging.globus_file_transfer.datetime",
        mock_datetime(2022, 1, 1, 12, 22, 55, delta=0),
    ):
        globus_batch_filename, globus_analysis_df = create_globus_batch_file("grow_project", site_config, staging_config, tmp_path)

    assert globus_batch_filename.endswith(".txt")
    assert tmp_path in Path(globus_batch_filename).parents
    assert os.path.exists(globus_batch_filename)
