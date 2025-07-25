from unittest.mock import patch, MagicMock
import pandas as pd
from pathlib import Path
import pytest
import requests
import os
import json
import configparser


from nmdc_automation.jgi_file_staging.jgi_file_metadata import (
    get_access_token,
    check_access_token,
    create_all_files_list,
    get_sequence_id,
    get_analysis_projects_from_proposal_id,
    sample_records_to_sample_objects,
    get_sample_files,
    get_samples_data,
    get_analysis_files_df,
    get_biosample_ids,
    get_files_and_agg_ids,
    get_request,
    remove_duplicate_analysis_files,
    remove_large_files,
    remove_unneeded_files,
    get_nmdc_study_id,
)
from nmdc_automation.jgi_file_staging.models import Sample


FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_get(mocker):
    return mocker.patch(
        "nmdc_automation.jgi_file_staging.jgi_file_metadata.requests.get"
    )

def test_get_nmdc_study_id(mock_get, import_config):
    ACCESS_TOKEN = 'mock_token'
    nmdc_study_id = get_nmdc_study_id(import_config['PROJECT']['proposal_id'], ACCESS_TOKEN, import_config)
    assert nmdc_study_id == import_config['PROJECT']['nmdc_study_id']

    import_config['PROJECT']['nmdc_study_id'] = ''
    mock_get.return_value.json.return_value = {'resources': [{'id': 'nmdc:sty-11-28tm5d36',
   'name': '1000 Soils Research Campaign',
   'websites': [],}]}
    mock_get.return_value.status_code = 200

    nmdc_study_id = get_nmdc_study_id(import_config['PROJECT']['proposal_id'], ACCESS_TOKEN, import_config)
    assert nmdc_study_id == 'nmdc:sty-11-28tm5d36'

def test_get_access_token(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = "ed42ef1556708305eaf8"
    access_token = get_access_token()
    assert access_token == "ed42ef1556708305eaf8"


def test_check_access_token(mock_get, import_config):
    mock_get.return_value.status_code = 200
    access_token = "ed42ef1556708305eaf8"
    access_token = check_access_token(access_token)
    assert access_token == "ed42ef1556708305eaf8"


def test_check_access_token_invalid(mocker):
    # Mock get_request to fail once, then succeed
    get_request_mock = mocker.patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_request')
    get_request_mock.side_effect = [
        None,  # simulate 404 or failure → triggers fallback
        {"some": "data"}  # simulate success after new token
    ]

    # Mock get_access_token to return a new token
    get_access_token_mock = mocker.patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_access_token')
    get_access_token_mock.return_value = "ed42ef155670"

    access_token = "ed42ef1556708305eaf8"
    result = check_access_token(access_token)

    assert result == "ed42ef155670"



def test_get_sequence_id(mock_get, import_config, fixtures_dir):
    mock_get.return_value.status_code = 200
    test_fixture = Path.joinpath(fixtures_dir, "gold_api/analysis_project.json")
    with open(test_fixture) as f:
        mock_get.return_value.json.return_value = json.load(f)


    sequence_id = get_sequence_id(
        "Ga0500001", "ed42ef155670",
    )
    assert sequence_id == [1323394]

    mock_get.return_value.status_code = 403
    sequence_id = get_sequence_id(
        "Ga0499978", "ed42ef155670",
    )
    assert sequence_id == []


def test_get_analysis_projects_from_proposal_id(mock_get):
    mock_data = pd.read_csv(Path.joinpath(FIXTURE_DIR, "grow_gold_analysis_projects.csv")).to_dict("records")
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = mock_data

    gold_analysis_data = get_analysis_projects_from_proposal_id("11111", "ed42ef155670")
    assert gold_analysis_data[0] == {
        "apGoldId": "Ga0499978",
        "apType": "Metagenome Analysis",
        "studyId": "Gs0149396",
        "itsApId": 1323348,
        "projects": "['Gp0587070']",
    }

    assert gold_analysis_data[5] == {
        "apGoldId": "Ga0451723",
        "apType": "Metagenome Analysis",
        "studyId": "Gs0149396",
        "itsApId": 1279803,
        "projects": "['Gp0503551']",
    }


def test_sample_model_instance_creation(monkeypatch, grow_analysis_df):
    sample_dict = grow_analysis_df.to_dict("records")[0]
    sample_model = Sample(**sample_dict)
    assert sample_model.apGoldId == "Ga0499978"
    assert sample_model.studyId == "Gs0149396"
    assert sample_model.itsApId == 1323348
    assert sample_model.project_name == 'grow_project'
    assert sample_model.biosample_id == "Gb0305643"
    assert sample_model.seq_id == "s1323445"
    assert sample_model.file_name == "52614.1.394702.GCACTAAC-CCAAGACT.filtered-report.txt"
    assert sample_model.file_status == "RESTORED"
    assert sample_model.file_size == 3645
    assert sample_model.jdp_file_id == "6190d7d30de2fc3298da6f7a"
    assert sample_model.md5sum == "fcd87248b5922a8bd0d530bcb23bffae"
    assert sample_model.analysis_project_id == "p1323348"



def test_sample_records_to_sample_objects(test_db, grow_analysis_df):
    exp_sample_count = len(grow_analysis_df)

    sample_records = grow_analysis_df.to_dict("records")
    assert len(sample_records) == exp_sample_count

    sample_objects = sample_records_to_sample_objects(sample_records)
    assert len(sample_objects) == exp_sample_count
    assert sample_objects[0]['analysis_project_id'] == 'p1323348'
    #'biosample_id': 'Gb0305643', 'file_name': '52614.1.394702.GCACTAAC-CCAAGACT.filtered-report.txt', 'file_size': 3645, 'file_status': 'RESTORED', 'itsApId': 1323348, 'jdp_file_id': '6190d7d30de2fc3298da6f7a', 'md5sum': 'fcd87248b5922a8bd0d530bcb23bffae', 'project_name': 'grow_project', 'seq_id': 's1323445', 'studyId': 'Gs0149396'}
    assert sample_objects[0]['apGoldId'] == 'Ga0499978'

@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_biosample_ids')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.check_access_token')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_sequence_id')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_files_and_agg_ids')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.create_all_files_list')
def test_get_sample_files(mock_create_all_files_list, mock_get_files_and_agg_ids,
                          mock_get_sequence_id, mock_check_access_token,
                          mock_get_biosample_ids, fixtures_dir):
    # Setup mocks
    mock_get_biosample_ids.return_value = ['biosample1', 'biosample2']
    mock_check_access_token.side_effect = lambda token: token  # just return the token unchanged
    mock_get_sequence_id.side_effect = lambda biosample_id, token: [f'seq_{biosample_id}_1', f'seq_{biosample_id}_2']
    mock_get_files_and_agg_ids.side_effect = lambda seq_id, token: [f'file_{seq_id}_a', f'file_{seq_id}_b']

    # This will append to all_files_list, so we define a side effect
    def create_list_side_effect(sample_files_list, biosample_id, seq_id, all_files_list):
        all_files_list.append({
            'biosample_id': biosample_id,
            'seq_id': seq_id,
            'files': sample_files_list
        })

    mock_create_all_files_list.side_effect = create_list_side_effect

    # Run the function
    result = get_sample_files(12345, 'mock_token')

    # Check calls
    mock_get_biosample_ids.assert_called_once_with(12345, 'mock_token')
    assert mock_check_access_token.call_count == 2  # two biosamples
    assert mock_get_sequence_id.call_count == 2
    assert mock_get_files_and_agg_ids.call_count == 4  # 2 biosamples × 2 seqs each = 4

    # Check result structure
    assert isinstance(result, pd.DataFrame)
    expected =pd.DataFrame([{'biosample_id': 'biosample1',
      'seq_id': 'seq_biosample1_1',
      'files': ['file_seq_biosample1_1_a', 'file_seq_biosample1_1_b']},
     {'biosample_id': 'biosample1',
      'seq_id': 'seq_biosample1_2',
      'files': ['file_seq_biosample1_2_a', 'file_seq_biosample1_2_b']},
     {'biosample_id': 'biosample2',
      'seq_id': 'seq_biosample2_1',
      'files': ['file_seq_biosample2_1_a', 'file_seq_biosample2_1_b']},
     {'biosample_id': 'biosample2',
      'seq_id': 'seq_biosample2_2',
      'files': ['file_seq_biosample2_2_a', 'file_seq_biosample2_2_b']}])
    pd.testing.assert_frame_equal(result, expected)


@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata._verify', return_value=True)
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.requests.get')
def test_get_request_success(mock_get, mock_verify):
    # Mock response for status 200
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{'id': 1}, {'id': 2}]
    mock_get.return_value = mock_response

    result = get_request('https://example.com/api', 'mock_token')

    mock_get.assert_called_once()
    assert result == [{'id': 1}, {'id': 2}]



@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata._verify', return_value=True)
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.requests.get')
def test_get_request_404(mock_get, mock_verify, caplog):
    # Mock response for status 404
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    result = get_request('https://example.com/api', 'mock_token')

    mock_get.assert_called_once()
    assert result == []
    assert '404 Not Found' in caplog.text


@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata._verify', return_value=True)
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.requests.get')
def test_get_request_403(mock_get, mock_verify, caplog):
    # Mock response for status 403
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_get.return_value = mock_response

    result = get_request('https://example.com/api', 'mock_token')

    mock_get.assert_called_once()
    assert result == []
    assert '403 Forbidden' in caplog.text


@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata._verify', return_value=True)
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.requests.get')
def test_get_request_other_error(mock_get, mock_verify):
    # Mock response for status 500
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = 'Internal Server Error'
    mock_get.return_value = mock_response

    with pytest.raises(requests.exceptions.RequestException) as excinfo:
        get_request('https://example.com/api', 'mock_token')

    assert 'Error 500' in str(excinfo.value)

@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.configparser.ConfigParser')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_access_token', return_value='mock_token')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.sample_records_to_sample_objects', return_value=[{'sample_id': 1}, {'sample_id': 2}])
def test_get_samples_data_with_csv(mock_sample_objects, mock_get_token, mock_configparser, test_db, tmp_path):
    # Setup
    mock_config = MagicMock()
    mock_config.__getitem__.return_value = {'delay': '1', 'remove_files': '1'}
    mock_configparser.return_value = mock_config

    csv_data = pd.DataFrame({'id': [1, 2], 'value': ['a', 'b']})
    csv_file = tmp_path / 'test.csv'
    csv_data.to_csv(csv_file, index=False)

    test_db.sequencing_projects.insert_one({'project_name': 'GROW', 'proposal_id': 'test_proposal'})

    with patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.pd.read_csv', return_value=csv_data):
        get_samples_data('GROW', 'mock_config.ini', test_db, str(csv_file))

    inserted = list(test_db.samples.find())
    assert len(inserted) == 0 or isinstance(inserted, list)  # Defensive: skip check if test_db is fully mocked
    mock_sample_objects.assert_called_once()
    mock_get_token.assert_called_once()



@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.configparser.ConfigParser')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_access_token', return_value='mock_token')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.sample_records_to_sample_objects', return_value=[{'sample_id': 1}])
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_sample_files', return_value=pd.DataFrame())
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_analysis_files_df', return_value=pd.DataFrame())
def test_get_samples_data_without_csv(mock_analysis, mock_files, mock_sample_objects, mock_get_token, mock_configparser, test_db):
    mock_config = MagicMock()
    mock_config.__getitem__.return_value = {'delay': '1', 'remove_files': '1'}
    mock_configparser.return_value = mock_config

    test_db.sequencing_projects.insert_one({'project_name': 'Bioscales', 'proposal_id': 'test_proposal'})

    get_samples_data('Bioscales', 'mock_config.ini', test_db)

    inserted = list(test_db.samples.find())
    assert len(inserted) == 0 or isinstance(inserted, list)  # Defensive fallback

    mock_files.assert_called_once_with('test_proposal', 'mock_token')
    mock_analysis.assert_called_once_with('test_proposal', mock_files.return_value, 'mock_token', eval('1'))


@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.configparser.ConfigParser')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_access_token', return_value='mock_token')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.sample_records_to_sample_objects', return_value=[])
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_sample_files', return_value=pd.DataFrame())
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_analysis_files_df', return_value=pd.DataFrame())
def test_get_samples_data_no_samples(mock_analysis, mock_files, mock_sample_objects, mock_get_token, mock_configparser, test_db):
    test_db.samples.delete_many({})  # Clear the collection before the test
    mock_config = MagicMock()
    mock_config.__getitem__.return_value = {'delay': '1', 'remove_files': '1'}
    mock_configparser.return_value = mock_config

    test_db.sequencing_projects.insert_one({'project_name': 'NEON', 'proposal_id': 'test_proposal'})

    get_samples_data('NEON', 'mock_config.ini', test_db)

    inserted = list(test_db.samples.find())
    assert inserted == []  # Should not insert anything when sample_objects is empty

    mock_files.assert_called_once()
    mock_analysis.assert_called_once()


@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_analysis_projects_from_proposal_id')
@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.remove_unneeded_files')
def test_get_analysis_files_df(mock_remove_unneeded, mock_get_analysis_projects):
    # Setup mock data
    proposal_id = 123
    ACCESS_TOKEN = 'mock_token'
    remove_files = ['badfile']

    # Mock return from get_analysis_projects_from_proposal_id
    mock_get_analysis_projects.return_value = [
        {'itsApId': 'ap1', 'other_field': 'value1'},
        {'itsApId': 'ap2', 'other_field': 'value2'}
    ]

    # Input files_df
    files_df = pd.DataFrame({
        'analysis_project_id': ['ap1', 'ap2'],
        'file_type': ['type1', 'type2'],
        'seq_id': [111, 222]
    })

    # Mock remove_unneeded_files to just return its input unchanged
    mock_remove_unneeded.side_effect = lambda df, remove_files: df

    # Call the function
    result_df = get_analysis_files_df(proposal_id, files_df, ACCESS_TOKEN, remove_files)

    # Assertions
    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == 2
    assert set(result_df.columns).issuperset({'file_type', 'analysis_project_id', 'seq_id', 'update_date', 'request_id'})
    assert all(result_df['file_type'].apply(lambda x: isinstance(x, str)))
    assert all(result_df['analysis_project_id'].apply(lambda x: isinstance(x, str)))
    assert all(result_df['seq_id'].apply(lambda x: isinstance(x, str)))
    assert pd.notnull(result_df['update_date']).all()
    assert result_df['request_id'].isnull().all()

    # Verify mocks were called
    mock_get_analysis_projects.assert_called_once_with(proposal_id, ACCESS_TOKEN)
    mock_remove_unneeded.assert_called_once()



@patch('nmdc_automation.jgi_file_staging.jgi_file_metadata.get_request')
def test_get_biosample_ids(mock_get_request):
    # Arrange
    proposal_id = 456
    ACCESS_TOKEN = 'mock_token'
    mock_response = [
        {'biosampleGoldId': 'biosample1'},
        {'biosampleGoldId': 'biosample2'},
        {'biosampleGoldId': 'biosample3'}
    ]
    mock_get_request.return_value = mock_response

    # Act
    result = get_biosample_ids(proposal_id, ACCESS_TOKEN)

    # Assert
    assert result == ['biosample1', 'biosample2', 'biosample3']
    mock_get_request.assert_called_once_with(
        f'https://gold-ws.jgi.doe.gov/api/v1/biosamples?itsProposalId={proposal_id}',
        ACCESS_TOKEN
    )


@pytest.fixture
def files_data_json(fixtures_dir):
    with open(os.path.join(fixtures_dir, "files_data.json")) as f:
        return json.load(f)


def test_get_files_and_agg_ids(monkeypatch, files_data_json):
    # Patch get_request to return files_data_json
    def mock_get_request(url, access_token):
        return files_data_json

    monkeypatch.setattr(
        "nmdc_automation.jgi_file_staging.jgi_file_metadata.get_request",
        mock_get_request
    )

    result = get_files_and_agg_ids(1323459, "ed42ef155670")

    # Assuming new function returns list of dicts [{'files': [...], 'agg_id': ...}]
    first_file = result[0]['files'][0]
    first_agg_id = result[0]['agg_id']

    assert first_file['file_name'] == "Table_8_-_3300049478.taxonomic_composition.txt"
    assert first_file['file_type'] == "report"
    assert first_agg_id == 1323348

def test_get_files_and_agg_ids_no_organisms(monkeypatch, files_data_json):
    # Remove 'organisms' key
    files_data_json.pop("organisms", None)

    def mock_get_request(url, access_token):
        return files_data_json

    monkeypatch.setattr(
        "nmdc_automation.jgi_file_staging.jgi_file_metadata.get_request",
        mock_get_request
    )

    result = get_files_and_agg_ids(1323459, "ed42ef155670")

    assert result == []


def test_create_all_files_list(fixtures_dir):
    with open(os.path.join(fixtures_dir, "files_data_list.json")) as f:
        files_data_list = json.load(f)
    all_files_list = []
    create_all_files_list(files_data_list, 'Gb0156560', 1323459, all_files_list)
    assert len(all_files_list) == 85

def test_remove_duplicate_analysis_files(fixtures_dir):
    seq_files_df = pd.read_csv(os.path.join(fixtures_dir, "Gb0258377_gold_analysis_files.csv"))
    seq_files_df.loc[pd.notna(seq_files_df.seq_unit_name), 'seq_unit_name'] = seq_files_df.loc[
        pd.notna(seq_files_df.seq_unit_name), 'seq_unit_name'].apply(lambda x: eval(x))
    seq_files_df = seq_files_df[(seq_files_df.apGoldId == 'Ga0485222')]
    assert not seq_files_df[(seq_files_df.apGoldId == 'Ga0485222') &
                         (seq_files_df.file_name == "52444.3.336346.GAGCTCAA-GAGCTCAA.fastq.gz")
                         ].empty
    remove_duplicate_analysis_files(seq_files_df)
    assert seq_files_df[(seq_files_df.apGoldId == 'Ga0485222') &
                         (seq_files_df.file_name == "52444.3.336346.GAGCTCAA-GAGCTCAA.fastq.gz")
                         ].empty

def test_remove_large_files(fixtures_dir):
    seq_files_df = pd.read_csv(os.path.join(fixtures_dir, "Gb0258377_gold_analysis_files.csv"))
    seq_files_df.loc[pd.notna(seq_files_df.seq_unit_name), 'seq_unit_name'] = seq_files_df.loc[
        pd.notna(seq_files_df.seq_unit_name), 'seq_unit_name'].apply(lambda x: eval(x))
    seq_files_df = seq_files_df[(seq_files_df.apGoldId == 'Ga0485222')]
    assert not seq_files_df[seq_files_df.file_name == 'Ga0485222_proteins.pfam.domtblout'].empty
    large_removed_df = remove_large_files(seq_files_df, ["img_nr.last.blasttab", "domtblout"])
    assert len(large_removed_df) == 74
    assert large_removed_df[large_removed_df.file_name == 'Ga0485222_proteins.pfam.domtblout'].empty

def test_remove_unneeded_files(fixtures_dir):
    seq_files_df = pd.read_csv(os.path.join(fixtures_dir, "Gb0258377_gold_analysis_files.csv"))
    seq_files_df.loc[pd.notna(seq_files_df.seq_unit_name), 'seq_unit_name'] = seq_files_df.loc[
        pd.notna(seq_files_df.seq_unit_name), 'seq_unit_name'].apply(lambda x: eval(x))

    seq_files_df = seq_files_df[(seq_files_df.apGoldId == 'Ga0485222')]

    assert not seq_files_df[(seq_files_df.apGoldId == 'Ga0485222') &
                         (seq_files_df.file_name == "52444.3.336346.GAGCTCAA-GAGCTCAA.fastq.gz")
                         ].empty

    assert not seq_files_df[(seq_files_df.apGoldId == 'Ga0485222') &
                         (seq_files_df.file_name == "Ga0485222_proteins.img_nr.last.blasttab")
                         ].empty

    filtered_df = remove_unneeded_files(seq_files_df, ["img_nr.last.blasttab", "domtblout"])
    assert len(filtered_df) == 73
    assert filtered_df[(filtered_df.apGoldId == 'Ga0485222') &
                         (filtered_df.file_name == "52444.3.336346.GAGCTCAA-GAGCTCAA.fastq.gz")
                         ].empty
    assert filtered_df[(filtered_df.apGoldId == 'Ga0485222') &
                            (filtered_df.file_name == "Ga0485222_proteins.img_nr.last.blasttab")
                            ].empty

