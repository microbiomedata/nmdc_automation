import os
import argparse
import gzip
import zipfile
import json
import csv
import sys
from datetime import datetime
from nmdc_automation.config import SiteConfig


VALID_EMPTY_GROUPS = [
    {
        "name": "Annot Crispr",
        "file_types": ["Crispr Terms", "CRT Annotation GFF"]
    }
]

# Valid only if MAGs produced no data
VALID_EMPTY_MAG_PLOTS = [ "Metagenome Bins Heatmap", "Metagenome Bins Barplot"]
    
# Validation helper functions

def check_trailing_newline(filepath):
    try:
        with open(filepath, 'rb') as f:
            f.seek(-1, os.SEEK_END)
            last_char = f.read(1)
            return last_char in [b'\n', b'\r']
    except Exception:
        return False

def check_bam_eof(filepath):
    """
    Checks for the standard 28-byte BAM EOF marker.
    A valid BAM file must end with this specific empty BGZF block.
    """
    # The hex representation of the 28-byte BAM EOF marker
    BAM_EOF = (
        b'\x1f\x8b\x08\x04\x00\x00\x00\x00\x00\xff\x06\x00\x42\x43'
        b'\x02\x00\x1b\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    )
    try:
        file_size = os.path.getsize(filepath)
        if file_size < 28:
            return False
        with open(filepath, 'rb') as f:
            f.seek(-28, os.SEEK_END)
            return f.read(28) == BAM_EOF
    except Exception:
        return False

#
# Main validation function for various expected file extensions        
#
def validate_file(filepath, ext, dry_run=False, verbose=False):
    """Returns (is_valid, message)"""

    
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        if verbose: print(f"    ❌ MISSING: {filepath}")
        return False, "File missing or empty"
    
    if dry_run:
        return True, "DRY RUN: Path exists, skipping content check"

    try:
        # 1. Compressed Files
        if ext == '.gz':
            try:
                with gzip.open(filepath, 'rb') as f:
                    # header check
                    f.read(1024)

                # footer check (using raw binary seek)
                # can't do footer check with gzip.open without reading the entire file
                # # so need to do separate raw binary check for truncation
                with open(filepath, 'rb') as f_raw:
                    f_raw.seek(0, os.SEEK_END)
                    if f_raw.tell() < 18:  # 10 (header) + 8 (trailer)
                        return False, "Truncated GZIP: File too small"
                    
                    f_raw.seek(-8, os.SEEK_END)
                    trailer = f_raw.read(8)
                    if len(trailer) < 8:
                        return False, "Truncated GZIP: Missing trailer"

                return True, "Valid GZIP (Header & Footer verified)"
                
            except (gzip.BadGzipFile, EOFError, OSError) as e:
                return False, f"Corrupted or Truncated GZIP: {str(e)}"
            except Exception as e:
                return False, f"GZIP Read Error: {str(e)}"
            
        if ext == '.zip':
            # This captures zip file corruption, possibly due to truncation
            if zipfile.is_zipfile(filepath):
                return True, "Valid ZIP"
            return False, "Invalid ZIP structure"

            # This can be slow for large files so only check if explicitly asked
            # todo: need to add flag to turn this on if necessary
            #    try:
            #        with gzip.open(filepath, 'rb') as f:
            #            # Seeking to the end of a GZIP file in Python 
            #            # forces it to verify the CRC32 footer.
            #            f.seek(0, os.SEEK_END)
            #        return True, "Valid GZIP"
            #    except (gzip.BadGzipFile, EOFError):
            #        return False, "Corrupted or Truncated GZIP"

        # 2. Sequence Files (FASTA)
        if ext in ['.fna', '.faa']:
            # Truncation check
            if not check_trailing_newline(filepath):
                return False, "Truncated: Missing trailing newline"

            try:
                with open(filepath, 'r') as f:
                    line = f.readline().strip()
                    if line.startswith('>'):
                        return True, "Valid FASTA header"
                    return False, "Missing '>' header"
            except UnicodeDecodeError:
                return False, "Corrupted: Binary bytes in FASTA text"
            except Exception as e:
                return False, f"FASTA Read Error: {str(e)}"

        # 3. Binary Formats (BAM / PDF)
        if ext == '.bam':
            # Truncation check (EOF marker)
            if not check_bam_eof(filepath):
                return False, "Truncated: Missing BAM EOF marker"
            
            # Check that this is bam content
            try:
                with gzip.open(filepath, 'rb') as f:
                    magic_bytes = f.read(4)
                    if magic_bytes == b'BAM\x01':
                        return True, "Valid BAM header"
                    else:
                        # If we got here, it's a valid Gzip but NOT a BAM
                        return False, f"Invalid BAM header (Found: {magic_bytes.hex()})"
            except Exception as e:
                return False, f"BAM Read Error: {str(e)}"
            
        if ext == '.pdf':
            try:
                with open(filepath, 'rb') as f:
                    # check header
                    if f.read(4) != b'%PDF':
                        return False, "Invalid PDF header"
                
                    # check tail
                    # get size to ensure we can seek back 100 bytes
                    f.seek(0, os.SEEK_END)
                    if f.tell() < 100:
                        return False, "Truncated PDF: File too small"
                    # Check for %%EOF in the last 100 bytes
                    f.seek(-100, os.SEEK_END)
                    if b'%%EOF' not in f.read(100):
                        return False, "Truncated PDF: Missing %%EOF"
                return True, "Valid PDF"
            except Exception as e:
                return False, f"PDF Read Error: {str(e)}"

        # 4. Tabular (TSV / GFF / AGP)
        if ext in ['.tsv', '.gff', '.agp']:
            if not check_trailing_newline(filepath):
                return False, "Truncated: Missing trailing newline"

            # corruption Check: ensure it's actually text 
            try:
                with open(filepath, 'r') as f:
                    # Read a small chunk to verify encoding
                    f.read(4096)
                return True, "Valid Text"
            except UnicodeDecodeError:
                return False, "Corrupted: Binary bytes detected in text file"
            except Exception as e:
                return False, f"Read Error: {str(e)}"

            
        
        # Futureproofing: no current json output but here is how to check
        # Untested
        if ext == '.json':
            try:
                # JSON doesn't strictly NEED a newline, but it MUST end with a bracket
                with open(filepath, 'rb') as f:
                    # header check
                    # Read the first 1024 bytes to account for any leading whitespace
                    header_chunk = f.read(1024).lstrip() # lstrip removes only leading whitespace
                    
                    if not header_chunk:
                        return False, "Invalid JSON: Empty/Whitespace-only JSON"
                    if header_chunk[0:1] not in [b'{', b'[']:
                        return False, "Invalid JSON: Missing opening bracket"

                    # tail
                    # 2. Tail Check (The Sliding Window)
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    
                    # read 32 bytes to be safe against multiple newlines
                    seek_back = min(size, 32)
                    f.seek(-seek_back, os.SEEK_END)
                    
                    # strip() removes all trailing \n, \r, and spaces
                    trailing_chunk = f.read(seek_back).strip()
                    if not trailing_chunk:
                        return False, "Invalid JSON: Empty/Whitespace-only JSON"
                    # Check the last non-whitespace character
                    if trailing_chunk[-1:] not in [b'}', b']']:
                        return False, "Truncated JSON: No closing bracket"
                    
                    return True, "Valid JSON (Structural check passed)"
            except Exception as e:
                return False, f"JSON Read Error: {str(e)}"       

        return True, "Basic existence check passed"

    except Exception as e:
        if verbose: print(f"    💥 ERROR: {filepath} ({str(e)})")
        return False, f"Validation error: {str(e)}"



# Example usage:
# generate_audit_report('results.json', 'audit_failures.tsv')
def generate_audit_report(json_input, output_tsv, config, dry_run=False, label=None, verbose=False):
    
    # Retrieve mapping values from SiteConfig
    url_root = config.url_root  # e.g. "https://blah/data"
    data_dir = config.data_dir  # e.g. "/path/on/fs"

    # Record the start time
    start_time = datetime.now()

    # load the aggregation json
    # TODO: replace this with endpoint retrieval data structure
    with open(json_input, 'r') as f:
        data = json.load(f)

    failed_records = []
    error_counts = {}
    total_files_checked = 0
    total_workflows_checked = len(data)

    if dry_run:
        print("\n[DRY RUN MODE ACTIVE]")
        
    for workflow in data:
        wfe_id = workflow.get('workflow_id', 'Unknown_WFE')
        site = workflow.get('processing_institution',"NA")
        if verbose: print(f"\nProcessing WFE: {wfe_id}")

        outputs = workflow.get('outputs', [])
        

        # pre-scan for empty files that have logic to check if it is OK.
        file_is_empty = {}
        path_cache = {} 
        for out in outputs:
            f_type = out.get('file_type')
            url = out.get('url')
            if not url: continue

            # Map URL to Filesystem
            l_path = url.replace(url_root, data_dir).split('?')[0]
            path_cache[f_type] = l_path
            
            # Check if empty or missing
            is_empty = not os.path.exists(l_path) or os.path.getsize(l_path) == 0
            file_is_empty[f_type] = is_empty

        
        empty_pass_types = set()
       
        # Check for valid empty mag files only if binned contigs are
        # found in the workflow and has 0 count
        mag_bin_ctgs = workflow.get('binned_contig_num', None)
        if mag_bin_ctgs is not None:
            if mag_bin_ctgs == 0:
                for f_type in VALID_EMPTY_MAG_PLOTS:
                    if file_is_empty.get(f_type, False):
                        empty_pass_types.add(f_type)


        # find valid empty groups and save them
        for group in VALID_EMPTY_GROUPS:
            group_types = group["file_types"]
            # every file in this specific group must be found and 0-size, then they all get a pass
            if all(file_is_empty.get(t, False) for t in group_types):
                for t in group_types:
                    empty_pass_types.add(t)

        #
        # The main loop for each output file, skipping any empty files that
        # passed the screens above
        #
        for output in outputs:
            total_files_checked += 1
            obj_id = output.get('data_object_id')
            file_type = output.get('file_type')  # Field name from your aggregation
            url = output.get('url')
            
            if not url:
                continue

            # URL to Filesystem Path Mapping 
            # Replace the web root with the local path root
            local_path = url.replace(url_root, data_dir)
            
            # Remove any URL parameters if they exist (e.g. ?download=true)
            local_path = local_path.split('?')[0]
            extension = os.path.splitext(local_path)[1] 
            
            # make the display file type string for useful reporting
            display_type = f"{file_type} ({extension})"

            # If we find the file type already validated as a group
            # If a pair didn't pass and get added to the empty_pass_types, each
            # file in the will be checked individually
            if file_type in empty_pass_types:
                if verbose:
                    print(f"[{total_files_checked}] Logic Pass: {file_type} is part of an all-empty group. Skipping.")
                continue

            # Run validation
            is_valid, message = validate_file(local_path, extension, dry_run)

            # Messaging
            if verbose:
                # Color error \033[91m = Start Red | \033[0m = Reset to Default
                status_suffix = " -> \033[91mERROR\033[0m" if not is_valid else ""
                print(f"[{total_files_checked}] Checking: {os.path.basename(local_path)}{status_suffix}", flush=True)
        
            # Data Handling    
            if not is_valid:
                failed_records.append({
                    "wfe_record_id": wfe_id,
                    "data_object_id": obj_id,
                    "file_type": file_type,
                    "extension": extension,
                    "error": message,
                    "path": local_path,
                    "site": site
                })

                # update count by file type
                error_counts[display_type] = error_counts.get(display_type, 0) + 1

    
    # Write Failure Report
    keys = ["wfe_record_id", "data_object_id", "file_type", "error", "path", "site"]
    with open(output_tsv, 'w', newline='') as f:
        dict_writer = csv.DictWriter(f, fieldnames=keys, delimiter='\t', extrasaction='ignore')
        dict_writer.writeheader()
        dict_writer.writerows(failed_records)
    
    # Calculate unique WFE failures from the list
    unique_wfe_count = len({rec['wfe_record_id'] for rec in failed_records})

    # Count and group specific error reasons
    error_reason_counts = {}
    for r in failed_records:
        msg = r["error"]
        error_reason_counts[msg] = error_reason_counts.get(msg, 0) + 1

    # Record the end time after the loop finishes
    end_time = datetime.now()
    duration = end_time - start_time

    # Calculate percentages
    workflow_fail_pct = (unique_wfe_count / total_workflows_checked * 100) if total_workflows_checked > 0 else 0
    file_fail_pct = (len(failed_records) / total_files_checked * 100) if total_files_checked > 0 else 0

    # Create a mapping: { "Error Message": { "Data Object Type": Count } }
    error_mapping = {}
    for rec in failed_records:
        err = rec['error']
        # Reconstruct the display name with suffix for the report
        obj_with_suffix = f"{rec['file_type']} ({rec['extension']})"
        
        if err not in error_mapping:
            error_mapping[err] = {}
        error_mapping[err][obj_with_suffix] = error_mapping[err].get(obj_with_suffix, 0) + 1

   # Console Summary
    header_width = 70
    print("\n" + "=" * header_width)
    print(f"{'NMDC WORKFLOW AUDIT SUMMARY':^70}")
    print("=" * header_width)

    # Top Metrics Section
    if label:
        print(f"{'Label':>25}    {label}")
    print(f"{'Audit Time':>25}    {start_time.strftime('%Y-%m-%d %H:%M:%S')} PST")
    print(f"{'Audit Duration':>25}    {duration}") # Split to hide microseconds if desired
    print("-" * header_width)

    print(f"{'Workflow Records':>25}    {total_workflows_checked:,}")
    print(f"{'Files Checked':>25}    {total_files_checked:,}")
    print(f"{'Total File Failures':>25}    {len(failed_records)}  ({file_fail_pct:.1f}%)")
    print(f"{'Unique Workflow Failures':>25}    {unique_wfe_count}  ({workflow_fail_pct:.1f}%)")
    print("\n")
    if error_counts:
        print("\nFAILURE CLASSIFICATION & MAPPING")
        print("-" * header_width)
        print(f"{'Count':>5}   {'Reason / Data Object Type'}")
        print("-" * header_width)
        
        # Error Mapping (Reason -> Object Type)
        for reason, objs in sorted(error_mapping.items()):
            # Calculate total for this reason
            reason_total = sum(objs.values())
            print(f"{reason_total:>5}   {reason}")
            
            for obj_type, count in sorted(objs.items(), key=lambda x: x[1], reverse=True):
                # Indent the sub-objects and align their counts
                print(f"{count:>12}   {obj_type}")
            print("") # Blank line between reason groups

        print("-" * header_width)
        print("SUMMARY BY DATA OBJECT")
        print("-" * header_width)
        for f_type, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"{count:>5}   {f_type}")
            
    else:
        print("\nNo validation errors found! 🎉")

    print("=" * header_width)
    print("\n")
    print(f"Detailed report saved to: {output_tsv}\n")


def main():
    parser = argparse.ArgumentParser(description="Audit NMDC workflow outputs.")
    
    # Allows you to pass --config /path/to/config.yaml
    parser.add_argument("-c", "--config", type=str, help="Path to the NMDC site configuration file")
    parser.add_argument("-i", "--input", type=str, required=True, help="JSON file exported from MongoDB")
    parser.add_argument("-o", "--output", type=str, default="audit_report.tsv", help="Filename for the failure report")
    parser.add_argument("-l", "--label", type=str, help="Optional report label in summary outfile")
    parser.add_argument("-dry-run", "--dry-run", action="store_true", help="Skip file content validation, only check path mapping/existence")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print real-time file checks")

    args = parser.parse_args()

    # Verify the config file actually exists on disk before trying to parse it
    if not os.path.exists(args.config):
        print(f"❌ ERROR: Configuration file not found at: {args.config}")
        sys.exit(1)

    try:
        # Initialize config with the explicit path
        config = SiteConfig(args.config)
        
        # Double check that the required keys exist in your config object
        # This prevents KeyErrors later in the script
        if not hasattr(config, 'url_root') or not hasattr(config, 'data_dir'):
            print("❌ ERROR: Config file is missing 'url_root' or 'data_dir' keys.")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ ERROR: Failed to load SiteConfig: {e}")
        sys.exit(1)

    #DEBUG
    print(f"Loaded config from: {args.config}")
    print(f"Mapping {config.url_root} -> {config.data_dir}")
    
    # TODO: check file paths of input/outputs and make them explicit
    # Run the audit
    generate_audit_report(args.input, args.output, config, args.dry_run, args.label, args.verbose)



if __name__ == "__main__":
    main()