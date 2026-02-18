#!/bin/bash
#SBATCH --account=m3408  
#SBATCH --qos=regular                   # https://docs.nersc.gov/jobs/policy/#perlmutter-cpu
#SBATCH --cpus-per-task=2
#SBATCH --nodes=1
#SBATCH --ntasks=1  
#SBATCH --time=1-00:00:00  
#SBATCH --constraint=cpu
#SBATCH --mem=16GB                       # uses around 15 gb max
#SBATCH --mail-type=ALL                 ### Mail events (NONE, BEGIN, END, FAIL, REQUEUE, ALL)
#SBATCH --mail-user=user@email.gov
#SBATCH --output=OUT/run_stats_%j.out
#SBATCH --error=OUT/run_stats_%j.err
#SBATCH --job-name=run_stats

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

    cat > "$tmp_json_file" <<EOF
{
  "calculate_assembly_stats.data_gen_id": "$col1",
  "calculate_assembly_stats.assembly_id": "$col2",
  "calculate_assembly_stats.auth": "$auth"
}
EOF
    echo "Created: $tmp_json_file"

    cromwell -Dconfig.file=/path/to/nersc/cromwell_jaws_shifter.conf \
        run -i $tmp_json_file \
        ./assembly_stats.wdl 

    # sleep 15
    echo -e "finished $col1 $col2"

done < "$input_file"

echo -e "all IDs done"

exit