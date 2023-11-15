from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any

class InputDataObject(BaseModel):
    id: str
    name: str
    description: str
    url: str
    md5_checksum: str
    file_size_bytes: int
    data_object_type: str

class Output(BaseModel):
    output: str
    name: str
    suffix: str
    data_object_type: str
    description: str
    id: str

class Activity(BaseModel):
    name: str
    type: str
    # As the fields in activity are dynamic, use dict to adapt 
    additional_properties: Dict[str, str] = Field(alias="...")

    class Config:
        allow_population_by_field_name = True

class Conf(BaseModel):
    git_repo: str
    release: str
    wdl: str
    activity_id: str
    activity_set: str
    was_informed_by: str
    trigger_activity: str
    iteration: int
    input_prefix: str
    inputs: Dict[str, str]
    input_data_objects: List[InputDataObject]
    activity: Activity

class RecordBase(BaseModel):
    type: str
    cromwell_jobid: str
    nmdc_jobid: str
    conf: Conf
    activity_id: str
    last_status: str
    done: bool
    failed_count: int
    start: str
    end: Optional[str] = None
    opid: str
    outputs: List[Output]

class InputDataObjectUpdate(BaseModel):
    id: Optional[str]
    name: Optional[str]
    description: Optional[str]
    url: Optional[str]
    md5_checksum: Optional[str]
    file_size_bytes: Optional[int]
    data_object_type: Optional[str]

class OutputUpdate(BaseModel):
    output: Optional[str]
    name: Optional[str]
    suffix: Optional[str]
    data_object_type: Optional[str]
    description: Optional[str]
    id: Optional[str]

class ActivityUpdate(BaseModel):
    name: Optional[str]
    type: Optional[str]
    additional_properties: Optional[Dict[str, str]] = Field(alias="...")

    class Config:
        allow_population_by_field_name = True

class ConfUpdate(BaseModel):
    git_repo: Optional[str]
    release: Optional[str]
    wdl: Optional[str]
    activity_id: Optional[str]
    activity_set: Optional[str]
    was_informed_by: Optional[str]
    trigger_activity: Optional[str]
    iteration: Optional[int]
    input_prefix: Optional[str]
    inputs: Optional[Dict[str, str]]
    input_data_objects: Optional[List[InputDataObjectUpdate]]
    activity: Optional[ActivityUpdate]

class RecordUpdate(BaseModel):
    type: Optional[str]
    cromwell_jobid: Optional[str]
    nmdc_jobid: Optional[str]
    conf: Optional[ConfUpdate]
    activity_id: Optional[str]
    last_status: Optional[str]
    done: Optional[bool]
    failed_count: Optional[int]
    start: Optional[str]
    end: Optional[str]
    opid: Optional[str]
    outputs: Optional[List[OutputUpdate]]
