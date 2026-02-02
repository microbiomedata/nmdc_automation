#!/bin/bash
set -euo pipefail

# Default values
WORKSPACE="prod"
CONF="./site_configuration.toml"
# CONF=/global/homes/n/nmdcda/nmdc_automation/$WORKSPACE/site_configuration_nersc_$WORKSPACE.toml
HOST=$(hostname)
LOG_FILE=watcher-$WORKSPACE.log
PID_FILE=watcher-$WORKSPACE.pid
HOST_FILE=host-$WORKSPACE.last
SLACK_WEBHOOK_URL=$(grep 'slack_webhook' "$CONF" | sed 's/.*= *"\(.*\)"/\1/')
PVENV=/Users/kli/Library/Caches/pypoetry/virtualenvs/nmdc-automation-FtOYRXpA-py3.11
# PVENV=/global/cfs/cdirs/m3408/nmdc_automation/$WORKSPACE/nmdc_automation/.venv
COMMAND=""   # default start watcher when script called

# Global state flags
CLEANED_UP=0
RESTARTING=0
MISMATCH=0
HELP=0
MANUAL_STOP=0
TRACEBACK_MODE=0
KILL_PID=""
WATCHER_PID=""
OLD_PID=""
OLD_HOST=""
TAIL_PID=""
LAST_ALERT=""
LAST_ERROR=""
IGNORE_PATTERN="Error removing directory /tmp: \[Errno 13\] Permission denied: .*/tmp|['\"]error['\"]:[[:space:]]*['\"][[:space:]]*['\"]"
ALERT_PATTERN='Internal Server Error'
TRACEBACK_LINES=()
ERROR_SUMMARY=""
ALERT_EPOCH="${LAST_ALERT_EPOCH:-0}"
TRACEBACK_EPOCH="${TRACEBACK_EPOCH:-0}"


# Help message
show_help() {
  echo "Usage: ./run_watcher_[prod/dev].sh [COMMAND] [--conf PATH]"
  echo
  echo "Commands:"
  echo "  stop                  Stop the running watcher"
  echo "  status                Show watcher status"
  echo
  echo "Options:"
  echo "  -c, --conf PATH        Path to site config TOML   (default: $CONF)"
  echo "  -h, --help             Show this help message"
  HELP=1
}

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        stop|status)    COMMAND="$1"; shift;;
        -c|--conf)      CONF="$2"; shift 2 ;;
        -h|--help)      show_help; exit 0 ;;
        *)              echo "Unknown option: $1"; show_help; exit 1 ;;
    esac
done

# ----------- Functions ----------- 
send_slack_notification() {
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

get_timestamp() {
    echo "$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")"
}

echo_status() {
    echo "CLEANUP RESTARTING MISMATCH KILL_PID HELP MANUAL_STOP"
    echo $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID $HELP $MANUAL_STOP
}

check_host_match() {
    if [[ -f "$HOST_FILE" ]]; then
        read -r OLD_HOST < "$HOST_FILE"
        if [[ -n "$OLD_HOST" && "$OLD_HOST" != "$HOST" ]]; then
            echo "Host mismatch: existing watcher was on '$OLD_HOST', current host is '$HOST'."
            return 1
        fi
    fi
    return 0
}

traceback_summary() {
    [[ ${#TRACEBACK_LINES[@]} -eq 0 ]] && return 1
    local summary

    summary=$(printf "%s\n" "${TRACEBACK_LINES[@]}" \
        | grep -E "[A-Za-z]+Error:|Exception:" \
        | sed -E 's/with url: .*//' \
        | sed -E 's/^[^:]+: //' \
        | sort -u 2>/dev/null)

    if [[ -z "$summary" ]]; then
        summary="${TRACEBACK_LINES[${#TRACEBACK_LINES[@]}-1]}"
    fi

    ERROR_SUMMARY="$summary"
    LAST_ERROR="$summary"
    return 0
}


cleanup() {
    if [[ $CLEANED_UP -eq 1 ]]; then return; fi
    CLEANED_UP=1

    echo_status

    # if [[ $TRACEBACK_MODE -eq 1 && ${#TRACEBACK_LINES[@]} -gt 0 ]]; then
    if [[ $TRACEBACK_MODE -eq 1 && ${#TRACEBACK_LINES[@]} -gt 0 ]] \
        && (( TRACEBACK_EPOCH > LAST_ALERT_EPOCH )); then
        ERROR_SUMMARY=$(printf "%s\n" "${TRACEBACK_LINES[@]}" \
            | grep -E "[A-Za-z]+Error:|Exception:" \
            | sed -E 's/with url: .*//' \
            | sed -E 's/^[^:]+: //' \
            | sort -u)

        [[ -z "$ERROR_SUMMARY" ]] && ERROR_SUMMARY="${TRACEBACK_LINES[-1]}"
        if [[ -n "$ERROR_SUMMARY" && "$ERROR_SUMMARY" != "$LAST_ALERT" ]]; then
                # send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$(get_timestamp)\`:\n\`\`\`$ERROR_SUMMARY\`\`\`"
                LAST_ALERT="$ERROR_SUMMARY"
        fi
    fi

    # Always clean up tail process if it exists    
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null || true 
        pkill -P "$TAIL_PID" 2>/dev/null || true
    fi
    pkill -u "$USER" -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true
    # If this cleanup was triggered by a restart, kill the old PID
    if [[ $RESTARTING -eq 1 && -n "$KILL_PID" ]]; then
        kill "$KILL_PID" 2>/dev/null
        MSG=":arrows_counterclockwise: *Watcher-$WORKSPACE script refresh* on \`$HOST\` at \`$(get_timestamp)\` (replacing PID \`$OLD_PID\`)"
        echo "[$(get_timestamp)] Watcher script restarted" | tee -a "$LOG_FILE"
        send_slack_notification "$MSG"
    # If this cleanup was triggered by a manual kill, kill the old PID and exit
    elif [[ $MANUAL_STOP -eq 1 ]]; then
        send_slack_notification ":x: *Watcher-$WORKSPACE manually stopped*  on \`$HOST\` at \`$(get_timestamp)\`"
        echo "[$(get_timestamp)] Watcher script terminated" | tee -a "$LOG_FILE"
        exit 0
    fi

    # Only send termination message if not restarting and no mismatch
    if [ "$RESTARTING" -eq 1 ] || [ "$MISMATCH" -eq 1 ] || [ "$HELP" -eq 1 ]; then
        :  # no-op, do nothing
    else
        EXIT_MESSAGE=":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$(get_timestamp)\`"
        if [[ -n "$LAST_ERROR" && "$LAST_ERROR" != "$LAST_ALERT" ]]; then
            EXIT_MESSAGE=":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$(get_timestamp)\`.\nLatest error:\n\`\`\`$LAST_ERROR\`\`\`"
        fi
        send_slack_notification "$EXIT_MESSAGE"
        echo "[$(get_timestamp)] Watcher script terminated" | tee -a "$LOG_FILE"
        echo_status
        exit 0
    fi
}

trap cleanup SIGINT SIGTERM EXIT

# process commands
if [[ "$COMMAND" == "stop" || "$COMMAND" == "status" ]]; then
    if ! check_host_match; then
        echo "Refusing to $COMMAND watcher from a different host."
        exit 1
    fi

    if [[ -f "$PID_FILE" ]]; then
        read -r OLD_PID < "$PID_FILE"
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            if [[ "$COMMAND" == "stop" ]]; then
                echo "Stopping watcher PID $OLD_PID..."
                MANUAL_STOP=1; RESTARTING=0; MISMATCH=0; HELP=0
                cleanup
            else
                echo "Watcher is running (PID $OLD_PID)"
            fi
        else
            echo "Watcher PID $OLD_PID not running"
        fi
    else
        [[ "$COMMAND" == "stop" ]] \
            && echo "No PID file found; watcher may not be running" \
            || echo "Watcher not running"
    fi
    exit 0
fi


# Kill existing process only if it's the correct watcher on this host
if ! check_host_match; then
    echo "Aborting startup due to host mismatch." | tee -a "$LOG_FILE"
    MISMATCH=1
    exit 1
fi

if [[ "$VIRTUAL_ENV" != "$PVENV" ]]; then
    echo "Incorrect poetry environment. Aborting." | tee -a "$LOG_FILE"
    MISMATCH=1
    exit 1
fi

# Look for an existing watcher process
if [[ -f "$PID_FILE" ]] && read -r OLD_PID < "$PID_FILE" && ps -p "$OLD_PID" > /dev/null 2>&1; then
    CMD_NAME=$(ps -p "$OLD_PID" -o comm=)
    # Check command name (comm) includes 'python'
    if [[ "$CMD_NAME" == *python* ]]; then
        PROC_CMD=$(ps -p "$OLD_PID" -o args=)
        # Check full command line includes 'watcher'
        if [[ "$PROC_CMD" == *"watcher"* ]] && [[ "$OLD_HOST" == "$HOST" ]]; then
            # This is the correct watcher process on the right host
            RESTARTING=1
            KILL_PID="$OLD_PID"
            cleanup
            # sleep 2
        else
            echo "Process command line does not match watcher or host mismatch."
            exit 1
        fi
    else
        echo "Process with PID $OLD_PID is not a python process."
        exit 1
    fi
else
    echo "No active process found for PID $OLD_PID"
fi


send_slack_notification ":rocket: *Watcher-$WORKSPACE started* on \`$HOST\` at \`$(get_timestamp)\`"
echo "[$(get_timestamp)] Watcher script started on $HOST" | tee -a "$LOG_FILE"

# Ensure no leftover tail processes are running for full log file
pkill -u "$USER" -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true

# Start monitoring the log file for errors in background
tail -n 0 -F "$LOG_FILE" | while IFS= read -r line; do
    if [[ "$line" == *"Traceback (most recent call last):"* ]]; then
        TRACEBACK_MODE=1
        TRACEBACK_LINES=()
        TRACEBACK_EPOCH=$(date +%s)
        continue
    fi

    if [[ $TRACEBACK_MODE -eq 1 ]]; then
        if [[ "$line" =~ ^\[.*\] ]] || [[ "$line" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
            TRACEBACK_MODE=0
        else
            TRACEBACK_LINES+=("$line")
            continue
        fi

        
        if [[ -n "$ERROR_SUMMARY" && "$ERROR_SUMMARY" != "$LAST_ALERT" ]]; then
            send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$(get_timestamp)\`:\n\`\`\`$ERROR_SUMMARY\`\`\`"
            LAST_ALERT="$ERROR_SUMMARY"
        fi
    fi

    # --- Single-line errors (outside traceback) ---
    if [[ $TRACEBACK_MODE -eq 0 ]]; then
        shopt -s nocasematch
        if [[ "$line" =~ (error|exception|[A-Za-z]+Error) ]]; then
            [[ "$line" =~ $IGNORE_PATTERN ]] && continue
            if [[ "$line" != "$LAST_ALERT" || "$line" == *"$ALERT_PATTERN"* ]]; then
                ALERT_EPOCH=$(date +%s)
                LAST_ERROR="$line"
                send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$(get_timestamp)\`:\n\`\`\`$line\`\`\`"
                LAST_ALERT="$line"
            fi
        fi
        shopt -u nocasematch
    fi
done &
TAIL_PID=$!

RESTARTING=0

# PYTHONPATH=$(pwd)/nmdc_automation \
#     python -m nmdc_automation.run_process.run_workflows watcher --config "$CONF" daemon \
#     > >(tee -a "$LOG_FILE") 2>&1 &

python watcher.py \
    > >(tee -a "$LOG_FILE") 2>&1 &

WATCHER_PID=$!
echo "$WATCHER_PID" > "$PID_FILE"
echo "$HOST" > "$HOST_FILE"
wait $WATCHER_PID
cleanup