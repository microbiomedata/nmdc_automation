""" Data classed for NMDC workflow automation. """
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from dateutil import parser

from nmdc_automation.models.nmdc import DataObject, workflow_process_factory


class WorkflowProcessNode(object):
    """
    Class to represent a workflow processing node. This is a node in a tree
    structure that represents the tree of data generation and
    workflow execution objects with their associated data objects.

    Workflow refers to a WorkflowConfig, defined in a workflow config file e.g. workflow.yaml
    Process refers to a PlannedProcess, either a DataGeneration or WorkflowExecution.
    """
    def __init__(self, record: Dict[str, Any], workflow: "WorkflowConfig") -> None:
        """
        Initialize a workflow processing node.
        """
        self.parent = None
        self.children = []
        self.data_objects_by_type = {}
        self.workflow = workflow
        process = workflow_process_factory(record)
        self.process = process

    def __hash__(self):
        return hash((self.id, self.type))

    def __eq__(self, other) -> bool:
        """
        Compare two workflow processing nodes by process id and type
        """
        return self.id == other.id and self.type == other.type

    def add_data_object(self, data_object) -> None:
        """
        Add a data object to this workflow processing node.
        """
        self.data_objects_by_type[data_object.data_object_type.code.text] = data_object

    @property
    def id(self):
        """
        Return the workflow processing node id based on its process id.
        """
        return self.process.id

    @property
    def type(self):
        """
        Return the workflow processing node type based on its process type.
        """
        return self.process.type

    @property
    def name(self):
        """
        Return the workflow processing node name based on its process name.
        """
        return self.process.name

    @property
    def has_input(self) -> list[str]:
        """
        Return the list of DataObject (or Biosample for DataGeneration) IDs that are input for this workflow processing node.
        """
        return self.process.has_input

    @property
    def has_output(self) -> list[str]:
        """
        Return the list of DataObject IDs that are output for this workflow processing node.
        """
        return self.process.has_output

    @property
    def git_url(self):
        """ workflow executions have a git_url field, data generations do not"""
        return getattr(self.process, "git_url", None)

    @property
    def version(self):
        """ workflow executions have a version field, data generations do not"""
        return getattr(self.process, "version", None)

    @property
    def analyte_category(self):
        """ data generations have an analyte_category field, workflow executions do not"""
        return getattr(self.process, "analyte_category", None)

    @property
    def was_informed_by(self):
        """ workflow executions have a was_informed_by field, data generations get set to their own id"""
        return getattr(self.process, "was_informed_by", self.id)


@dataclass
class WorkflowConfig:
    """ Configuration for a workflow execution. Defined by .yaml files in nmdc_automation/config/workflows """
    # Sequencing workflows only have these fields
    name: str
    collection: str
    enabled: bool
    analyte_category: str
    filter_output_objects: List[str]
    # TODO should type be optional?
    type: Optional[str] = None

    # workflow repository information
    git_repo: Optional[str] = None
    version: Optional[str] = None
    wdl: Optional[str] = None
    # workflow execution and input / output information
    filter_output_objects: List[str] = field(default_factory=list)
    predecessors: List[str] = field(default_factory=list)
    filter_input_objects: List[str] = field(default_factory=list)
    input_prefix: str = None
    inputs: Dict[str, str] = field(default_factory=dict)
    optional_inputs: List[str] = field(default_factory=list)
    workflow_execution: Dict[str, Any] = field(default_factory=dict)
    outputs: List[Dict[str, str]] = field(default_factory=list)

    # populated after initialization
    children: Set["WorkflowConfig"] = field(default_factory=set)
    parents: Set["WorkflowConfig"] = field(default_factory=set)
    input_data_object_types: List[str] = field(default_factory=list)

    def __post_init__(self):
        """ Parse input data object types from the inputs """
        for _, inp_param in self.inputs.items():
            # Some input params are boolean values, skip these
            if isinstance(inp_param, bool):
                continue
            if inp_param.startswith("do:"):
                self.input_data_object_types.append(inp_param[3:])
        if not self.type:
            # Infer the type from the name
            if self.collection == 'data_generation_set' and 'Sequencing' in self.name:
                self.type = 'nmdc:NucleotideSequencing'

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other) -> bool:
        """
        Compare two workflow configs by name.
        """
        return self.name == other.name


    def add_child(self, child: "WorkflowConfig") -> None:
        """ Add a child workflow config """
        self.children.add(child)

    def add_parent(self, parent: "WorkflowConfig") -> None:
        """ Add a parent workflow config"""
        self.parents.add(parent)
