import logging
import pathlib
import sys

import pandas
import pandas as pd
from pathlib import Path
from argparse import ArgumentParser

from nmdc_automation.jgi_file_staging.jgi_file_metadata import get_access_token, get_request
from nmdc_api_utilities.auth import NMDCAuth
from nmdc_api_utilities.data_staging import JGISampleSearchAPI, JGISequencingProjectAPI
from nmdc_automation.config import SiteConfig, ProjectConfig, StagingConfig

logging.basicConfig(filename='mapping_tsv.log',
                    format='%(asctime)s.%(msecs)03d %(levelname)s {%(module)s} [%(funcName)s] %(message)s',
                    datefmt='%Y-%m-%d,%H:%M:%S', level=logging.DEBUG, force=True)
def create_mapping_tsv(project_name: str, site_configuration: SiteConfig, staging_configuration: StagingConfig, mapping_file_path: pathlib.Path=None) -> None:
    """
    Creates mapping tsv file(s) for a given project
    :param project_name: Name of the project
    :param mapping_file_path: path where to save the mapping tsv file (optional, default is staging_dir/project_name)
    :param site_configuration: SiteConfig object
    :param staging_configuration: StagingConfig object
    Not all studies have an associated proposal id
    1) get gold ids from the data_generation_set API
    2) for each gold id, get the gold analysis record
    """
    ACCESS_TOKEN = get_access_token()
    mapping_file_path = Path(staging_configuration.staging_dir, project_name) if not mapping_file_path else mapping_file_path
    seq_project = JGISequencingProjectAPI(env=site_configuration.env, 
                                          auth=NMDCAuth(client_id=site_configuration.client_id, 
                                                        client_secret=site_configuration.client_secret, 
                                                        env=site_configuration.env)
                                          ).get_jgi_sequencing_project_by_name(project_name)
    study_df = get_gold_ids(seq_project['nmdc_study_id'], ACCESS_TOKEN)
    study_df['gold_project'] = study_df.gold_sequencing_project_identifiers.apply(lambda x: x[0].split(':')[1])
    study_df = study_df.apply(
        lambda x: get_gold_analysis_project(x, ACCESS_TOKEN), axis=1)
    study_df = study_df.loc[pd.notna(study_df.gold_analysis_project), :]

    metag_study_df = study_df.loc[study_df.ap_type == 'Metagenome Analysis', ['id', 'gold_analysis_project']]
    create_tsv_file(metag_study_df, project_name, 'metag', mapping_file_path)
    metat_study_df = study_df.loc[study_df.ap_type == 'Metatranscriptome Analysis', ['id', 'gold_analysis_project']]
    if not metat_study_df.empty:
        new_row_list = []
        for idx, row in metat_study_df.iterrows():
            logging.debug(f'Processing row {row.id}, len={len(row.gold_analysis_project)}')
            new_row_list.append({'id': row.id, 'gold_analysis_project': row.gold_analysis_project[0]})
            try:
                new_row_list.append({'id': row.id, 'gold_analysis_project': row.gold_analysis_project[1]})
            except IndexError as e:
                logging.exception(f"Index Error: {e, study_df.loc[study_df.id==row.id, 'gold_project']}")
                new_row_list.append({'id': row.id, 'gold_analysis_project': None})
        metat_study_df = pd.DataFrame(new_row_list)
        create_tsv_file(metat_study_df, project_name, 'metat', mapping_file_path)


def create_tsv_file(study_df: pandas.DataFrame, project_name: str, ap_type: str,
                    mapping_file_path: pathlib.Path) -> None:
    """
    Create mapping tsv file for either metaG or metaT analysis projects
    :param study_df: pandas DataFrame containing gold analysis records
    :param project_name: Name of the project
    :param ap_type: type of analysis project
    :param mapping_file_path: path where to save the mapping tsv file
    """
    study_df['project_path'] = study_df.apply(lambda x: str(mapping_file_path / "analysis_files" / x['gold_analysis_project']) if x['gold_analysis_project'] else None, axis=1)
    study_df = study_df[['id', 'gold_analysis_project', 'project_path']]
    study_df.columns = ['nucleotide_sequencing_id', 'project_id', 'project_path']
    study_df.to_csv(Path(mapping_file_path, f'{project_name}.{ap_type}.map.tsv'), sep='\t', index=False)


def get_gold_ids(nmdc_study_id: str, ACCESS_TOKEN: str) -> pd.DataFrame:
    """
    Find the gold ids for a given NMDC study by querying the nmdc schema data_generation_set endpoint
    """
    url = (f'https://api.microbiomedata.org/nmdcschema/data_generation_set?filter='
           f'{{"associated_studies":"{nmdc_study_id}",'
           f'"gold_sequencing_project_identifiers":{{"$exists":true}}}}&max_page_size=1000')
    study_samples = get_request(url, ACCESS_TOKEN)
    study_df = pd.DataFrame(study_samples['resources'])
    return study_df.loc[pd.notna(study_df['gold_sequencing_project_identifiers']), :]


def get_gold_analysis_project(row: pd.Series, ACCESS_TOKEN: str) -> pd.Series:
    """
    get gold analysis project id for gold project id
    param: row: pandas Series containing gold analysis record
    """
    url = f"https://gold-ws.jgi.doe.gov/api/v1/analysis_projects?projectGoldId={row['gold_project']}"
    study_samples_json = get_request(url, ACCESS_TOKEN)
    if not study_samples_json:
        logging.debug(f"failed {row['gold_project']}")
        row['gold_analysis_project'] = None
        row['ap_type'] = None
    else:

        analysis_df = pd.DataFrame(study_samples_json)

        filter_values = analysis_df.loc[
            (analysis_df.apType == 'Metagenome Analysis') | (analysis_df.apType == 'Metatranscriptome Analysis'),
            ['apGoldId', 'apType']].sort_values('apGoldId', ascending=False).values[0]
        ap_gold_id = filter_values[0]
        ap_type = filter_values[1]
        if ap_type == 'Metatranscriptome Analysis':
            mapping_type = f"{ap_type.split(' ')[0]} mapping (self)"
            ap_gold_id = analysis_df.loc[(analysis_df.apGoldId == ap_gold_id) |
                                         ((analysis_df.apType == mapping_type) &
                                          (analysis_df.referenceApGoldId == ap_gold_id)), 'apGoldId'].values
        elif ap_type == 'Metagenome Analysis' and len(analysis_df[(analysis_df.apType == 'Metagenome Analysis')]) > 1:
            logging.debug(f"multiple metagenome analysis projects found for {row['gold_project']}, selecting none")
            ap_gold_id = None
        row['gold_analysis_project'] = ap_gold_id
        row['ap_type'] = ap_type
    return row


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('project_name', help='The project name from MongoDB')
    parser.add_argument('site_config_file', help='Site config parameters for runtime_api')
    parser.add_argument('staging_config_file', help='Config parameters for file staging')
    parser.add_argument('-f', '--file_path', default=None,
                        help='path where mapping tsv file is saved. default is <analysis_projects_dir>/<project_name>')
    args = vars((parser.parse_args()))

    site_configuration = SiteConfig(args['site_config_file'])
    staging_configuration = StagingConfig(args['staging_config_file'])
    # Create the mapping TSV file

    create_mapping_tsv(args['project_name'], site_configuration, staging_configuration,  args['file_path'])
