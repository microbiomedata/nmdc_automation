#!/bin/bash
set -euo pipefail
# Default values
WORKSPACE="dev"
HOST=$(hostname)
CONF=/path/to/nmdc_automation/$WORKSPACE/site_configuration_nersc.toml
LOG_FILE=watcher-$WORKSPACE.log
PID_FILE=watcher-$WORKSPACE.pid
HOST_FILE=host-$WORKSPACE.last
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXX"
ERROR_ALERTED_FILE="watcher_error_alerted_$WORKSPACE"

CLEANED_UP=0
RESTARTING=0

send_slack_notification() {
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

cleanup() {
    if [[ $CLEANED_UP -eq 1 ]]; then return; fi
    CLEANED_UP=1
    if [[ $RESTARTING -eq 0 ]]; then
        END_TIME=$(date)
        send_slack_notification ":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$END_TIME\`"
        echo "[$END_TIME] Watcher script terminated" | tee -a "$LOG_FILE"
    fi
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Kill existing process only if it's the correct watcher on this host
OLD_PID=""
OLD_HOST=""
[[ -f "$PID_FILE" ]] && OLD_PID=$(cat "$PID_FILE")
[[ -f "$HOST_FILE" ]] && OLD_HOST=$(cat "$HOST_FILE")

if [[ -n "$OLD_HOST" && "$OLD_HOST" != "$HOST" ]]; then
    echo "Host mismatch: existing watcher was on '$OLD_HOST', current host is '$HOST'. Aborting."
    exit 1
fi

# Look for an existing watcher process
if [[ -n "$OLD_PID" ]] && ps -p "$OLD_PID" > /dev/null 2>&1; then
    # Check command name (comm) includes 'python'
    CMD_NAME=$(ps -p "$OLD_PID" -o comm=)
    if [[ "$CMD_NAME" == *python* ]]; then
        # Check full command line includes 'watcher'
        PROC_CMD=$(ps -p "$OLD_PID" -o args=)
        if [[ "$PROC_CMD" == *"run_workflows watcher"* ]] && [[ "$OLD_HOST" == "$HOST" ]]; then
            # This is the correct watcher process on the right host
            RESTARTING=1
            TIMESTAMP=$(date)
            MSG=":arrows_counterclockwise: *Watcher-$WORKSPACE script refresh* on \`$HOST\` at \`$TIMESTAMP\` (replacing PID \`$OLD_PID\`)"
            echo "$MSG" | tee -a "$LOG_FILE"
            send_slack_notification "$MSG"

            kill "$OLD_PID"
            sleep 2
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


START_TIME=$(date)
send_slack_notification ":rocket: *Watcher-$WORKSPACE started* on \`$HOST\` at \`$START_TIME\`"
echo "[$START_TIME] Watcher script started on $HOST" | tee -a "$LOG_FILE"


# Start monitoring the log file for errors in background
rm -f "$ERROR_ALERTED_FILE"
tail -F "$LOG_FILE" | grep --line-buffered 'ERROR' | while read -r line; do
    if [[ ! -f "$ERROR_ALERTED_FILE" ]]; then
        TIMESTAMP=$(date)
        send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$TIMESTAMP\`:\n\`\`\`$line\`\`\`"
        touch "$ERROR_ALERTED_FILE"
    fi
done &
TAIL_PID=$!

PYTHONPATH=$(pwd)/nmdc_automation \
    python -m nmdc_automation.run_process.run_workflows watcher --config "$CONF" daemon \
    > >(tee -a "$LOG_FILE") 2>&1 &

WATCHER_PID=$!
echo "$WATCHER_PID" > "$PID_FILE"
echo "$HOST" > "$HOST_FILE"
wait $WATCHER_PID