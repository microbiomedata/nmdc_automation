import pytest
import pandas as pd
from numpy.ma.core import equal
from pathlib import Path
from unittest.mock import patch, MagicMock

from nmdc_automation.jgi_file_staging.staged_files import get_list_missing_staged_files
from nmdc_automation.jgi_file_staging.jgi_file_metadata import sample_records_to_sample_objects
from nmdc_automation.config.siteconfig import SiteConfig, StagingConfig
 


@patch('nmdc_automation.jgi_file_staging.staged_files.JGISampleSearchAPI')
def test_get_list_missing_staged_files(mock_sample_api,
    monkeypatch, tmp_path, grow_analysis_df, staging_config, site_config, fixtures_dir
):

    
    # Patch DataFrame.to_csv to a no-op to prevent file writes
    monkeypatch.setattr(pd.DataFrame, "to_csv", lambda *args, **kwargs: None)

    project_name = "grow_project"

    # Setup fake directory structure under tmp_path
    # Patch config to point to tmp_path
    class _StagingConfig(StagingConfig):
        staging_dir = tmp_path
    staging_config.__class__ = _StagingConfig
    base_dir = tmp_path / project_name / "analysis_files"
    base_dir.mkdir(parents=True)

    # Prepare the test database
    sample_objs = sample_records_to_sample_objects(grow_analysis_df.to_dict("records"))
    mock_sample_api_instance = MagicMock(env='test', client_id='test_id', client_secret='test_secret')
    mock_sample_api_instance.get_jgi_samples.return_value = sample_objs
    mock_sample_api.return_value = mock_sample_api_instance
    # Add fake files
    for row in grow_analysis_df.loc[0:8, :].itertuples():
        analysis_proj_dir = base_dir / row.ap_gold_id
        analysis_proj_dir.mkdir() if not analysis_proj_dir.exists() else analysis_proj_dir
        (analysis_proj_dir / row.file_name).touch()
    # Run the function under test
    missing_files = get_list_missing_staged_files(project_name, staging_config, site_config)

    # Check type and basic properties
    assert isinstance(missing_files, list)
    assert len(missing_files) == 1

    # Optional: assert no CSV files were written
    assert not any(tmp_path.glob("*.csv"))
    # check that file is missing
    assert equal(missing_files[0], {'ap_gold_id': 'Ga0499978', 'file_name': 'rqc-stats.pdf'})
        