from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional


class Sample(BaseModel):
    projects: list[str]
    apGoldId: str
    apName: str
    studyId: str
    itsApId: int
    biosample_id: str
    seq_id: int
    file_name: str
    file_status: str
    file_size: float
    jdp_file_id: str
    md5sum: Optional[str]
    analysis_project_id: int
    modDate: date
