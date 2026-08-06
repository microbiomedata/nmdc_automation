#!/usr/bin/env python

import json
import os
from time import sleep as _sleep
from urllib.parse import urlencode
import requests
from pathlib import Path
from typing import Union, List
from nmdc_automation.config import SiteConfig
import logging
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
from requests.exceptions import HTTPError
from nmdc_client.minter import Minter
from nmdc_client.collection_search import CollectionSearch
from nmdc_client import DataObjectSearch
from nmdc_client.metadata import Metadata
from nmdc_client.auth import NMDCAuth

logging_level = os.getenv("NMDC_LOG_LEVEL", logging.INFO)
logging.basicConfig(
    level=logging_level, format="%(asctime)s %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

class NmdcRuntimeApi:
    _base_url = None
    client_id = None
    client_secret = None

    def __init__(self, site_configuration: Union[str, Path, SiteConfig]):
        if isinstance(site_configuration, str) or isinstance(site_configuration, Path):
            site_configuration = SiteConfig(site_configuration)
        self.config = site_configuration
        self._base_url = self.config.api_url
        self.client_id = self.config.client_id
        self.client_secret = self.config.client_secret

    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def minter(self, id_type):
        minter = Minter(api_base_url=self._base_url)
        try:
            new_id = minter.mint(
                nmdc_type=id_type,
                count=1,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
            return new_id
        except Exception as e:
            logging.error(f"Failed to mint ID using Minter: {e}")
            raise

    def mock_mint(self, id_type):  # pragma: no cover
        """
        Return a fixed pattern used for testing
        """
        mapping = {
            "nmdc:ReadQcAnalysisActivity": "mgrqc",
            "nmdc:MetagenomeAssembly": "mgasm",
            "nmdc:MetagenomeAnnotationActivity": "mgann",
            "nmdc:MAGsAnalysisActivity": "mgmag",
            "nmdc:ReadBasedTaxonomyAnalysisActivity": "mgrbt",
        }
        return f"nmdc:wf{mapping[id_type]}-11-xxxxxx"

    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def get_object(self, obj:str, decode=False):
        """
        Helper function to get object info
        """
        do_client = DataObjectSearch(api_base_url=self._base_url)
        try:
            data = do_client.get_record_by_attribute(
                attribute_name="id",
                attribute_value=obj,
                exact_match=True,
            )[0]
        except Exception as e:
            logging.error(f"Failed to get object info using DataObjectSearch: {e}")
            raise
        ## TODO: why does the below code exist? is it used somewhere?
        # its function adds metadata slot if description is a json (not a string)
        if decode and "description" in data:
            try:
                data["metadata"] = json.loads(data["description"])
            except Exception:
                data["metadata"] = None
        return data

    def list_from_collection(self, collection, filt=None, projection=None, max=100):
        collection_client = CollectionSearch(collection, api_base_url=self._base_url)
        max_attempts = 3 # Defining max_attempts to retrieve from collection in case of API instability
        attempt = 0
        filt_args = json.dumps(filt)

        while attempt < max_attempts:
            try:
                results = collection_client.get_record_by_filter(
                    filter=filt_args,
                    max_page_size=max,
                    all_pages=True,
                    fields=projection
                )
                break
            except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
                attempt += 1
                logging.warning(f"--- API Instability Detected (Attempt {attempt}/{max_attempts}) ---")
                logging.warning(f"Error: {type(e).__name__}")

                if attempt < max_attempts:
                    # backoff linearly: 10s, 20s with added 10s infrastructure buffer
                    wait_time = 10 + (10 * attempt)
                    logging.info(f"Restarting fetch in {wait_time}s to clear poisoned token...")
                    _sleep(wait_time)
                    
                else:
                    logging.error("Max retries reached. Terminating to prevent partial data processing.")
                    raise RuntimeError(f"Crawl failed after {max_attempts} full restarts.") from e

        return results
    

    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def post_workflow_executions(self, obj_data):
        obj_json = {}
        obj_json["workflow_execution_set"] = obj_data
        resp = self.submit_metadata(obj_json)
        if not resp.ok:
            resp.raise_for_status()
        return resp.json()

    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def create_job(self, job_obj):
        url = "%sjobs" % (self._base_url)
        resp = requests.post(url, headers=self.header, data=json.dumps(job_obj))
        if not resp.ok:
            resp.raise_for_status()
        return resp.json()

    # TODO test that this concatenates multi-page results
    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def list_jobs(self, filt=None, max=100) -> List[dict]:
        url = "%sjobs" % (self._base_url) 

        params = {
            "max_page_size": max
        }
        if filt:
            #url += "&filter=%s" % (json.dumps(filt))
            params["filter"] = json.dumps(filt)
        
        results = []
        while True:
            resp = requests.get(url, headers=self.header, params=params)
            if resp.status_code != 200:
                # todo make this exit with failure more cleanly -jlp 20251104
                resp.raise_for_status()
            try:
                response_json = resp.json()
            except Exception as e:
                logging.error(f"Failed to parse response: {resp.text}")
                raise e
            if "resources" not in response_json:
                logging.warning(str(response_json))
                break
            
            results.extend(response_json["resources"])
            
            # Handle pagination
            next_token = response_json.get("next_page_token")
            if not next_token:
                break
            
            params["page_token"] = next_token

        return results
    
    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def list_jobs(self, filt=None, max=100) -> List[dict]:
        jobs_client = CollectionSearch("jobs", api_base_url=self._base_url)
        filt_args = filt if isinstance(filt, str) else json.dumps(filt) if filt else ""
        return jobs_client.get_record_by_filter(
            filter=filt_args,
            max_page_size=max,
            all_pages=True,
        )

    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def release_job(self, job_id: str):
        """
        Release a job that was previously claimed.
        """
        url = "%sjobs/%s:release" % (self._base_url, job_id)
        resp = requests.post(url, headers=self.header)
        if resp.status_code == 404:
            logging.warning(f"Job {job_id} not found or already released.")
            return None
        return resp.json()

    # Optimized to not retry on 404 ("Not Found" errors), since retrying won't eventuall
    # retrieve the data. All other error codes will continue to trigger a 6-attempt exponential 
    # backoff to handle transient network or server-side issues.
    @retry(
        retry=retry_if_exception(
            lambda e: not (
                isinstance(e, HTTPError) and 
                getattr(e, "response", None) is not None and 
                e.response.status_code == 404
            )
        ),
        # for other error codes, retry
        wait=wait_exponential(multiplier=4, min=8, max=120),
        stop=stop_after_attempt(6),
        reraise=True
    )
    def get_op(self, opid):
        url = "%soperations/%s" % (self._base_url, opid)
        resp = requests.get(url, headers=self.header)
        if not resp.ok:
            resp.raise_for_status()
        return resp.json()

    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def update_op(self, opid, done=None, results=None, meta=None):
        """
        Update an operation with the given ID with the specified parameters.
        Returns the updated operation.
        """
        url = "%soperations/%s" % (self._base_url, opid)
        d = dict()
        if done is not None:
            d["done"] = done
        if results:
            d["result"] = results
        if meta:
            # Need to preserve the existing metadata
            cur = self.get_op(opid)
            if not cur.get("metadata"):
                # this means we messed up the record before.
                # This can't be fixed so just return
                return None
            d["metadata"] = cur["metadata"]
            d["metadata"]["extra"] = meta
        resp = requests.patch(url, headers=self.header, data=json.dumps(d))
        if not resp.ok:
            resp.raise_for_status()
        return resp.json()

    def _run_query_single(self, query):
        url = "%squeries:run" % self._base_url
        try:
            resp = requests.post(url, headers=self.header, data=json.dumps(query))
            if not resp.ok:
                resp.raise_for_status()
            return resp.json()
        
        except HTTPError as e:
            logger.error("HTTP Error occurred during query execution.")
            logger.error(f"Status Code: {e.response.status_code}")
            logger.error(f"Response Body: {e.response.text}")
        
            raise e
    
    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def run_query(self, query):
    # Executes the initial query and handles cursor-based pagination to retrieve ALL results.
    
        all_results = []
        cursor_id = None
        current_command = query
        
        while True:
            # Determine the command to send (initial query or getMore)
            if cursor_id is not None:
                # Subsequent call: Use the getMore command
                current_command = {
                    "getMore": cursor_id,
                    # Include collection name if required by API for getMore
                    #"collection": initial_query.get("aggregate")
                }
            
            # Execute the query 
            response_data = self._run_query_single(current_command) 

            cursor = response_data.get("cursor", {})
            batch = cursor.get("batch", [])
            all_results.extend(batch)
            
            new_cursor_id = cursor.get("id")
            
            if new_cursor_id:
                cursor_id = new_cursor_id
            else:
                break
                
        return all_results


    @retry(wait=wait_exponential(multiplier=4, min=8, max=120), stop=stop_after_attempt(6), reraise=True)
    def find_planned_processes(self, filter: dict):
        # construct filter params
        filter_parts = []
        for k, v in filter.items():
            filter_parts.append(f"{k}:{v}")
        filter_terms = ",".join(filter_parts)
        params = {
            "filter": filter_terms,
            "per_page": 100,
        }
        encoded_params = urlencode(params)
        url = f"{self._base_url}planned_processes?{encoded_params}"
        logger.info(url)
        resp = requests.get(url, headers=self.header)
        if not resp.ok:
            resp.raise_for_status()
        return resp.json()["results"]

    def validate_metadata(self, metadata):
        auth = NMDCAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            api_base_url=self._base_url,
        )
        metadata_client = Metadata(api_base_url=self._base_url, auth=auth)
        return metadata_client.validate_json(metadata)

    def submit_metadata(self, metadata):
        auth = NMDCAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            api_base_url=self._base_url,
        )
        metadata_client = Metadata(api_base_url=self._base_url, auth=auth)
        return metadata_client.submit_json(metadata)
