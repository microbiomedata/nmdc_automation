#!/bin/bash
#SBATCH --account=m3408  
#SBATCH --qos=regular                   # https://docs.nersc.gov/jobs/policy/#perlmutter-cpu
#SBATCH --cpus-per-task=2
#SBATCH --nodes=1
#SBATCH --ntasks=1  
#SBATCH --time=1-00:00:00  
#SBATCH --constraint=cpu
#SBATCH --mem=4GB                       # requests 4 GB RAM (typical usage ~1 GB)
#SBATCH --mail-type=ALL                 ### Mail events (NONE, BEGIN, END, FAIL, REQUEUE, ALL)
#SBATCH --mail-user=USER@email.gov        ### Where to send mail
#SBATCH --output=OUT/extract_%j.out
#SBATCH --error=OUT/extract_%j.err
#SBATCH --job-name=extract_stats

set -euo pipefail

# activate cromwell env
cromwell-load(){
    module load python
    conda activate nersc-cromwell
}

input_file="$1"
echo "$input_file"
# auth bearer from api using nmdcda client creds, can use queries endpoint to generate
auth=""

# Read CSV file line by line
while IFS=',' read -r col1 col2; do
    # Skip empty lines
    [ -z "$col1$col2" ] && continue
    # skip lines without nmdc
    [[ "$col1,$col2" != *nmdc* ]] && continue

    # Trim whitespace
    col1=$(echo "$col1" | xargs)
    col2=$(echo "$col2" | xargs)

    echo -e "processing $col1 $col2"

    # Create a temp file
    tmp_json_file="$(mktemp --suffix='.json')"

    # Write JSON content    
    cat > "$tmp_json_file" <<EOF
{
  "extract_assembly_stats.data_gen_id": "$col1",
  "extract_assembly_stats.assembly_id": "$col2",
  "extract_assembly_stats.auth": "$auth"
}
EOF

    echo "Created: $tmp_json_file"

    cromwell -Dconfig.file=/path/to/nersc/cromwell_jaws_shifter.conf \
        run -i $tmp_json_file \
        -p imports.zip \
        ./imported_stats.wdl

    # sleep 15
    echo -e "finished $col1 $col2"

done < "$input_file"

echo -e "all IDs done"

exit