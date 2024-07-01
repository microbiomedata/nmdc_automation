import pytest
import pytest_mock

from nmdc_automation.workflow_automation.base import Workflow, Activity, DataObject


def test_workflow_initialization():
    workflow = Workflow(
        name="Test Workflow", type="Type A", enabled=True, git_repo="https://example.com/repo.git", version="1.0"
        )
    assert workflow.name == "Test Workflow"
    assert workflow.type == "Type A"
    assert workflow.enabled is True
    assert workflow.git_repo == "https://example.com/repo.git"
    assert workflow.version == "1.0"
    assert workflow.children == set()
    assert workflow.parents == set()
    assert workflow.do_types == []


def test_workflow_post_init():
    workflow = Workflow(inputs={"param1": "do:type1", "param2": "type2"})
    assert workflow.do_types == ["type1"]


def test_workflow_from_dict():
    wf_dict = {
        "name": "Test Workflow",
        "type": "nmdc:SomeType",
        "enabled": True,
        "git_repo": "https://example.com/repo.git",
        "version": "1.0",
        "inputs": {"param1": "do:type1", "param2": "type2"}
    }
    workflow = Workflow.from_dict(wf_dict)
    assert workflow.name == "Test Workflow"
    assert workflow.type == "nmdc:SomeType"
    assert workflow.enabled is True
    assert workflow.git_repo == "https://example.com/repo.git"
    assert workflow.version == "1.0"
    assert workflow.inputs == {"param1": "do:type1", "param2": "type2"}
    assert workflow.do_types == ["type1"]


def test_workflow_add_child():
    parent = Workflow(name="Parent Workflow")
    child = Workflow(name="Child Workflow")
    parent.add_child(child)
    assert child in parent.children


def test_workflow_add_parent():
    child = Workflow(name="Child Workflow")
    parent = Workflow(name="Parent Workflow")
    child.add_parent(parent)
    assert parent in child.parents


def test_activity_initialization():
    activity = Activity(id="123", name="Test Activity", git_url="https://example.com/repo.git", version="1.0")
    assert activity.id == "123"
    assert activity.name == "Test Activity"
    assert activity.git_url == "https://example.com/repo.git"
    assert activity.version == "1.0"
    assert activity.has_input == []
    assert activity.has_output == []
    assert activity.was_informed_by == []
    assert activity.type is None
    assert activity.parent is None
    assert activity.children == []
    assert activity.data_objects_by_type == {}
    assert activity.workflow is None


def test_activity_omics_processing_post_init():
    activity = Activity(
        id="123", name="Test Activity", git_url="https://example.com/repo.git", version="1.0",
        type="nmdc:OmicsProcessing"
        )
    assert activity.was_informed_by == ["123"]


def test_activity_post_init():
    activity = Activity(
        id="123", name="Test Activity", git_url="https://example.com/repo.git", version="1.0",
        type="nmdc:OtherType"
        )
    assert activity.was_informed_by == []

@pytest.fixture()
def activity_dict():
    return {
        "id": "123",
        "name": "Test Activity",
        "git_url": "https://example.com/repo.git",
        "version": "1.0",
        "has_input": ["do:type1"],
        "has_output": ["do:type2"],
        "was_informed_by": ["456"],
        "type": "nmdc:NotOmicsProcessing"
    }

def test_activity_from_dict(activity_dict):
    activity = Activity.from_dict(activity_dict)
    assert activity.id == "123"
    assert activity.name == "Test Activity"
    assert activity.git_url == "https://example.com/repo.git"
    assert activity.version == "1.0"
    assert activity.has_input == ["do:type1"]
    assert activity.has_output == ["do:type2"]
    assert activity.was_informed_by == ["456"]
    assert activity.type == "nmdc:NotOmicsProcessing"
    assert activity.workflow is None

def test_activity_from_dict_with_workflow(mocker, activity_dict):
    mock_wf = mocker.MagicMock(spec=Workflow)
    activity = Activity.from_dict(activity_dict, mock_wf)
    assert activity.workflow == mock_wf

