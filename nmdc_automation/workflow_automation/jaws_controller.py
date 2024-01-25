from nmdc_automation import JawsApi
import logging

class JawsController:
    
    def __init__(self, site_configuration_file):
        self.jaws_api = JawsApi(site_configuration_file)
        
    def submit_job(self, wdl_file, input_json):
        
        if not self.is_file_non_empty(wdl_file):
            raise ValueError(f"The WDL file '{wdl_file}' is empty.")

        if not self.is_file_non_empty(input_json):
            raise ValueError(f"The input JSON file '{input_json}' is empty.")
        
        logging.info("Submiting job to jaws")
        
        jaws_submission_response = self.jaws_api.submit_job(wdl_file, input_json)
        
        return jaws_submission_response["run_id"]
    
    def track_job_status(self, job_id):
        
        job_status_response = self.jaws_api.get_job_info(job_id)
        
        if job_status_response["result"] == "succeeded" and job_status_response["status"] == "done":
            logging.info(f"Job status succeeded for NMDC JAWs job {job_id}")
            return job_status_response["result"], job_status_response["output_dir"] + "/metadata.json"
        elif job_status_response["result"] == "failed":
            logging.info(f"Resubmitting job to NMDC JAWs for {job_id}")
            self.jaws_api.resubmit(job_id)
            return job_status_response["result"], f"resubmitted {job_id}"
        else:
            job_status_other = job_status_response["result"]
            logging.info(f"Job status for {job_id} is {job_status_other}")
            return job_status_other, None
        
    def check_jaws_status(self):
        if self.jaws_api.status():
            logging.info(f"JAWs status functional for NMDC-Site and Pelmutter")
            return "ok"
        else:
            logging.error(f"NMDC-Site and or Perlmutter site down, cancelling jobs")
            self.jaws_api.cancel_all_jobs()
            
     
    @staticmethod
    def is_file_non_empty(file_path):
        """Check if a file is not empty."""
        try:
            with open(file_path, 'r') as file:
                return file.read().strip() != ""
        except IOError as e:
            raise IOError(f"Error reading file '{file_path}': {e}")