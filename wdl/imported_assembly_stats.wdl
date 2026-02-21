version 1.0
import "assembly_stats.wdl" as asm_stats

workflow extract_assembly_stats {
    input {
        File base_proj_dir = "/global/cfs/cdirs/m3408/results"
        File label_mapping="/global/cfs/cdirs/m3408/aim2/dev/kli_training/ticket_1471_stats_backfill/label_mapping.csv"
        String data_gen_id
        String assembly_id
        String prefix=sub(assembly_id, ":", "_")
        String info_file="~{base_proj_dir}/~{data_gen_id}/~{assembly_id}/~{prefix}_metaAsm.info"
        String workflowmeta_container="microbiomedata/workflowmeta:1.1.1"
        String auth
    }

    call extract_stats {
        input: 
        info_file = info_file,
        label_mapping = label_mapping,
        container = workflowmeta_container
    }
    
    call asm_stats.format_stats {
        input:
        input_stats = extract_stats.stats_file,
        container = workflowmeta_container
    }
    call asm_stats.upload_stats {
        input:
        stats_json = format_stats.stats_json,
        assembly_id = assembly_id,
        container = workflowmeta_container,
        auth = auth
    }

    output {
        File stats_json = format_stats.stats_json
    }
}

task extract_stats {
    input {
        File info_file
        File label_mapping
        String stats_out = "stats.json"
        String container
    }

    command <<<
    set -eou pipefail

    echo "{" > ~{stats_out}
    # Read CSV file line by line
    while IFS=',' read -r key pattern awk_cmd; do
        # Skip empty lines
        [ -z "$key$pattern$awk_cmd" ] && continue

        # Trim whitespace
        key=$(echo "$key" | xargs | sed 's/^\xEF\xBB\xBF//')
        pattern=$(echo "$pattern" | xargs | sed 's/^\xEF\xBB\xBF//')
        awk_cmd=$(echo "$awk_cmd" | xargs | sed 's/^\xEF\xBB\xBF//')
        stat=$(awk  -F'\t' -v pat="$pattern" "$awk_cmd" ~{info_file} | xargs | tr -d ',')
        # leave out comma for last json entry
        echo -e "\t\"$key\": $stat$( [[ "$key" != "gc_std" ]] && echo ',' )" >> "~{stats_out}"

    done < ~{label_mapping}
    echo -e "}" >> ~{stats_out}
    >>>

    output {
        File stats_file = stats_out
    }

    runtime {
     memory: "10 GiB"
     cpu:  1
     maxRetries: 1
     docker: container
     runtime_minutes: 60
    }
}

