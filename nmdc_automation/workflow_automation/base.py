from dataclasses import dataclass, field, fields
from typing import List, Set, Dict, Any, Optional

"""
Base data classes for workflows, activities and data objects.
"""

@dataclass
class Workflow:
    """
    Workflow object class
    """
    name: str = None
    type: str = None
    enabled: bool = None
    git_repo: str = None
    version: str = None
    wdl: str = None
    collection: str = None
    predecessors: List[str] = field(default_factory=list)
    input_prefix: str = None
    inputs: Dict[str, str] = field(default_factory=dict)
    activity: str = None
    filter_input_objects: List[str] = field(default_factory=list)
    filter_output_objects: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    children: Set[Any] = field(default_factory=set, init=False)
    parents: Set[Any] = field(default_factory=set, init=False)
    do_types: List[str] = field(default_factory=list, init=False)

    def __post_init__(self):
        """
        Additional initialization steps after the dataclass __init__.
        """
        if self.inputs is None:
            self.inputs = {}

        self.do_types = [inp_param[3:] for inp_param in self.inputs.values() if inp_param.startswith("do:")]

    def __hash__(self):
        # Based name, type, git_repo, version
        return hash((self.name, self.type, self.git_repo, self.version))

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    @classmethod
    def from_dict(cls, wf: dict):
        """
        Class method to create a Workflow instance from a dictionary.
        """
        init_values = {}
        for field_ in fields(cls):
            if field_.init:  # Only include fields that are part of __init__
                attr_name = field_.name
                init_values[attr_name] = wf.get(attr_name)
        return cls(**init_values)

    def add_child(self, child: 'Workflow'):
        self.children.add(child)

    def add_parent(self, parent: 'Workflow'):
        self.parents.add(parent)

@dataclass
class Activity:
    id: Optional[str]
    name: Optional[str]
    git_url: Optional[str]
    version: Optional[str]
    has_input: Optional[List[str]] = field(default_factory=list)
    has_output: Optional[List[str]] = field(default_factory=list)
    was_informed_by: Optional[List[str]] = field(default_factory=list)
    type: Optional[str] = None
    parent: Optional['Activity'] = None
    children: List['Activity'] = field(default_factory=list)
    data_objects_by_type: Dict[str, 'DataObject'] = field(default_factory=dict)
    workflow: Optional['Workflow'] = None

    def __post_init__(self):
        if self.type == "nmdc:OmicsProcessing":
            self.was_informed_by = [self.id]

    def __hash__(self):
        return hash((self.id, self.name, self.type, self.version))

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    @classmethod
    def from_dict(cls, activity_rec: dict, wf: 'Workflow' = None) -> 'Activity':
        """
        Create an Activity object from a dictionary.
        """
        init_values = {}
        for field_ in fields(cls):
            if field_.init:
                attr_name = field_.name
                init_values[attr_name] = activity_rec.get(attr_name)
        if wf:
            init_values["workflow"] = wf
        return cls(**init_values)


    def add_data_object(self, do: 'DataObject'):
        self.data_objects_by_type[do.data_object_type] = do


@dataclass
class DataObject:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    md5_checksum: Optional[str] = None
    file_size_bytes: Optional[int] = None
    data_object_type: Optional[str] = None

    @classmethod
    def from_dict(cls, rec: dict) -> 'DataObject':
        init_values = {f.name: rec.get(f.name) for f in fields(cls)}
        return cls(**init_values)

    def __hash__(self):
        return hash((self.id, self.name, self.data_object_type, self.md5_checksum))

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()