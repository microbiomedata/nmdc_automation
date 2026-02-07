#!/bin/bash
set -euo pipefail

# Default values
WORKSPACE="prod"
LIST="/conf/allow.lst"
CONF="/conf/site_configuration.toml"
PID_FILE="/conf/sched-${WORKSPACE}.pid"
LOG_FILE="/conf/sched-${WORKSPACE}.log"
FULL_LOG_FILE="/conf/sched-${WORKSPACE}_full.log"
RESTART_FLAG="/tmp/scheduler_${WORKSPACE}_restarting"
KILL_FLAG="/tmp/scheduler_${WORKSPACE}_kill"
SKIP=""
PORT="27017"

SLACK_WEBHOOK_URL=$(grep 'slack_webhook' "$CONF" | sed 's/.*= *"\(.*\)"/\1/' || true)
YAML=$(grep 'workflows_config' "$CONF" | sed 's/.*= *"\(.*\)"/\1/' || true)

# Global state flags
DEBUG=0
DRYRUN=0
CLEANED_UP=0
RESTARTING=0
MISMATCH=0
HELP=0
MUTE=0
TEST=0
ACTUAL=0
LAST_ALERT_TIME=0
SCHED_PID=""
TAIL_PID=""
OLD_PID=""
KILL_PID=""
LAST_ALERT=""
LAST_ERROR=""
ALERT_PATTERN=""
IGNORE_PATTERN=""
COMMAND=""   # default start/restart scheduler when script called
TRACEBACK_LINES=()
ERROR_SUMMARY=""
SCHED_CMD=()

# Help message
show_help() {
  echo "Usage: $0 [COMMAND] [--allowlist PATH] [--yaml PATH] [--toml PATH] [OPTIONS]"
  echo
  echo "Commands:"
  echo "  stop                   Stop the running scheduler"
  echo "  status                 Show scheduler status"
  echo "  By default, if no command is called, scheduler will start"
  echo
  echo "Options:"
  echo "  -a, --allowlist PATH   Path to allowlist file     (default: $LIST)"
  echo "  -w, --workflows PATH   Path to workflow YAML file (default: $YAML)"
  echo "  -c, --config PATH      Path to site config CONF   (default: $CONF)"
  echo "  -p, --port PORT        MongoDB port number        (default: $PORT)"
  echo "  -s, --skiplist PATH    Path to skiplist file      (default: $SKIP)" 
  echo "  -i, --pidfile PATH     Path to PID file           (default: $PID_FILE)" 
  echo "  -l, --logfile PATH     Path to log file           (default: $LOG_FILE)" 
  echo "  -L, --logfull PATH     Path to full log file      (default: $FULL_LOG_FILE)" 
  echo "  -d, --debug            Enable debug mode          (increases logging)"
  echo "  -n, --dryrun           Enable dryrun mode         (nothing schedules)" 
  echo "  -m, --mute             Silence Slack notifs" 
  echo "  -t, --test             Run wrapper in test mode" 
  echo "  -ta, --actual          Run wrapper in test mode with sched code" 
  echo "  -h, --help             Show this help message"
  HELP=1
}

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        stop|status)    COMMAND="$1"; shift;;
        -a|--allowlist) LIST="$2"; shift 2 ;;
        -w|--workflows) YAML="$2"; shift 2 ;;
        -c|--conf)      CONF="$2"; shift 2 ;;
        -p|--port)      PORT="$2"; shift 2 ;;
        -s|--skiplist)  SKIP="$2"; shift 2 ;;
        -i|--pidfile)   PID_FILE="$2"; shift 2 ;;
        -l|--logfile)   LOG_FILE="$2"; shift 2 ;;
        -L|--logfull)   FULL_LOG_FILE="$2"; shift 2 ;;
        -d|--debug)     DEBUG=1; shift ;;
        -n|--dryrun)    DRYRUN=1; shift ;;
        -m|--mute)      MUTE=1; shift ;;
        -t|--test)      TEST=1; shift ;;
        -ta|--actual)   TEST=1; ACTUAL=1; shift ;;
        -h|--help)      show_help; exit 0 ;;
        *)              echo "Unknown option: $1"; show_help; exit 1 ;;
    esac
done

# process developer options

if [[ ${TEST:-0} -eq 1 ]]; then
    LIST="./allow.lst"
    CONF="./site_configuration.toml"
    PID_FILE="./test.sched.pid"
    LOG_FILE="./test.sched.log"
    FULL_LOG_FILE="./test.sched_full.log"
    YAML="../nmdc_automation/config/workflows/workflows.yaml"
    SLACK_WEBHOOK_URL=$(grep 'slack_webhook' "$CONF" | sed 's/.*= *"\(.*\)"/\1/' || true)
    SCHED_CMD=(python -u sched.py)
fi

# set env vars
export MONGO_PORT="$PORT"
export NMDC_WORKFLOW_YAML_FILE="$YAML"
export NMDC_SITE_CONF="$CONF"
export NMDC_LOG_LEVEL=INFO # info by default every time. 
export DRYRUN="$DRYRUN"
export SKIPLISTFILE="$SKIP"
export ALLOWLISTFILE="$LIST"

if [[ ${TEST:-0} -eq 0 || ${ACTUAL:-0} -eq 1 ]]; then
    SCHED_CMD=(python -u -m nmdc_automation.workflow_automation.sched \
            "$NMDC_SITE_CONF" "$NMDC_WORKFLOW_YAML_FILE")
fi

# ----------- Functions ----------- 
send_slack_notification() {
    if [[ "$MUTE" -eq 1 ]]; then
        return
    fi
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

get_timestamp() {
    TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y" 2>/dev/null || true
}

log() {
    if [ -n "$1" ]; then
        # Direct message
        printf '[%s] %s\n' "$(get_timestamp)" "$1" | tee -a "$LOG_FILE" "$FULL_LOG_FILE" #> "$STD_OUT"
    else
        # Read from stdin (for piped input)
        while IFS= read -r line; do
            printf '[%s] %s\n' "$(get_timestamp)" "$line" | tee -a "$LOG_FILE" "$FULL_LOG_FILE" #> "$STD_OUT"
        done
    fi
}

log_status() {
  log "CLEANED_UP RESTARTING MISMATCH KILL_PID DEBUG COMMAND DRYRUN HELP MUTE TEST ACTUAL" 
  log "$CLEANED_UP $RESTARTING $MISMATCH $KILL_PID $DEBUG $COMMAND $DRYRUN $HELP $MUTE $TEST $ACTUAL" 
}

kill_tails() {
    # Ensure no leftover tail processes are running for log file
    pkill -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true
}

cleanup() {
    # cleanup() may be invoked multiple times (signals, errors, exits). Ensures side effects only run once.
    if [[ $CLEANED_UP -eq 1 ]]; then 
        return
    fi
    CLEANED_UP=1

    # If this process is being replaced, exit quietly
    if [[ -f "$RESTART_FLAG" ]]; then
        log "Watcher exiting due to restart"
        rm -f "$RESTART_FLAG"
        exit 0
    fi

    # Manual stop is a hard termination with notification.
    if [[ -f "$KILL_FLAG" ]]; then
        rm -f "$KILL_FLAG"
        exit 0
    fi

    # HELP or MISMATCH intentionally terminate without Slack noise.
    if [[ ${HELP:-0} -eq 1 || ${MISMATCH:-0} -eq 1 ]]; then
        exit 0
    fi
    
    # Always clean up tail process if it exists    
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null || true 
        pkill -P "$TAIL_PID" 2>/dev/null || true
    fi
    kill_tails

    # NORMAL TERMINATION: Send termination notification, include last error if present.
    kill "$SCHED_PID" 2>/dev/null || true
    EXIT_MESSAGE=":x: *Scheduler-$WORKSPACE script terminated* at \`$(get_timestamp)\`"
    if [[ -n "${LAST_ERROR:-}" && "${LAST_ERROR:-}" != "${LAST_ALERT:-}" ]]; then
        EXIT_MESSAGE+="\nLatest error:\n\`\`\`${LAST_ERROR}\`\`\`"
    fi
    send_slack_notification "$EXIT_MESSAGE"
    log "Scheduler script terminated" 
    log_status
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# process commands
if [[ "${COMMAND}" == "stop" || "${COMMAND}" == "status" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        read -r OLD_PID < "$PID_FILE"
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            if [[ "$COMMAND" == "stop" ]]; then
                echo "Stopping scheduler PID $OLD_PID..."
                KILL_PID="$OLD_PID"; touch "$KILL_FLAG"
                send_slack_notification ":octagonal_sign: *Scheduler-$WORKSPACE manually stopped* at \`$(get_timestamp)\`"
                log "Scheduler script manually terminated"
                kill "$KILL_PID" 2>/dev/null 
                kill_tails
            else
                echo "Scheduler is running (PID $OLD_PID)"
                ps ax -o pid,user,etime,command | awk 'NR==1 || (/sched/ && !/(awk|status)/)' || echo "Cannot check ps"
            fi
        else
            echo "Scheduler PID $OLD_PID not running"
        fi
    else
        [[ "$COMMAND" == "stop" ]] \
            && echo "No PID file found; scheduler may not be running" \
            || echo "Scheduler not running"
    fi
    HELP=1
    exit 0
fi

rm "$LOG_FILE" || true

if [[ ${DEBUG:-0} -eq 1 ]]; then
    export NMDC_LOG_LEVEL=DEBUG
    log "Debug mode enabled."
fi

# Look for existing scheduler process
if [[ -f "$PID_FILE" ]] && read -r OLD_PID < "$PID_FILE" && ps -p "$OLD_PID" > /dev/null 2>&1; then
    # check for PID process
    COMMAND_NAME=$(ps -p "$OLD_PID" -o comm=)
    PROC_COMMAND=$(ps -p "$OLD_PID" -o args=)
    # check command name and command process include python and sched
    if [[ "$COMMAND_NAME" == *python* && "$PROC_COMMAND" == *sched* ]]; then
        log "Found running scheduler process $OLD_PID: $COMMAND_NAME"
        RESTARTING=1
        touch "$RESTART_FLAG"
        send_slack_notification ":arrows_counterclockwise: *Scheduler-$WORKSPACE script refresh* at \`$(get_timestamp)\` (replacing PID \`$OLD_PID\`)"
        KILL_PID="$OLD_PID"
        kill "$KILL_PID" 2>/dev/null || true
    else
        log "PID $OLD_PID is not the scheduler, skipping kill"
        MISMATCH=1
        exit 1
    fi
else
    log "PID $OLD_PID not running"
fi

# Look for orphaned scheduler processes outside of PID file
if EXISTING_PID=$(pgrep -f "python.*sched" 2>/dev/null); then
    for PID in $EXISTING_PID; do
        [[ "$PID" == "$OLD_PID" ]] && continue
        PROC_COMMAND=$(ps -p "$PID" -o args= 2>/dev/null || echo "(unknown)")
        log "Removing scheduler process without PID file: $PID ($PROC_COMMAND)"
        kill "$PID" 2>/dev/null || true
    done
fi
kill_tails

# Start monitoring the log file for errors in background
tail -n 0 -F "$LOG_FILE" | while IFS= read -r line; do
    # skip known patterns
    [[ -n "$IGNORE_PATTERN" && "$line" =~ $IGNORE_PATTERN ]] && continue
    
    # begin python traceback
    if [[ "$line" == *"Traceback (most recent call last):"* ]]; then
        TRACEBACK_LINES=("$line")
        TRACEBACK_ACTIVE=1
        continue
    fi
    if [[ ${TRACEBACK_ACTIVE:-0} -eq 1 ]]; then
        TRACEBACK_LINES+=("$line")

        # End traceback and send on "final exception line"
        if [[ "$line" =~ [A-Za-z]+Error:|Exception: ]]; then
            ERROR_SUMMARY=$(printf "%s\n" "${TRACEBACK_LINES[@]}" \
                | grep -E "[A-Za-z]+Error:|Exception:" \
                | tail -n1 \
                | sed -E 's/with url: .*//' \
                | sed -E 's/^[^:]+: //' )
            ERROR_SUMMARY=${ERROR_SUMMARY:-"Unknown error"}
            LAST_ERROR="$ERROR_SUMMARY"

            if [[ -n "$ERROR_SUMMARY" && "$ERROR_SUMMARY" != "$LAST_ALERT" ]]; then
                send_slack_notification ":warning: *Scheduler-$WORKSPACE ERROR* at \`$(get_timestamp)\`:\n\`\`\`$ERROR_SUMMARY\`\`\`"
                LAST_ALERT="$ERROR_SUMMARY"
            fi
            # Reset traceback detection
            TRACEBACK_LINES=()
            TRACEBACK_ACTIVE=0
        fi
        continue
    fi

    # single line error detection
    shopt -s nocasematch
    if [[ "$line" =~ (error|exception) ]]; then
        # remove timestamp
        LAST_ERROR=$(awk '{sub(/^[0-9-]+ [0-9:,]+ /, ""); print}' <<< "$line")
        # send repeat errors only after 1 hour
        now=$(date +%s)
        resend_after=$((60 * 60))  # 1 hour
        if [[ "$LAST_ERROR" != "$LAST_ALERT" ]] || \
            [[ -n "$ALERT_PATTERN" && "$LAST_ERROR" == *"$ALERT_PATTERN"* ]] || \
            [[ "$LAST_ERROR" == "$LAST_ALERT" && $((now - LAST_ALERT_TIME)) -ge $resend_after ]]; then
            send_slack_notification ":warning: *Scheduler-$WORKSPACE ERROR* at \`$(get_timestamp)\`:\n\`\`\`$LAST_ERROR\`\`\`"
            LAST_ALERT="$LAST_ERROR"
            LAST_ALERT_TIME="$now"
        fi
    fi
    shopt -u nocasematch
done &
TAIL_PID=$!

if [[ ${RESTARTING:-0} -eq 0 ]]; then 
    send_slack_notification ":rocket: *Scheduler-$WORKSPACE started* at \`$(get_timestamp)\`"
fi

RESTARTING=0
CLEANED_UP=0

if [[ ${TEST:-0} -eq 0 ]]; then
    cd /src # needed for docker/spin env
fi

log "Scheduler script started" 
log_status

"${SCHED_CMD[@]}" \
    > >(tee -a "$LOG_FILE" "$FULL_LOG_FILE") 2>&1 &

SCHED_PID=$!
echo "$SCHED_PID" > "$PID_FILE"
wait "$SCHED_PID"
cleanup
