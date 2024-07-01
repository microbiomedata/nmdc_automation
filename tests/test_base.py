import pytest

from nmdc_automation.workflow_automation.base import Workflow

def test_initialization():
    workflow = Workflow(name="Test Workflow", type="Type A", enabled=True, git_repo="https://example.com/repo.git", version="1.0")
    assert workflow.name == "Test Workflow"
    assert workflow.type == "Type A"
    assert workflow.enabled is True
    assert workflow.git_repo == "https://example.com/repo.git"
    assert workflow.version == "1.0"
    assert workflow.children == set()
    assert workflow.parents == set()
    assert workflow.do_types == []

def test_post_init():
    workflow = Workflow(inputs={"param1": "do:type1", "param2": "type2"})
    assert workflow.do_types == ["type1"]

def test_from_dict():
    wf_dict = {
        "Name": "Test Workflow",
        "Type": "Type A",
        "Enabled": True,
        "Git repo": "https://example.com/repo.git",
        "Version": "1.0",
        "Inputs": {"param1": "do:type1", "param2": "type2"}
    }
    workflow = Workflow.from_dict(wf_dict)
    assert workflow.name == "Test Workflow"
    assert workflow.type == "Type A"
    assert workflow.enabled is True
    assert workflow.git_repo == "https://example.com/repo.git"
    assert workflow.version == "1.0"
    assert workflow.inputs == {"param1": "do:type1", "param2": "type2"}
    assert workflow.do_types == ["type1"]

def test_add_child():
    parent = Workflow(name="Parent Workflow")
    child = Workflow(name="Child Workflow")
    parent.add_child(child)
    assert child in parent.children

def test_add_parent():
    child = Workflow(name="Child Workflow")
    parent = Workflow(name="Parent Workflow")
    child.add_parent(parent)
    assert parent in child.parents
