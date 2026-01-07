import configparser
import os
import pandas as pd
import argparse
import logging
from pathlib import Path

from WDL.Type import Boolean

from nmdc_api_utilities.data_staging import JGISampleSearchAPI
from nmdc_automation.config import SiteConfig, StagingConfig

logging.basicConfig(
    filename="file_staging.log",
    format="%(asctime)s.%(msecs)03d %(levelname)s {%(module)s} [%(funcName)s] %(message)s",
    datefmt="%Y-%m-%d,%H:%M:%S",
    level=logging.DEBUG, force=True
)


def get_list_staged_files(project: str, staged_data_dir: Path, save_file_list: Boolean = None) -> pd.DataFrame:
    """
    Get list of files that have been staged to filesystem
    :param project: name of the project
    :param config: configparser instance
    :param save_file_list: Save list of staged files
    """
    # project root based on current file location
    base_dir = Path(staged_data_dir/ project / f"analysis_files")


    proj_list = []
    for analysis_proj in os.listdir(base_dir):
        [
            proj_list.append({"analysis_project": analysis_proj, "file": f})
            for f in os.listdir(os.path.join(base_dir, analysis_proj))
        ]

    stage_df = pd.DataFrame(proj_list)
    stage_df.to_csv("staged_files.csv", index=False) if save_file_list else None

    return stage_df


def get_list_missing_staged_files(
    project_name:str, staging_configuration, site_configuration, save_file_list: Boolean=False
) -> list:
    """
    Get list of files on file system for a project and compare to list of files in database
    :param project_name: name of the project
    :param config: configparser instance
    :param mdb: MongoDB instance
    :param save_file_list: Save list of staged files
    """

    stage_df = get_list_staged_files(project_name, staging_configuration.staging_dir, save_file_list)
    stage_df["file_key"] = stage_df.apply(
        lambda x: f"{x.analysis_project}-{x.file}", axis=1
    )
    samples_df = pd.DataFrame(
        JGISampleSearchAPI(env=site_configuration.env, 
                           client_id=site_configuration.client_id, 
                           client_secret=site_configuration.client_secret
                           ).get_jgi_samples({'sequencing_project_name':project_name}))
    samples_df["file_key"] = samples_df.apply(
        lambda x: f"{x.ap_gold_id}-{x.file_name}", axis=1
    )
    db_samples_df = pd.merge(
        samples_df, stage_df, left_on="file_key", right_on="file_key", how="outer"
    )
    db_samples_df.loc[
        pd.isna(db_samples_df.analysis_project), ["ap_gold_id", "file_name"]
    ].to_csv("missing_staged.csv", index=False)
    return db_samples_df.loc[
        pd.isna(db_samples_df.analysis_project), ["ap_gold_id", "file_name"]
    ].to_dict("records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project_name")
    parser.add_argument('site_config_file')
    parser.add_argument('staging_config_file')
    parser.add_argument(
        "-s",
        "--save_file_list",
        action="store_true",
        help="save list of staged files to output file",
        default=False,
    )
    args = vars((parser.parse_args()))
    project_name = args["project_name"]
    staging_config_file = args["staging_config_file"]
    save_file_list = args["save_file_list"]
    

    # Get the list of missing staged files
    
    site_configuration = SiteConfig(args['site_config_file'])
    staging_configuration = StagingConfig(staging_config_file)
    missing_files = get_list_missing_staged_files(
        project_name, staging_configuration, site_configuration, save_file_list
    )
