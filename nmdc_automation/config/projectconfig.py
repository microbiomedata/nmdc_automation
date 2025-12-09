import tomli
from typing import Union
from pathlib import Path

class ProjectConfig:
    def __init__(self, path: Union[str, Path]):
        with open(path, "rb") as file:
            self.config_data = tomli.load(file)

    @property
    def nmdc_study_id(self):
        return self.config_data["project"]["nmdc_study_id"]
    
    @property
    def sequencing_project_name(self):
        return self.config_data["project"]["sequencing_project_name"]
    
    @property
    def jgi_proposal_id(self):
        return self.config_data["project"]["jgi_proposal_id"]
    
    @property
    def sequencing_project_description(self):
        return self.config_data["project"]["sequencing_project_description"]