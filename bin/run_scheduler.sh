#!/bin/bash
set -euo pipefail
# enable job control
# set -m

# Default values
# LIST="/conf/allow.lst"
# TOML="/conf/site_configuration.toml"
# PID_FILE="/conf/test.sched.pid"
# LOG_FILE="/conf/test.sched.log"
# YAML=$(grep 'workflows_config' "$TOML" | sed 's/.*= *"\(.*\)"/\1/')
set -euo pipefail
WORKSPACE="dev"
LIST="./allow.lst"
TOML="./site_configuration.toml"
PORT="27017"
PID_FILE="./test.sched.pid"
LOG_FILE="./test.sched.log"
FULL_LOG_FILE="./test.sched_full.log"
SLACK_WEBHOOK_URL=$(grep 'slack_webhook' "$TOML" | sed 's/.*= *"\(.*\)"/\1/')
YAML="/Users/kli/Documents/NMDC/nmdc_automation/nmdc_automation/config/workflows/workflows.yaml"

# Global state flags
DEBUG=0
CLEANED_UP=0
RESTARTING=0
MISMATCH=0
HELP=0
MANUAL_STOP=0
SCHED_PID=""
TAIL_PID=""
OLD_PID=""
KILL_PID="NA"
LAST_ALERT=""
LAST_ERROR=""
IGNORE_PATTERN=""
STD_OUT=/dev/null
DAEMONIZE=1  # default to detached run
COMMAND=""   # default start scheduler when script called

# Help message
show_help() {
  echo "Usage: ./run_scheduler.sh [COMMAND] [--yaml PATH] [--allowlist PATH] [--toml PATH] [--port PORT]"
  echo
  echo "Commands:"
  echo "  stop                  Stop the running scheduler"
  echo "  status                Show scheduler status"
  echo
  echo "Options:"
  echo "  -y, --yaml PATH        Path to workflow YAML file (default: $YAML)"
  echo "  -a, --allowlist PATH   Path to allowlist file     (default: $LIST)"
  echo "  -t, --toml PATH        Path to site config TOML   (default: $TOML)"
  echo "  -p, --port PORT        MongoDB port number        (default: $PORT)"
  echo "  -d, --debug            Enable debug mode (outputs to stdout)"
  echo "  -h, --help             Show this help message"
  HELP=1
}

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        stop|status)    COMMAND="$1"; shift;;
        -y|--yaml)      YAML="$2"; shift 2 ;;
        -a|--allowlist) LIST="$2"; shift 2 ;;
        -t|--toml)      TOML="$2"; shift 2 ;;
        -p|--port)      PORT="$2"; shift 2 ;;
        -d|--debug)     DEBUG=1; DAEMONIZE=0; shift ;;
        -h|--help)      show_help; exit 0 ;;
        *)              echo "Unknown option: $1"; show_help; exit 1 ;;
    esac
done


# Functions
send_slack_notification() {
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

get_timestamp() {
    TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y"
}

log() {
    if [ -n "$1" ]; then
        # Direct message
        printf '[%s] %s\n' "$(get_timestamp)" "$1" | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > "$STD_OUT"
    else
        # Read from stdin (for piped input)
        while IFS= read -r line; do
            printf '[%s] %s\n' "$(get_timestamp)" "$line" | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > "$STD_OUT"
        done
    fi
}

log_status() {
  log "CLEANED_UP RESTARTING MISMATCH KILL_PID DEBUG" 
  log "$CLEANED_UP $RESTARTING $MISMATCH $KILL_PID $DEBUG" 
}

cleanup() {
    pkill -u "$USER" -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true
    if [[ $CLEANED_UP -eq 1 ]]; then return; fi
    log "Cleanup triggered."
    CLEANED_UP=1
    log_status
        
    # Always clean up tail process if it exists    
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null || true 
        pkill -P "$TAIL_PID" 2>/dev/null || true
    fi
        
    # If this cleanup was triggered by a restart, kill the old PID
    if [[ $RESTARTING -eq 1 && -n "$KILL_PID" ]]; then
        kill "$KILL_PID" 2>/dev/null
        send_slack_notification ":arrows_counterclockwise: *Scheduler-$WORKSPACE script refresh* at \`$(get_timestamp)\` (replacing PID \`$OLD_PID\`)"
        log "Scheduler script restarted" 
    # If this cleanup was triggered by a manual kill, kill the old PID and exit
    elif [[ $MANUAL_STOP -eq 1 ]]; then
        send_slack_notification ":x: *Scheduler-$WORKSPACE manually stopped* at \`$(get_timestamp)\`"
        log "Scheduler terminated"
        exit 0
    fi

    # Only send termination message if not restarting and no mismatch
    if [ "$RESTARTING" -eq 1 ] || [ "$MISMATCH" -eq 1 ] || [ "$HELP" -eq 1 ]; then
        :  # no-op, do nothing
    else
        EXIT_MESSAGE=":x: *Scheduler-$WORKSPACE script terminated* at \`$(get_timestamp)\`"
        if [[ -n "$LAST_ERROR" && "$LAST_ERROR" != "$LAST_ALERT" ]]; then
            EXIT_MESSAGE=":x: *Scheduler-$WORKSPACE script terminated* at \`$(get_timestamp)\`.\nLatest error:\n\`\`\`$LAST_ERROR\`\`\`"
        fi
        send_slack_notification "$EXIT_MESSAGE"
        log "Scheduler script terminated" 
        exit 0
    fi
}

# trap 'kill $SCHED_PID; cleanup' SIGINT SIGTERM EXIT
# trap 'MANUAL_STOP=1; RESTARTING=0; MISMATCH=0; HELP=0; kill "$SCHED_PID" 2>/dev/null; cleanup' SIGINT SIGTERM
trap cleanup SIGINT SIGTERM EXIT

# process commands
if [[ "$COMMAND" == "stop" || "$COMMAND" == "status" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        read -r OLD_PID < "$PID_FILE"
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            if [[ "$COMMAND" == "stop" ]]; then
                echo "Stopping scheduler PID $OLD_PID..."
                MANUAL_STOP=1; RESTARTING=0; MISMATCH=0; HELP=0
                cleanup
            else
                echo "Scheduler is running (PID $OLD_PID)"
            fi
        else
            echo "Scheduler PID $OLD_PID not running"
        fi
    else
        [[ "$COMMAND" == "stop" ]] \
            && echo "No PID file found; scheduler may not be running" \
            || echo "Scheduler not running"
    fi
    exit 0
fi

# set env vars
export MONGO_PORT="$PORT"
export NMDC_WORKFLOW_YAML_FILE="$YAML"
export NMDC_SITE_CONF="$TOML"
export NMDC_LOG_LEVEL=INFO # info by default every time. 
rm "$LOG_FILE"

if [[ "$DEBUG" -eq 1 ]]; then
    export NMDC_LOG_LEVEL=DEBUG
    [[ "$DEBUG" == "1" ]] && STD_OUT=/dev/stdout
    log "Debug mode enabled."
fi


# Check if PID file exists
if [[ -f "$PID_FILE" ]]; then
    read -r OLD_PID < "$PID_FILE"
    # check for PID process
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        COMMAND_NAME=$(ps -p "$OLD_PID" -o comm=)
        PROC_COMMAND=$(ps -p "$OLD_PID" -o args=)
        # check command name and command process include python and sched
        if [[ "$COMMAND_NAME" == *python* && "$PROC_COMMAND" == *sched* ]]; then
            log "Found running scheduler process $OLD_PID: $COMMAND_NAME"
            RESTARTING=1
            KILL_PID="$OLD_PID"
            cleanup
        else
            log "PID $OLD_PID is not the scheduler, skipping kill"
            MISMATCH=1
        fi
    else
        log "PID $OLD_PID not running"
    fi
else
    log "PID file $PID_FILE does not exist"
fi

# Look for orphaned scheduler processes outside of PID file
if EXISTING_PID=$(pgrep -u "$USER" -f "python.*sched" 2>/dev/null); then
    for PID in $EXISTING_PID; do
        [[ "$PID" == "$OLD_PID" ]] && continue
        PROC_COMMAND=$(ps -p "$PID" -o args= 2>/dev/null || echo "(unknown)")
        log "Removing scheduler process without PID file: $PID ($PROC_COMMAND)"
        kill "$PID" 2>/dev/null || true
    done
fi

# clean up logging
[[ -n "$TAIL_PID" ]] && kill "$TAIL_PID" 2>/dev/null || true
pkill -u "$USER" -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true

# log "Passed cleanup checks"

# log "Starting monitoring"
tail -n 0 -F "$LOG_FILE" | while IFS= read -r line; do
    # Detect traceback start
    if [[ "$line" == *"Traceback (most recent call last):"* ]]; then
        TRACEBACK_LINES=()
        while IFS= read -r -t 1 tb_line; do
            # Stop if next line looks like a log timestamp
            if [[ "$tb_line" =~ ^\[.*\] ]] || [[ "$tb_line" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
                break
            fi
            TRACEBACK_LINES+=("$tb_line")
        done

        # Extract only meaningful error lines
        ERROR_SUMMARY=$(printf "%s\n" "${TRACEBACK_LINES[@]}" \
        | grep -E "[A-Za-z]+Error:|Exception:" \
        | sed -E 's/with url: .*//' \
        | sed -E 's/^[^:]+: //' \
        | sort -u 2>/dev/null )

         # fallback if no summary found
        if [[ -z "$ERROR_SUMMARY" ]]; then
            ERROR_SUMMARY="${TRACEBACK_LINES[-1]}"
        fi

        # Only alert if something meaningful matched
        if [[ -n "$ERROR_SUMMARY" && "$ERROR_SUMMARY" != "$LAST_ALERT" ]]; then
            send_slack_notification \
              ":warning: *Scheduler-$WORKSPACE ERROR* at \`$(get_timestamp)\`:\n\`\`\`\n$ERROR_SUMMARY\n\`\`\`"
            LAST_ALERT="$ERROR_SUMMARY"
        fi
        continue
    fi

    # Detect single-line ERROR logs
    shopt -s nocasematch
    if [[ "$line" =~ error|exception|warning ]]; then
        [[ "$line" =~ $IGNORE_PATTERN ]] && continue
        if [[ "$line" != "$LAST_ALERT" || "$line" == *"$ALERT_PATTERN"* ]]; then
            send_slack_notification \
              ":warning: *Scheduler-$WORKSPACE ERROR* at \`$(get_timestamp)\`:\n\`\`\`$line\`\`\`"
            LAST_ALERT="$line"
        fi
    fi
    shopt -u nocasematch
done &
TAIL_PID=$!

RESTARTING=0
CLEANED_UP=0
send_slack_notification ":rocket: *Scheduler-$WORKSPACE started* at \`$(get_timestamp)\`"
log "Scheduler script started" 

log_status

# DRYRUN=1 \
# ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
#     "$NMDC_SITE_CONF" \
#     "$NMDC_WORKFLOW_YAML_FILE" \
#     2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > "$STD_OUT" &

# python sched.py  2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > "$STD_OUT" &

poetry run pytest /Users/kli/Documents/NMDC/nmdc_automation/tests/test_sched.py | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > "$STD_OUT" &

SCHED_PID=$!
echo "$SCHED_PID" > "$PID_FILE"
wait "$SCHED_PID"
sleep 1
cleanup

# # Only wait and trap cleanup if not detached
# if [[ $DAEMONIZE -eq 0 ]]; then
#     trap 'kill $SCHED_PID $TAIL_PID; cleanup' SIGINT SIGTERM
#     wait "$SCHED_PID"
#     cleanup
# else
#     # Detached mode: wrapper exits immediately
#     echo "Scheduler started (PID $SCHED_PID). Tail PID: $TAIL_PID"
#     exit 0
# fi



# (
#   if [[ "$DEBUG" -eq 1 ]]; then
#     log "Debug mode enabled."
#     export NMDC_LOG_LEVEL=DEBUG
#   fi

#   PIPE=$(mktemp -u /tmp/sched.$$.pipe.XXXXX); mkfifo "$PIPE"
#   tee -a "$LOG_FILE" "$FULL_LOG_FILE" < "$PIPE" > /dev/null &
#   TEE_PID=$!

#   # cd /src

#   # # Run the Python script
#   # ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
#   #     "$NMDC_SITE_CONF" \
#   #     "$NMDC_WORKFLOW_YAML_FILE" \
#   #     2>&1 | tee /conf/sched.log >> /conf/sched_full.log &

#   python sched.py > "$PIPE" 2>&1 &
#   SCHED_PID=$!

#   echo "$SCHED_PID" > "$PID_FILE"
#   wait "$SCHED_PID"
#   rm -f "$PIPE"
# ) &
# LAUNCH_PID=$!

# wait $LAUNCH_PID