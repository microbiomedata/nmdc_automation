"""
Integration tests for the NMDC API. These tests require the NMDC API to be running on localhost
"""

from time import time

import pytest
import requests
from datetime import datetime, timedelta

from nmdc_automation.api.nmdcapi import NmdcRuntimeApi as nmdcapi


@pytest.mark.integration
def test_integration_environment():
    """
    Test that the integration environment is set up correctly:
    - Runtime API server is running on localhost port 8000
    - The site 'NERSC' exists in the sites endpoint

    If any of these conditions are not met, the test will fail, and the remaining integration
    tests will be skipped.
    """
    response = requests.get("http://localhost:8000")
    assert response.status_code == 200

    response = requests.get("http://localhost:8000/sites/NERSC")
    assert response.status_code == 200
    response_body = response.json()
    assert response_body["id"] == "NERSC"


@pytest.mark.integration
def test_nmdcapi_get_token(site_config_file):
    n = nmdcapi(site_config_file)

    assert n.header is None
    token = n.auth.get_token()
    assert token is not None
    header = n.refresh_auth_header()
    assert header["Authorization"] == f"Bearer {token}"
    assert n.header == header


@pytest.mark.integration
def test_nmdcapi_list_jobs_refreshes_token(site_config_file):
    n = nmdcapi(site_config_file)
    assert n.header is None

    jobs = n.list_jobs()
    assert jobs is not None
    assert n.header is not None
    assert n.header["Authorization"].startswith("Bearer ")

    n.auth._token_expires_at = datetime.now() - timedelta(seconds=1)
    n.header = None
    jobs = n.list_jobs()
    assert jobs is not None
    assert n.header is not None
    assert n.header["Authorization"].startswith("Bearer ")
