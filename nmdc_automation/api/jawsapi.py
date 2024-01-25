#!/usr/bin/env python

import requests
import uuid
from nmdc_automation.config import Config


class JawsApi:
    
    def __init__(self, site_configuration):
        self.config = Config(site_configuration)
        self._base_url = self.config.jaws_api
        self.token = self.config.jaws_token
        if self._base_url[-1] != "/":
            self._base_url += "/"
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
    def get_jaws_status(self):
        resp = requests.post(f"{self._base_url}/run", headers=self.headers).json()
        
        if resp["nmdc-Site"] == "UP" and resp["perlmutter-Site"] == "UP":
            return True
        else:
            return False
        
        
    def submit_job(self, wdl_file, input_json):
        
        sub_id = str(uuid.uuid4())
        
        data = {
                "compute_site_id": "nmdc",
                "input_site_id": "nmdc",
                "team_id": "nmdc",
                "max_ram_gb": "500",
                "submission_id":sub_id,
                "manifest": "{}",
                "json_file": input_json,
                "wdl_file": wdl_file
                }
        
        resp = requests.post(f"{self._base_url}/run", headers=self.headers, data=data)
        
        return resp.json()
        
    def cancel_job_by_id(self, job_id):
        
        resp = requests.put(f"{self._base_url}/run/{job_id}/cancel", headers=self.headers)
        
        return resp.json()
    
    def get_job_info(self, job_id):
        
        resp = requests.get(f"{self._base_url}/run/{job_id}", headers=self.headers)
        
        return resp.json()
    
    def resubmit_job(self, job_id):
        
        resp = requests.put(f"{self._base_url}/run/{job_id}/resubmit", headers=self.headers)
        
        return resp.json()
        
    def get_run_logs(self, job_id):
        
        resp = requests.get(f"{self._base_url}/run/{job_id}/run_log", headers=self.headers)
        
        return resp.json()        
    
    def get_task_metadata(self, job_id):
        
        resp = requests.get(f"{self._base_url}/run/{job_id}/tasks", headers=self.headers)
        
        return resp.json() 

    def get_runtime_metrics(self, job_id):
        
        resp = requests.get(f"{self._base_url}/run_metrics/{job_id}", headers=self.headers)
        
        return resp.json()
        
    def cancel_all_jobs(self):
        
        resp = requests.get(f"{self._base_url}/run/cancel_all", headers=self.headers)
        
        return resp.json()
        