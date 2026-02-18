version 1.0

workflow calculate_assembly_stats {
    input {
        File base_proj_dir = "/global/cfs/cdirs/m3408/results"
        String data_gen_id
        String assembly_id
        String prefix=sub(assembly_id, ":", "_")
        String rename_contig_prefix=prefix # default "scaffold"
        File scaffold_file="~{base_proj_dir}/~{data_gen_id}/~{assembly_id}/~{prefix}_scaffolds.fna"
        String bbtools_container = "microbiomedata/bbtools:39.03"
        String workflowmeta_container="microbiomedata/workflowmeta:1.1.1"
        String auth
    }

    call calc_stats {
        input: 
        scaffold_file = scaffold_file,
        rename_contig_prefix = rename_contig_prefix,
        container = bbtools_container
    }
    call format_stats {
        input:
        input_stats = calc_stats.stats_file,
        container = workflowmeta_container
    }

    call upload_stats {
        input:
        stats_json = format_stats.stats_json,
        assembly_id = assembly_id,
        auth = auth,
        container = workflowmeta_container
    }

    output {
        File stats_json = format_stats.stats_json
    }
}

task calc_stats {
    input {
        File scaffold_file
        String rename_contig_prefix
        String stats_out = "stats.json"
        String container
    }

    command <<<
        if [ "~{rename_contig_prefix}" != "scaffold" ]; then
            sed -i 's/scaffold/~{rename_contig_prefix}_scf/g' ~{scaffold_file}
        fi
        bbstats.sh format=8 in=~{scaffold_file} out=stats.json
        sed -i 's/l_gt50k/l_gt50K/g' stats.json
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

task format_stats {
    input {
        File input_stats
        String container
        String output_stats = "stats.json"

    }
    command <<<
        ## Remove an extra field from the stats and normalize keys
        cat ~{input_stats} | jq 'del(.filename)' > ~{output_stats}.tmp

        python3 <<EOF
        import json

        with open("~{output_stats}.tmp") as f:
            stats = json.load(f)

        key_map = {
            "ctg_N50": "ctg_n50",
            "ctg_L50": "ctg_l50",
            "ctg_N90": "ctg_n90",
            "ctg_L90": "ctg_l90",
            "scaf_N50": "scaf_n50",
            "scaf_L50": "scaf_l50",
            "scaf_N90": "scaf_n90",
            "scaf_L90": "scaf_l90",
            "scaf_n_gt50K": "scaf_n_gt50k",
            "scaf_l_gt50K": "scaf_l_gt50k",
            "scaf_pct_gt50K": "scaf_pct_gt50k"
        }

        for old, new in key_map.items():
            if old in stats:
                stats[new] = stats.pop(old)

        with open("~{output_stats}", "w") as f:
            json.dump(stats, f, indent=2)
        EOF
    >>>

    output {
        File stats_json = output_stats
    }
    runtime {
     memory: "10 GiB"
     cpu:  1
     maxRetries: 1
     docker: container
     runtime_minutes: 60
   }
}

task upload_stats {
    input {
        File stats_json
        String assembly_id
        String container
        String auth
    }

    command <<<
    python3 <<EOF
    import sys
    import json
    import requests

    with open("~{stats_json}") as f:
        stats = json.load(f)

    headers = {'accept': 'application/json', 'Authorization': 'Bearer ~{auth}'}
    update_query = {
        "update": "workflow_execution_set",
        "updates": 
               [{ "q": {"id": "~{assembly_id}"},
                "u": {"\$set": stats},
                "limit": 1}]
            }
    print(update_query)

    response = requests.post(
            'https://api.microbiomedata.org/queries:run', json=update_query, headers=headers
        )
    if response.status_code == 200:
        print("Successfully updated the database")
    else: 
        print(f"Error in response: {response.status_code}")
        sys.exit(1)

    EOF
    >>>

    runtime {
     memory: "10 GiB"
     cpu:  1
     maxRetries: 1
     docker: container
     runtime_minutes: 60
   }
}