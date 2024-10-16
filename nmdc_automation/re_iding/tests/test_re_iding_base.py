# nmdc_automation/re_iding/tests/test_re_iding_base.py
from pathlib import Path
import pytest_mock

from nmdc_automation.api import NmdcRuntimeApi
from nmdc_schema.nmdc import Database as NmdcDatabase
from nmdc_schema.nmdc import DataObject as NmdcDataObject
from nmdc_schema.nmdc import (
    Biosample,
    MetabolomicsAnalysisActivity,
    NomAnalysisActivity,
    OmicsProcessing,
)
from nmdc_automation.re_iding.base import (
    ReIdTool,
    update_biosample,
    compare_models,
    get_new_nmdc_id,
    _update_metabolomics_analysis_activity,
    update_omics_output_data_object,
    update_omics_processing,
    update_metabolomics_or_nom_data_object,
)


TEST_DATAFILE_DIR = "./test_data/results"

def test_reidtool_update_omics_processing_has_output(db_record, mocker):
    """
    Test that we can get a new Database with updated omics processing has_output
    and re-IDed data objects.
    """
    exp_do_id = "nmdc:dobj-1234-abcd12345"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_do_id
    reid_tool = ReIdTool(mock_api, TEST_DATAFILE_DIR)
    new_db = NmdcDatabase()
    new_db = reid_tool.update_omics_processing_has_output(db_record, new_db)
    assert isinstance(new_db, NmdcDatabase)
    assert new_db.omics_processing_set

    assert new_db.omics_processing_set[0].has_output[0] == exp_do_id


def test_reidtool_make_new_data_object(data_object_record, mocker):
    """
    Test that we can make a new DataObject with a new ID and correct
    URL and Path attributes.
    """
    exp_do_id = "nmdc:dobj-1234-abcd12345"
    exp_url = 'https://data.microbiomedata.org/data/nmdc:omics_processing-1234-abcd12345/nmdc:activity-1234-abcd12345/nmdc_activity-1234-abcd12345_filtered.fastq.gz'
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_do_id
    reid_tool = ReIdTool(mock_api, TEST_DATAFILE_DIR)
    new_do = reid_tool.make_new_data_object(
        omics_processing_id="nmdc:omics_processing-1234-abcd12345",
        activity_type="nmdc:ReadQcAnalysisActivity",
        new_activity_id="nmdc:activity-1234-abcd12345",
        data_object_record=data_object_record,
        data_object_type="Filtered Sequencing Reads",
    )
    assert isinstance(new_do, NmdcDataObject)
    assert new_do.id == exp_do_id
    assert new_do.url == exp_url

def test_update_biosample_igsn_biosample_record_id_set_correctly_no_id_map(igsn_biosample_record, mocker):
    """
    Test that we can update a Biosample with an IGSN Biosample record with no identifiers_map provided.
    """
    exp_biosample_id = "nmdc:bsm-1234-abcd12345"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_biosample_id
    exp_study_id = "nmdc:sty-1234-abcd12345"

    orig_biosample_id = igsn_biosample_record["id"]

    biosample = Biosample(**igsn_biosample_record)
    updated_biosample = update_biosample(biosample, exp_study_id, mock_api)

    assert isinstance(updated_biosample, Biosample)
    assert updated_biosample.id == exp_biosample_id
    assert updated_biosample.part_of == [exp_study_id]
    assert updated_biosample.igsn_biosample_identifiers == [orig_biosample_id]

def test_compare_models_igsn_biosample_updates(igsn_biosample_record, mocker):
    """
    Test that we can compare a Biosample with an IGSN Biosample record and update it.
    """
    exp_biosample_id = "nmdc:bsm-1234-abcd12345"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_biosample_id
    exp_study_id = "nmdc:sty-1234-abcd12345"

    orig_biosample_id = igsn_biosample_record["id"]
    orig_study_id = igsn_biosample_record["part_of"][0]

    biosample = Biosample(**igsn_biosample_record)
    updated_biosample = update_biosample(biosample, exp_study_id, mock_api)

    changes = compare_models(biosample, updated_biosample)
    assert changes["id"] == exp_biosample_id
    assert changes["part_of"] == [exp_study_id]
    assert changes["igsn_biosample_identifiers"] == [orig_biosample_id]


def test_get_new_nmdc_id_biosample(mocker):
    """
    Test that we can get a new NMDC ID.
    """
    exp_id = "nmdc:1234-abcd12345"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_id

    nmdc_object = mocker.Mock(spec=Biosample)
    nmdc_object.type.return_value = "nmdc:Biosample"

    new_id = get_new_nmdc_id(nmdc_object, mock_api)
    assert new_id == exp_id

def test_get_new_id_data_object(mocker):
    """
    Test that we can get a new NMDC ID.
    """
    exp_id = "nmdc:1234-abcd12345"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_id

    nmdc_object = mocker.Mock(spec=NmdcDataObject)
    nmdc_object.type.return_value = "nmdc:DataObject"

    new_id = get_new_nmdc_id(nmdc_object, mock_api)
    assert new_id == exp_id

def test_get_new_id_metabolomics_analysis_activity(mocker):
    """
    Test that we can get a new NMDC ID with a .1 suffix.
    """
    exp_api_return = "nmdc:wfmb-1234-abcd12345"
    exp_id = "nmdc:wfmb-1234-abcd12345.1"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_api_return

    nmdc_object = mocker.Mock(spec=MetabolomicsAnalysisActivity)
    nmdc_object.type.return_value = "nmdc:MetabolomicsAnalysisActivity"

    new_id = get_new_nmdc_id(nmdc_object, mock_api)
    assert new_id == exp_id

def test_get_new_nmdc_id_biosample_with_identifiers_map(mocker):
    """
    Test that we can get a new NMDC ID with an identifiers_map.
    """
    exp_id = "nmdc:1234-abcd12345"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_id

    # Mock a simple object with type and id attributes
    nmdc_object = mocker.Mock()
    nmdc_object.type = "nmdc:Biosample"
    nmdc_object.id = "nmdc:old_id"

    identifiers_map = {
        ("biosample_set", "nmdc:old_id"): exp_id
    }

    new_id = get_new_nmdc_id(nmdc_object, mock_api, identifiers_map)
    assert new_id == exp_id

def test_get_new_nmdc_id_nom_activity_ndmc_typo_in_type(nom_activity_record_ndmc, mocker):
    """
    Test that we can get a new NMDC ID for a NOM Activity with a typo in the type.
    """
    exp_api_id = "nmdc:wfnom-1234-abcd12345"
    exp_id = "nmdc:wfnom-1234-abcd12345.1"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_api_id

    nmdc_object = NomAnalysisActivity(**nom_activity_record_ndmc)

    new_id = get_new_nmdc_id(nmdc_object, mock_api)
    assert new_id == exp_id

def test_get_new_nmdc_id_nom_activity_ndmc_typo_in_type_with_identifiers_map(nom_activity_record_ndmc, mocker):
    exp_id = "nmdc:1234-abcd12345"
    api_id = "should not see this"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = api_id

    nmdc_object = NomAnalysisActivity(**nom_activity_record_ndmc)
    old_id = nmdc_object.id
    identifiers_map = {
        ("nom_analysis_activity_set", old_id): exp_id
    }
    new_id = get_new_nmdc_id(nmdc_object, mock_api, identifiers_map)
    assert new_id == exp_id

def test_update_metabolomics_analysis_activity(metabolomics_analysis_activity_record):
    """
    Test that we can update a MetabolomicsAnalysisActivity.
    """
    exp_api_return = "nmdc:wfmb-1234-abcd12345"
    exp_activity_id = "nmdc:wfmb-1234-abcd12345"
    exp_omics_processing_id = "nmdc:omprc-1234-abcd12345"
    exp_data_object_id = "nmdc:dobj-1234-abcd12345"
    exp_output_data_object_ids = ["nmdc:dobj-1234-abcd12345"]
    exp_calibration_data_object_ids = "nmdc:dobj-calibration-1234-abcd12345"
    metabolomics = MetabolomicsAnalysisActivity(**metabolomics_analysis_activity_record)
    updated_metabolomics = _update_metabolomics_analysis_activity(
        exp_activity_id, metabolomics, exp_omics_processing_id, exp_data_object_id, exp_output_data_object_ids,
        exp_calibration_data_object_ids
        )
    assert isinstance(updated_metabolomics, MetabolomicsAnalysisActivity)
    assert updated_metabolomics.id == exp_activity_id

    assert updated_metabolomics.was_informed_by == exp_omics_processing_id
    assert updated_metabolomics.has_input == [exp_data_object_id]
    assert updated_metabolomics.has_output == exp_output_data_object_ids
    assert updated_metabolomics.has_calibration == exp_calibration_data_object_ids

def test_update_omics_output_data_object(data_object_record, mocker):
    """
    Test that we can update an OmicsOutputDataObject.
    """
    exp_id = "nmdc:1234-abcd12345"
    exp_study_id = "nmdc:sty-1234-abcd12345"
    mock_updated_omics_processing = mocker.Mock()
    mock_updated_omics_processing.omics_type.has_raw_value = "Metabolomics"

    exp_omics_processing_id = "nmdc:omprc-1234-abcd12345"
    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_id

    orig_id = data_object_record["id"]
    data_object = NmdcDataObject(**data_object_record)
    updated_data_object = update_omics_output_data_object(
        data_object, mock_updated_omics_processing, mock_api
    )
    assert isinstance(updated_data_object, NmdcDataObject)
    assert updated_data_object.id == exp_id
    assert updated_data_object.alternative_identifiers == [orig_id]

def test_update_omics_processing_has_input_is_nmdc_biosample_id(metagenome_omics_processing_record, mocker):
    """
    Test that we can update an OmicsProcessing with has_input.
    """
    exp_omics_id = "nmdc:omprc-1234-abcd12345"
    exp_biosample_id = "nmdc:bsm-1234-abcd12345"
    exp_study_id = "nmdc:sty-1234-abcd12345"
    orig_id = metagenome_omics_processing_record["id"]

    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_omics_id

    omics_processing = OmicsProcessing(**metagenome_omics_processing_record)

    updated_omics_processing = update_omics_processing(
        omics_processing, exp_study_id, exp_biosample_id, mock_api
    )
    assert isinstance(updated_omics_processing, OmicsProcessing)
    assert updated_omics_processing.id == exp_omics_id
    assert updated_omics_processing.part_of == [exp_study_id]
    assert updated_omics_processing.gold_sequencing_project_identifiers == [orig_id]

    assert updated_omics_processing.has_input == [exp_biosample_id]

def test_update_metabolomics_or_nom_data_object(metabolomics_output_data_object_record, mocker):
    """
    Test that we can update a Metabolomics or NOM DataObject with both a new ID and
    updated was_generated_by.
    """
    exp_do_id = "nmdc:dobj-1234-abcd12345"
    exp_was_generated_by = "nmdc:activity-1234-abcd12345"
    data_object = NmdcDataObject(**metabolomics_output_data_object_record)

    mock_api = mocker.Mock(spec=NmdcRuntimeApi)
    mock_api.minter.return_value = exp_do_id

    updated_data_object = update_metabolomics_or_nom_data_object(
        data_object, mock_api, identifiers_map=None, was_generated_by=exp_was_generated_by)
    assert isinstance(updated_data_object, NmdcDataObject)
    assert updated_data_object.id == exp_do_id
    assert updated_data_object.was_generated_by == exp_was_generated_by
