#!/bin/bash

# Input JSON file
input_file="agent.state"

# Output TSV file
output_file="summary.tsv"

# Write header
echo -e "workflow_id\twas_informed_by\tactivity_id\tlast_status\tdone\tnmdc_jobid" > "$output_file"

# Extract data with jq and append to the file
# jq -r '.jobs[] | select(.workflow != null) | [.workflow.id, .config.was_informed_by, .config.activity_id, .last_status] | @tsv' "$input_file" >> "$output_file"
jq -r '
  .jobs[]
  | [
      .workflow.id,
      (.config.was_informed_by | join(",")),
      .config.activity_id,
      .last_status,
      .done,
      .nmdc_jobid
    ]
  | @tsv
' "$input_file" >> "$output_file"

echo "Saved extracted data to $output_file"

