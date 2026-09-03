import click
import copy
import os.path
from unittest.mock import MagicMock, patch

import pytest

from nmdc_automation.import_automation.import_mapper import ImportMapper
from nmdc_automation.run_process import run_import


@pytest.fixture
def mock_runtime_api():
    api = MagicMock()
    api.minter = MagicMock(side_effect=lambda obj_type: f"mocked_id_for_{obj_type}")
    return api

@pytest.fixture
def import_mapper_instance(mock_runtime_api, base_test_dir, ):
    yaml_file = base_test_dir / "import_test.yaml"
    nucleotide_sequencing_id = "nmdc:omprc-11-importT"
    return ImportMapper(
        nucleotide_sequencing_id=nucleotide_sequencing_id, import_project_dir=base_test_dir / "import_project_dir",
        # 22 files in here
        import_yaml=yaml_file, runtime_api=mock_runtime_api
    )

@pytest.fixture
def mock_minted_ids():
    return {"data_object_ids": {"Metagenome Raw Reads": "existing_data_object_id"},
        "workflow_execution_ids": {"WorkflowA": "existing_workflow_id"}}


def test_update_do_mappings_from_import_files(import_mapper_instance):
    import_mapper_instance.update_do_mappings_from_import_files()
    assert len(import_mapper_instance.mappings) == 22
    for fm_all in import_mapper_instance.mappings:
        print("Import File:", fm_all.import_file)
        assert not fm_all.import_file.endswith(".md5"), f"Unexpected .md5 file found: {fm_all.import_file}"


def test_update_do_mapping_from_import_files_correct_protein_file_import(import_mapper_instance):
    import_mapper_instance.update_do_mappings_from_import_files()
    correct_protein_faa_files = [
        fm for fm in import_mapper_instance.mappings if fm.data_object_type == "Annotation Amino Acid FASTA"
    ]
    assert len(correct_protein_faa_files) == 1, "Only one '_proteins.faa' file should be imported."

def test_update_do_mapping_from_import_files_correct_binning_mapping(import_mapper_instance):
    import_mapper_instance.update_do_mappings_from_import_files()
    binning_files = [
        fm for fm in import_mapper_instance.mappings if fm.data_object_type == "Metagenome HQMQ Bins Compression File"
    ]
    assert len(binning_files) == 2, "Multiple files should be imported."


def test_import_projects_sets_hqmq_zip_file_size_bytes(
    import_mapper_instance, base_test_dir, monkeypatch, tmp_path
):
    runtime_api = import_mapper_instance.runtime_api

    def find_planned_processes(filters):
        if filters == {"id": "nmdc:omprc-11-importT"}:
            return [{"id": "nmdc:omprc-11-importT", "has_output": []}]
        return []

    runtime_api.find_planned_processes.side_effect = find_planned_processes
    minted_ids = {"count": 0}

    def mint_id(object_type):
        minted_ids["count"] += 1
        return f"nmdc:test-{minted_ids['count']}"

    runtime_api.minter.side_effect = mint_id
    runtime_api.validate_metadata.return_value = {"result": "All Okay!"}
    import_mapper_instance._import_files = [
        "Ga0597026_bins_1.tar.gz",
        "Ga0597026_bins_2.tar.gz",
    ]
    monkeypatch.setattr(import_mapper_instance, "add_do_mappings_from_data_generation", lambda: None)
    monkeypatch.setattr(import_mapper_instance, "add_do_mappings_from_workflow_executions", lambda: None)
    monkeypatch.chdir(tmp_path)
    import_yaml = tmp_path / "import_test.yaml"
    import_yaml.write_text(
        (base_test_dir / "import_test.yaml").read_text()
    )
    import_mapper_instance.import_yaml = str(import_yaml)
    monkeypatch.setattr(run_import, "NmdcRuntimeApi", lambda _: runtime_api)
    monkeypatch.setattr(run_import, "ImportMapper", lambda *args: import_mapper_instance)
    monkeypatch.setattr(
        run_import,
        "_parse_tsv",
        lambda _: [{
            "project_path": str(base_test_dir / "import_project_dir"),
            "nucleotide_sequencing_id": "nmdc:omprc-11-importT",
        }],
    )

    context = click.Context(run_import.cli, obj={"log_level": 20})
    with context:
        run_import.import_projects.callback(
            "ignored.tsv",
            str(base_test_dir / "import_test.yaml"),
            str(base_test_dir / "site_configuration_test.toml"),
            False,
        )

    records = runtime_api.validate_metadata.call_args.args[0]["data_object_set"]
    hqmq_records = [
        record for record in records
        if record["data_object_type"] == "Metagenome HQMQ Bins Compression File"
    ]
    assert len(hqmq_records) == 1
    assert hqmq_records[0]["file_size_bytes"] == 1201


def test_write_minted_id_file(import_mapper_instance, base_test_dir):
    import_project_dir = base_test_dir / "import_project_dir"
    nucleotide_sequencing_id = "nmdc:omprc-11-importT"
    id_file = os.path.join(import_project_dir, f"{nucleotide_sequencing_id}_minted_ids.json")
    if os.path.exists(id_file):
        os.remove(id_file)
    import_mapper_instance.write_minted_id_file()
    assert os.path.exists(id_file)


def test_get_or_create_minted_id_existing_data_object(import_mapper_instance, mock_minted_ids):
    import_mapper_instance.minted_ids = mock_minted_ids
    result = import_mapper_instance.get_or_create_minted_id(
        object_type=ImportMapper.NMDC_DATA_OBJECT, data_object_type=ImportMapper.METAGENOME_RAW_READS
    )
    assert result == "existing_data_object_id"


def test_get_or_create_minted_id_new_data_object(import_mapper_instance, mock_minted_ids, mock_runtime_api):
    import_mapper_instance.minted_ids = mock_minted_ids
    result = import_mapper_instance.get_or_create_minted_id(
        object_type=ImportMapper.NMDC_DATA_OBJECT, data_object_type="NewDataObject"
    )
    assert result == "mocked_id_for_nmdc:DataObject"
    assert import_mapper_instance.minted_ids["data_object_ids"]["NewDataObject"] == "mocked_id_for_nmdc:DataObject"


def test_get_or_create_minted_id_existing_workflow(import_mapper_instance, mock_minted_ids):
    import_mapper_instance.minted_ids = mock_minted_ids
    result = import_mapper_instance.get_or_create_minted_id(
        object_type="WorkflowA"
    )
    assert result == "existing_workflow_id"


def test_get_or_create_minted_id_new_workflow(import_mapper_instance, mock_minted_ids, mock_runtime_api):
    import_mapper_instance.minted_ids = mock_minted_ids
    result = import_mapper_instance.get_or_create_minted_id(
        object_type="NewWorkflow"
    )
    assert result == "mocked_id_for_NewWorkflow.1"
    assert import_mapper_instance.minted_ids["workflow_execution_ids"]["NewWorkflow"] == "mocked_id_for_NewWorkflow.1"


def test_get_or_create_minted_id_missing_data_object_type(import_mapper_instance):
    with pytest.raises(TypeError, match="Must specify data_object_type for a Data Object"):
        import_mapper_instance.get_or_create_minted_id(object_type=ImportMapper.NMDC_DATA_OBJECT)


def test_import_specifications_returns_dict(import_mapper_instance):
    import_specifications = import_mapper_instance.import_specifications
    assert isinstance(import_specifications, dict)


def test_import_specifications_loads_yaml_correctly(import_mapper_instance, tmp_path):
    yaml_content = """
    key1: value1
    key2: value2
    """
    yaml_file = tmp_path / "import_specifications.yaml"
    yaml_file.write_text(yaml_content)
    import_mapper_instance.import_yaml = str(yaml_file)
    import_specifications = import_mapper_instance.import_specifications
    assert import_specifications == {"key1": "value1", "key2": "value2"}


def test_import_specifications_with_invalid_yaml(import_mapper_instance, tmp_path):
    invalid_yaml_content = "invalid_yaml: [unmatched_bracket"
    yaml_file = tmp_path / "import_specifications.yaml"
    yaml_file.write_text(invalid_yaml_content)
    import_mapper_instance.import_yaml = str(yaml_file)
    with pytest.raises(Exception):
        _ = import_mapper_instance.import_specifications


def test_import_specs_by_workflow_type_returns_dict(import_mapper_instance):
    import_specs_by_workflow_type = import_mapper_instance.import_specs_by_workflow_type
    assert isinstance(import_specs_by_workflow_type, dict)


def test_file_mappings_by_data_object_type_returns_dict(import_mapper_instance):
    import_file_mappings_by_data_object_type = import_mapper_instance.mappings_by_data_object_type
    assert isinstance(import_file_mappings_by_data_object_type, dict)


def test_file_mappings_by_workflow_type_returns_dict(import_mapper_instance):
    import_file_mappings_by_workflow_type = import_mapper_instance.mappings_by_workflow_type
    assert isinstance(import_file_mappings_by_workflow_type, dict)


def test_workflow_execution_ids_returns_list(import_mapper_instance):
    import_workflow_execution_ids = import_mapper_instance.workflow_execution_ids
    assert isinstance(import_workflow_execution_ids, list)


def test_workflow_execution_types_returns_list(import_mapper_instance):
    import_workflow_execution_types = import_mapper_instance.workflow_execution_types
    assert isinstance(import_workflow_execution_types, list)


def test_update_file_mappings(import_mapper_instance):
    for fm in import_mapper_instance.mappings:
        assert fm.nmdc_process_id is None
        assert fm.data_object_id is None

    for fm in import_mapper_instance.mappings:
        import_mapper_instance.update_mappings(
            fm.data_object_type, data_object_id='nmdc:dobj', workflow_execution_id='nmdc:wf'
        )
    for fm in import_mapper_instance.mappings:
        assert fm.nmdc_process_id == 'nmdc:wf'
        assert fm.data_object_id == 'nmdc:dobj'


def test_get_nmdc_file_name(import_mapper_instance):
    # Prepare - assign workflow IDs to file mappings
    for fm in import_mapper_instance.mappings:
        import_mapper_instance.update_mappings(
            fm.data_object_type, data_object_id='nmdc:dobj', workflow_execution_id='nmdc:wf'
        )
    for fm in import_mapper_instance.mappings:
        nmdc_file_name = import_mapper_instance.get_nmdc_data_file_name(fm)
        assert "nmdc_wf" in nmdc_file_name


def test_get_has_input_has_output_for_workflow_type_returns_lists(import_mapper_instance):
    wfe_types = import_mapper_instance.workflow_execution_types
    for wfe_type in wfe_types:
        has_input, has_output = import_mapper_instance.get_has_input_has_output_for_workflow_type(wfe_type)
        assert isinstance(has_input, list)
        assert isinstance(has_output, list)


def test_root_directory(import_mapper_instance):
    root_dir = import_mapper_instance.root_directory
    assert root_dir == os.path.join("import_project_dir", "nmdc:omprc-11-importT")


def test_data_source_url(import_mapper_instance):
    data_source_url = import_mapper_instance.data_source_url
    assert data_source_url == "https://data.microbiomedata.org/data"


def test_file_mapping_equality(import_mapper_instance):
    for fm in import_mapper_instance.mappings:
        fm_copy = copy.deepcopy(fm)
        assert fm_copy == fm
