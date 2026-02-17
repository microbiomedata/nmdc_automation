import pytest

from nmdc_automation.config.siteconfig import SiteConfig, StagingConfig


def test_config(monkeypatch, test_data_dir, base_test_dir):
    monkeypatch.setenv("WF_CONFIG_FILE", str(test_data_dir / "wf_config"))
    conf = SiteConfig(base_test_dir / "site_configuration_test.toml")
    assert conf.cromwell_api
    assert conf.cromwell_url
    assert conf.stage_dir
    assert conf.template_dir
    assert conf.data_dir
    assert conf.raw_dir
    assert conf.resource
    assert conf.site
    assert conf.url_root
    assert conf.api_url
    assert conf.watch_state
    assert conf.agent_state is None # not in test config
    assert conf.activity_id_state
    assert conf.workflows_config
    assert conf.client_id
    assert conf.client_secret
    assert conf.allowed_workflows
    assert conf.env == "dev"

def test_staging_config(monkeypatch, test_data_dir, base_test_dir):
    monkeypatch.setenv("WF_CONFIG_FILE", str(test_data_dir / "wf_config"))
    conf = StagingConfig(base_test_dir / "staging_configuration_test.toml")
    assert conf.max_restore_request == 1e13
    assert "img_nr.last.blasttab" in conf.remove_files
    assert conf.globus_mailto == "test@example.com"
    assert conf.jgi_globus_id == "ae777bc6-e080-11ec-990f-3b4cfda38030"
    assert conf.globus_root_dir == '90125'


def test_config_missing(monkeypatch):
    monkeypatch.setenv("WF_CONFIG_FILE", "/bogus")
    with pytest.raises(OSError):
        SiteConfig("/tmp/foo")
