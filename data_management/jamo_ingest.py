"""
NMDC Workflow Data Processing Script
Retrieves workflow execution data from NMDC API, processes it, and generates metadata files.
Handles workflow execution records and their associated data objects.
"""

import json
import yaml
import os
import sys
import requests
import click
import glob
import argparse
from typing import Dict, List, Optional
import logging
import traceback

_BASE_URL = "https://api.microbiomedata.org/"


# File Operations
def save_json(data: Dict, filename: str):
    """
    Save dictionary data to a JSON file with proper formatting.

    Args:
        data: Dictionary to be saved
        filename: Target JSON file path

    Raises:
        OSError: If directory creation or file writing fails
    """
    # Create directory path if it doesn't exist
    dirname = os.path.dirname(filename)
    if dirname:  # Only create directory if dirname is not empty
        os.makedirs(dirname, exist_ok=True)

    with open(filename, 'w+') as f:
        json.dump(data, f, indent=4)


def load_json(filename: str) -> Dict:
    """
    Load and parse a JSON file into a dictionary.

    Args:
        filename: Path to JSON file to load

    Returns:
        Dictionary containing parsed JSON data
    """
    with open(filename) as f:
        return json.load(f)


# API Query Functions
def query_collection(base_url: str, collection_name: str,
                     max_page_size: Optional[int] = None,
                     filter_param: Optional[str] = None,
                     paginate: bool = True) -> Dict:
    """
    Query the metadata from a specific collection with optional pagination support.

    Args:
        base_url: The base URL of the API
        collection_name: The name of the collection to query
        max_page_size: Maximum number of records to query per page
        filter_param: Optional MongoDB-style filter query string
        paginate: If True, automatically fetches all pages and combines results

    Returns:
        Dictionary containing the API response data. If paginate=True, returns
        combined results from all pages in the same format as a single page response.

    Raises:
        requests.RequestException: If the API request fails
    """
    url = f"{base_url}nmdcschema/{collection_name}"
    params = {}
    if max_page_size:
        params['max_page_size'] = max_page_size
    if filter_param:
        params['filter'] = filter_param

    if not paginate:
        # Single page request (original behavior)
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    # Paginated request - collect all pages
    all_resources = []
    page_token = None
    page_count = 0
    
    while True:
        current_params = params.copy()
        if page_token:
            current_params['page_token'] = page_token
            
        response = requests.get(url, params=current_params)
        response.raise_for_status()
        response_data = response.json()
        
        # Add resources from this page
        if "resources" in response_data:
            all_resources.extend(response_data["resources"])
            page_count += 1
            click.echo(f"Fetched page {page_count} with {len(response_data['resources'])} records")
        
        # Check if there are more pages
        if "next_page_token" not in response_data or not response_data["next_page_token"]:
            break
            
        page_token = response_data["next_page_token"]
    
    # Return the combined results in the same format as the original response
    if page_count > 1:
        click.echo(f"Pagination complete: {page_count} pages fetched, {len(all_resources)} total records")
    
    # Use the last response as the template and replace resources with combined results
    response_data["resources"] = all_resources
    return response_data


def get_data_object_set(base_api_url: str, max_page_size: int) -> Dict:
    """
    Retrieve data objects with URLs from the data_object_set collection.

    Creates a lookup dictionary mapping object ID to their full record data.
    Only includes records that have a URL field. Uses pagination to fetch all records.

    Args:
        base_api_url: Base API URL
        max_page_size: Maximum number of records to retrieve per page

    Returns:
        Dictionary mapping object IDs to their complete record data
    """
    collection_name = "data_object_set"
    filter_param = '{"url": {"$exists": true}}'  # Filter to retrieve only records with a URL
    collection_data = query_collection(base_api_url, collection_name, max_page_size, filter_param)

    kv_store = {}
    for item in collection_data.get("resources", []):
        item_id = item.get("id")
        if item_id:
            kv_store[item_id] = item
    return kv_store


def get_workflow_execution_set(base_api_url: str = _BASE_URL, max_page_size: int = 100000) -> Dict[str, List[str]]:
    """
    Query workflow execution records and organize them by workflow type.

    Queries the workflow_execution_set collection, validates each record against
    the data_object_set collection, and groups valid records by their workflow type.
    Results are saved to a JSON file.

    Args:
        base_api_url: Base URL for the API endpoint
        max_page_size: Maximum number of records to retrieve per query

    Returns:
        Dictionary where:
            - key (str): workflow_execution_id
            - value (List): [workflow_execution_type (str), list_of_records (List[Dict])]
    """
    # Get workflow records with pagination support
    workflow_records = query_collection(base_api_url, "workflow_execution_set", max_page_size)
    click.echo(f"Workflow Executions Set: {len(workflow_records.get('resources', []))} records retrieved.")

    # Get data object set with pagination support
    data_object_set = get_data_object_set(base_api_url, max_page_size)
    click.echo(f"Data Object Set: {len(data_object_set)} records retrieved.")

    # Process workflows
    workflow_outputs_dict = {}
    total_file_size_bytes = 0
    for record in workflow_records.get("resources", []):
        has_output_list = record.get("has_output", [])
        workflow_execution = record.get("type").removeprefix("nmdc:")
        workflow_execution_id = record.get("id")
        was_informed_by = record.get("was_informed_by")
        valid_records = []
        for output_id in has_output_list:
            # Cross-reference workflow outputs against data_object_set to filter out invalid/missing records
            output_record = data_object_set.get(output_id)
            if output_record:
                valid_records.append(output_record)
                total_file_size_bytes += output_record.get('file_size_bytes', 0)
        workflow_outputs_dict[workflow_execution_id] = [workflow_execution, was_informed_by, valid_records]

    # Save results
    save_json(workflow_outputs_dict, "valid_data/valid_data.json")
    click.echo(f"Total file size: {total_file_size_bytes} bytes.")
    # throws an exception due to makedirs in save_json if filename does not contain dir in path
    # add try except block, and print stack trace using traceback module

    return workflow_outputs_dict


def create_json_structure(workflow_execution_id: str, workflow_execution: str, was_informed_by: str, metadata_keys_list: List[Dict]) -> Dict:
    """
    Create a standardized JSON structure for workflow execution metadata.

    Args:
        workflow_execution_id: Unique identifier for the workflow execution
        workflow_execution: Type/name of the workflow execution
        metadata_keys_list: List of dictionaries containing file metadata

    Returns:
        Dictionary with structure:
        {
            "metadata": {
                "workflow_execution": str,
                "workflow_execution_id": str
            },
            "outputs": [
                {
                    "file": str,
                    "label": str,
                    "metadata": {
                        "file_format": str,
                        "data_object_id": str,
                        "was_informed_by": str
                    }
                },
                ...
            ]
        }
    """
    # contains list of dicts of metadata specific to each file
    outputs = []

    for metadata_keys in metadata_keys_list:
        # generates metadata specific to each file
        try:
            file = metadata_keys["file"]
            data_object_id = metadata_keys["data_object_id"]
            output = {
                "file": file,
                "label": metadata_keys["label"],
                "metadata": {
                    "data_object_id": metadata_keys["data_object_id"],
                    "data_object_type": metadata_keys["data_object_type"]
                }
            }
            outputs.append(output)
        except KeyError:
            logging.error(f"ERROR: key not found error: {file} data_object_id: {data_object_id}\n stack trace: {traceback.format_exc()}")
            return

    return {
        "metadata": {
            "workflow_execution": workflow_execution,
            "workflow_execution_id": workflow_execution_id,
            "was_informed_by": was_informed_by

        },
        "outputs": outputs
    }


def _get_file_suffix():
    config_yaml = 'config.yaml'

    with open(config_yaml, 'r') as config_file:
        config_yaml_data = yaml.safe_load(config_file)
    config_json = json.loads(json.dumps(config_yaml_data, indent=4))

    data_object_type_suffix_dict = {}
    for data_object in config_json["Data Objects"]["Unique"]:
        data_object_type_suffix_dict[data_object['data_object_type']] = data_object['nmdc_suffix']

    return data_object_type_suffix_dict


def generate_metadata_file(workflow_execution_id: str, workflow_execution: str, was_informed_by: str, records: List, emsl_only: bool = False, nersc_only: bool = False):
    """
    Generate and save metadata file for a specific workflow execution.

    Processes each record to extract relevant metadata and creates a structured JSON file.
    The output file is named 'metadata_{workflow_execution_id}.json'.

    Args:
        workflow_execution_id: Unique identifier for the workflow execution
        workflow_execution: Type/name of the workflow execution
        records: List of record dictionaries containing workflow output data
        emsl_only: If True, only process EMSL data records
        nersc_only: If True, only process NERSC data records
    """
    try:
        # Try to load workflow labels from file
        with open('workflow_labels.json', 'r') as workflow_labels_file:
            workflow_labels = json.load(workflow_labels_file)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.error("workflow_labels.json not found or invalid, generating from templates...")
        return
    
    if workflow_execution not in workflow_labels.keys():
        logging.warning(f"workflow_execution {workflow_execution} {workflow_execution_id} type not supported")
        return

    metadata_keys_list: List[Dict] = []

    for record in records:
        """Process a single record and extract relevant information."""
        metadata_keys: Dict = {}

        url = record["url"]
        metadata_keys["url"] = url
        
        # Handle both NERSC and EMSL data URLs
        nersc_prefix = "https://data.microbiomedata.org/data/"
        emsl_prefix = "https://nmdcdemo.emsl.pnnl.gov/"
        
        # Apply URL filtering based on flags
        if emsl_only and not url.startswith(emsl_prefix):
            continue
        if nersc_only and not url.startswith(nersc_prefix):
            continue
        
        if url.startswith(nersc_prefix):
            file = "/global/cfs/cdirs/m3408/results/" + url.removeprefix(nersc_prefix)
        elif url.startswith(emsl_prefix):
            file = "/global/cfs/cdirs/m3408/emsl_backup/" + url.removeprefix(emsl_prefix)
        else:
            logging.warning(f"Data {url} outside NERSC and EMSL")
            continue

        record["name"] = file
        metadata_keys["file"] = file

        data_object_id = record["id"]
        metadata_keys["data_object_id"] = data_object_id
        data_object_type = record["data_object_type"]
        metadata_keys["data_object_type"] = data_object_type

        if file.endswith("scaffold_lineage.tsv"): # hardcoding label for this file format # bug in referenced nmdc config file?
            metadata_keys["label"] = "lineage_tsv"
        else:
            if file.endswith(".gz") or file.endswith("zip"):
                metadata_keys["compression"] = file.split('.')[-1]
            # json structure: {"mags": {data_object_type1, label1},..}
            try:
                metadata_keys["label"] = workflow_labels[workflow_execution][data_object_type]
            except KeyError:
                logging.error(f"ERROR: label not found for workflow_execution:{workflow_execution}, data_object_type:{data_object_type}, url:{url}, data_object_id:{data_object_id} \n Stack trace: {traceback.format_exc()}")

        metadata_keys_list.append(metadata_keys)

    json_structure = create_json_structure(workflow_execution_id, workflow_execution, was_informed_by, metadata_keys_list)
    if json_structure is None:
        logging.error(f"Could not generate metadata structure for {workflow_execution} {workflow_execution_id}")
    save_json(json_structure, f"metadata_files/metadata_{was_informed_by}_{workflow_execution_id}.json")


def process_data(valid_data: Dict[str, List], emsl_only: bool = False, nersc_only: bool = False):
    """
    Process valid data and generate metadata files for each workflow type.

    Args:
        valid_data: Dictionary where:
            - key (str): workflow_execution_id
            - value (List): [workflow_execution_type (str), list_of_records (List[Dict])]
        emsl_only: If True, only process EMSL data records
        nersc_only: If True, only process NERSC data records
    """
    count_workflow_execution_records = {} # sanity check
    for workflow_execution_id, [workflow_execution, was_informed_by, records] in valid_data.items():
        count_workflow_execution_records[workflow_execution] = count_workflow_execution_records.get(workflow_execution, 0) + 1
        generate_metadata_file(workflow_execution_id, workflow_execution, was_informed_by, records, emsl_only, nersc_only)

    click.echo(f"number of records of each workflow execution: {count_workflow_execution_records}")


def parse_workflow_templates(template_dir: str = None) -> Dict[str, Dict[str, str]]:
    """
    Parse all NMDC workflow template YAML files to extract label and data_object_type mappings.

    Args:
        template_dir: Directory containing workflow template YAML files
                     (defaults to current directory if None)

    Returns:
        Dictionary mapping workflow types to their data_object_type -> label mappings
    """
    if template_dir is None:
        template_dir = os.path.dirname(os.path.abspath(__file__))

    workflow_labels = {}
    template_pattern = os.path.join(template_dir, "nmdc_*.yaml")

    for template_file in glob.glob(template_pattern):
        try:
            with open(template_file, 'r') as file:
                template_data = yaml.safe_load(file)

            workflow_name = template_data.get('name', '')
            if not workflow_name.startswith('NMDC'):
                continue

            # Extract the workflow type (remove NMDC prefix)
            workflow_type = workflow_name.removeprefix('NMDC')

            # Initialize the mapping dictionary for this workflow type
            workflow_labels[workflow_type] = {}

            # Process each output to extract label and data_object_type mapping
            for output in template_data.get('outputs', []):
                label = output.get('label')
                data_object_type = output.get('default_metadata_values', {}).get('data_object_type')

                if label and data_object_type:
                    workflow_labels[workflow_type][data_object_type] = label

        except Exception as e:
            logging.error(f"Error parsing template file {template_file}: {str(e)}")
            continue

    return workflow_labels


def generate_workflow_labels_json(template_dir: str = None, output_file: str = 'workflow_labels.json') -> None:
    """
    Generate the workflow_labels.json file from workflow template YAML files.

    Args:
        template_dir: Directory containing workflow template YAML files
        output_file: Path to the output JSON file

    Returns:
        None
    """
    workflow_labels = parse_workflow_templates(template_dir)

    # Check if we have any valid workflow mappings
    if not workflow_labels:
        logging.warning("No valid workflow templates found")
        return

    # Save the generated workflow labels to JSON
    save_json(workflow_labels, output_file)
    logging.info(f"Generated workflow labels file: {output_file}")
    logging.debug(f"Generated workflow labels for: {', '.join(workflow_labels.keys())}")

    return

def main():
    """
    Main execution function that orchestrates the workflow:
    1. Retrieves workflow execution data from API
    2. Processes and validates the data
    3. Generates individual metadata files for each workflow execution
    """
    parser = argparse.ArgumentParser(description="Run specific methods based on flags")
    parser.add_argument("--clean", action="store_true", help="Start a clean run with a fresh pull of NMDC data from the runtime api")
    parser.add_argument("--generate-labels", type=str, metavar="TEMPLATE_DIR", help="Generate workflow_labels.json from YAML templates in the specified directory")
    parser.add_argument("--emsl-only", action="store_true", help="Only process EMSL data records")
    parser.add_argument("--nersc-only", action="store_true", help="Only process NERSC data records")
    args = parser.parse_args()
    
    # Validate mutually exclusive flags
    if args.emsl_only and args.nersc_only:
        parser.error("--emsl-only and --nersc-only are mutually exclusive")
    
    # Generate workflow labels if requested
    if args.generate_labels:
        generate_workflow_labels_json(args.generate_labels)
    
    if args.clean:
        get_workflow_execution_set() # Produces valid_data.json

    # Check if valid_data.json exists before trying to load it
    if not os.path.exists('valid_data/valid_data.json'):
        logging.error("valid_data/valid_data.json not found. Run with --clean first.")
        return

    with open('valid_data/valid_data.json', 'r') as valid_data_file:
        valid_data = json.load(valid_data_file)

    # Process valid data
    process_data(valid_data, args.emsl_only, args.nersc_only)

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    try:
        main()
    except Exception as e:
        logging.error(f"Error in main execution: {str(e)}")
        logging.error(traceback.format_exc())
        sys.exit(1)

# todo logging