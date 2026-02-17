import json
import pytest
import linkml.validator as validator
from linkml_runtime.loaders import json_loader
import nmdc_automation.models.nmdc as automation_models


@pytest.fixture
def data():
    """Load the JSON data file to validate."""
    with open("tests/fixtures/nmdc_db/lipidomics_data_objects.json") as f:
        return json.load(f)



def test_data_conforms_to_schema(data):
    """
    Validate a JSON document against the LinkML schema defined in the nmdc-schema package.
    """
    #load schema
    nmdc_materialized = automation_models.get_nmdc_materialized()
    # Load into the LinkML dataclass (this will raise on major structural errors)
    for record in data:
        #determine target class name from type field
        target_class=record['type'].removeprefix("nmdc:")
        validation_report = validator.validate(record, nmdc_materialized, target_class)
        # Ensure no validation errors
        assert not validation_report.results, f"Schema validation errors for {record['id']}: {validation_report.results}"