import os
import json
from pathlib import Path
from typing import Any, Callable
import mongomock
import pandas as pd
import pytest
import shutil
from unittest.mock import patch, MagicMock

from tests.fixtures import db_utils

from nmdc_automation.jgi_file_staging.mapping_tsv import (
    get_gold_ids,
    get_gold_analysis_project,
    create_mapping_tsv,
    create_tsv_file,
)
from nmdc_automation.models.wfe_file_stages import JGISequencingProject
from nmdc_automation.config.siteconfig import SiteConfig, StagingConfig


@pytest.fixture
def insert_sequencing_project(test_db: mongomock.Database):
    @mongomock.patch(servers=(('localhost', 27017),))
    def _insert():
        projects = [
            {'proposal_id': '507130', 'project_name': 'bioscales', 'nmdc_study_id': 'nmdc:sty-11-r2h77870',
             'analysis_projects_dir': 'nmdc_automation/jgi_file_staging/tests/fixtures/test_project'},
            {'proposal_id': '508306', 'project_name': '1000_soils', 'nmdc_study_id': 'nmdc:sty-11-28tm5d36',
             'analysis_projects_dir': '/global/cfs/cdirs/m3408/aim2/dev'},
        ]
        for p in projects:
            obj = JGISequencingProject(**p)
            test_db.sequencing_projects.insert_one(obj.dict())
        return test_db
    return _insert


@patch('nmdc_automation.jgi_file_staging.mapping_tsv.get_request')
@mongomock.patch(servers=(('localhost', 27017),))
def test_get_gold_ids(mock_get_request, fixtures_dir: Any):
    with open(fixtures_dir / 'data_generation_set_response.json', 'r', encoding='utf-8') as f:
        response = json.load(f)
    mock_get_request.return_value = response
    df = get_gold_ids('nmdc:sty-11-r2h77870', '')
    assert len(df) == 318


@patch('nmdc_automation.jgi_file_staging.mapping_tsv.get_request')
@mongomock.patch(servers=(('localhost', 27017),))
def test_get_gold_analysis_project(mock_get_request):
    mock_get_request.return_value = [{
        'apGoldId': 'Ga0268315',
        'apType': 'Metagenome Analysis',
        'projects': ['Gp0307487'],
    }]
    row = {'gold_project': 'Gp0307487'}
    result = get_gold_analysis_project(row, '')
    assert result == {'gold_analysis_project': 'Ga0268315', 'ap_type': 'Metagenome Analysis', 'gold_project': 'Gp0307487'}


@patch('nmdc_automation.jgi_file_staging.mapping_tsv.get_request')
@mongomock.patch(servers=(('localhost', 27017),))
def test_get_gold_analysis_project_multiple_metag(mock_get_request, fixtures_dir: Any):
    with open(fixtures_dir / 'analysis_proj_multi_metag_response.json', 'r', encoding='utf-8') as f:
        response = json.load(f)
    mock_get_request.return_value = response
    row = pd.Series({'gold_project': 'Gp0061139'})
    result = get_gold_analysis_project(row, '')
    expected = pd.Series({'gold_project': 'Gp0061139', 'gold_analysis_project': None,
                                                     'ap_type':'Metagenome Analysis'})
    pd.testing.assert_series_equal(result, expected)


@patch('nmdc_automation.jgi_file_staging.mapping_tsv.JGISequencingProjectAPI')
@patch('nmdc_automation.jgi_file_staging.mapping_tsv.get_request')
@patch('nmdc_automation.jgi_file_staging.mapping_tsv.get_access_token')
@mongomock.patch(servers=(('localhost', 27017),))
def test_create_mapping_tsv(mock_get_access_token, mock_get_request, mock_seq_project, fixtures_dir: Any, 
                            site_config: SiteConfig, staging_config: StagingConfig, metag_df, metag_tsv_df, metat_df, metat_tsv_df, staged_files_dir):
    class _StagingConfig(StagingConfig):
        staging_dir = Path(fixtures_dir / "staged_files")
    staging_config.__class__ = _StagingConfig
    mock_seq_project_api = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_seq_project_api.get_jgi_sequencing_project.return_value = {
        'sequencing_project_name': 'bioscales', 'jgi_proposal_id': 'test_proposal', 'nmdc_study_id':'abcd-11-de45se'}
    mock_seq_project.return_value = mock_seq_project_api
    mock_get_access_token.return_value = 'dummy_token'
    test_file = fixtures_dir / 'data_generation_set_response_mapping_tsv.json'
    # if not test_file.exists():
    #     pytest.skip(f"Fixture file not found: {test_file}")

    with open(test_file, 'r', encoding='utf-8') as f:
        data_response = json.load(f)

    mock_get_request.side_effect = [
        data_response,
        [{
            'apGoldId': 'Ga0268315',
            'apType': 'Metagenome Analysis',
        }],
        [{'apGoldId': 'Ga0222738', 'apType': 'Metatranscriptome Analysis'},
         {'apGoldId': 'Ga0224388','referenceApGoldId': 'Ga0222738','apType': 'Metatranscriptome mapping (self)'}]
    ]

    metag_file = fixtures_dir / 'staged_files' / 'bioscales' / 'bioscales.metag.map.tsv'
    metat_file = fixtures_dir / 'staged_files' / 'bioscales' / 'bioscales.metat.map.tsv'
    try:
        create_mapping_tsv('bioscales', site_config, staging_config)


        metag_tsv = pd.read_csv(metag_file, sep='\t')
        metat_tsv = pd.read_csv(metat_file, sep='\t')
        pd.testing.assert_series_equal(metag_tsv_df.loc[:, 'project_id'], metag_tsv.loc[:, 'project_id'])
        pd.testing.assert_series_equal(metag_tsv_df.loc[:, 'nucleotide_sequencing_id'], metag_tsv.loc[:, 'nucleotide_sequencing_id'])
        pd.testing.assert_series_equal(metat_tsv_df.loc[:, 'project_id'], metat_tsv.loc[:, 'project_id'])
        pd.testing.assert_series_equal(metat_tsv_df.loc[:, 'nucleotide_sequencing_id'], metat_tsv.loc[:, 'nucleotide_sequencing_id'])
        assert str(metat_tsv_df.loc[0, 'project_path']) == metat_tsv.loc[0, 'project_path']
        assert str(metat_tsv_df.loc[1, 'project_path']) == metat_tsv.loc[1, 'project_path']
    finally:
        metag_file.unlink() if metag_file.exists() else None
        metat_file.unlink() if metat_file.exists() else None
        shutil.rmtree(staged_files_dir.parent, ignore_errors=True)


def test_create_metag_tsv(fixtures_dir: str, metag_tsv_df, metag_df, staged_files_dir):
    """ test creation of metag and metat tsv files """
    #metag file
    
    metag_file = fixtures_dir / "staged_files" / 'bioscales' / 'bioscales.metag.map.tsv'
    mapping_file_path = fixtures_dir / "staged_files" / 'bioscales'
    try:
        create_tsv_file(metag_df, 'bioscales', 'metag', mapping_file_path)

        metag_tsv = pd.read_csv(metag_file, sep='\t')

        pd.testing.assert_series_equal(metag_tsv_df.loc[:, 'project_id'], metag_tsv.loc[:, 'project_id'])
        pd.testing.assert_series_equal(metag_tsv_df.loc[:, 'nucleotide_sequencing_id'], metag_tsv.loc[:, 'nucleotide_sequencing_id'])
        # pd.testing.assert_frame_equal(metag_tsv_df, metag_tsv)
    finally:
        metag_file.unlink() if metag_file.exists() else None
        shutil.rmtree(staged_files_dir.parent, ignore_errors=True)



def test_create_metat_tsv(fixtures_dir: str,  metat_tsv_df, metat_df, staged_files_dir):
    mapping_file_path = fixtures_dir / "staged_files" / 'bioscales'
    metat_file = fixtures_dir  / "staged_files" / 'bioscales' / 'bioscales.metat.map.tsv'
    try:
        create_tsv_file(metat_df, 'bioscales', 'metat', mapping_file_path)
        metat_tsv = pd.read_csv(metat_file, sep='\t')
        pd.testing.assert_series_equal(metat_tsv_df.loc[:, 'project_id'], metat_tsv.loc[:, 'project_id'])
        pd.testing.assert_series_equal(metat_tsv_df.loc[:, 'nucleotide_sequencing_id'], metat_tsv.loc[:, 'nucleotide_sequencing_id'])
        assert str(metat_tsv_df.loc[0, 'project_path']) == metat_tsv.loc[0, 'project_path']
        assert str(metat_tsv_df.loc[1, 'project_path']) == metat_tsv.loc[1, 'project_path']
    finally:
        metat_file.unlink() if metat_file.exists() else None
        shutil.rmtree(staged_files_dir.parent, ignore_errors=True)
    
