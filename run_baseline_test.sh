#!/bin/bash
# End-to-end baseline test runner
# Usage:
#   bash run_baseline_test.sh new_baseline              # create fresh baseline
#   bash run_baseline_test.sh compare                   # compare same snapshots (Option A)
#   bash run_baseline_test.sh compare_with_new_calibration  # compare with recalibration (Option B)
#   bash run_baseline_test.sh all                       # run new_baseline, then compare, then compare_with_new_calibration
#
# Options:
#   --no-restart     Don't restart orchestrator
#   --poll-sec N     Poll interval (default 30)

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
ORCH_DIR="$(cd "$(dirname "$0")/orchestrator" && pwd)"
ORCH_URL="http://localhost:8000"
LOG_FILE="/tmp/orchestrator.log"
POLL_SEC=30
RESTART=true
SCENARIO_ID=3
LOAD_PROFILE_IDS="[1]"

# Targets: test_snapshot_id = baseline snapshot, compare_snapshot_id = same snapshot (self-compare)
# For a real test, compare_snapshot_id would be a snapshot with an agent installed
ROCKY_SERVER_ID=8
ROCKY_TEST_SNAPSHOT=3
ROCKY_COMPARE_SNAPSHOT=3

WIN_SERVER_ID=9
WIN_TEST_SNAPSHOT=4
WIN_COMPARE_SNAPSHOT=4

# ── Parse args ─────────────────────────────────────────────────
TEST_MODE=""
while [ $# -gt 0 ]; do
    case $1 in
        new_baseline|compare|compare_with_new_calibration|all)
            TEST_MODE=$1; shift ;;
        --no-restart)   RESTART=false; shift ;;
        --poll-sec)     POLL_SEC=$2; shift 2 ;;
        --poll-sec=*)   POLL_SEC="${1#*=}"; shift ;;
        *)              echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [ -z "$TEST_MODE" ]; then
    echo "Usage: bash $0 <new_baseline|compare|compare_with_new_calibration|all> [options]"
    exit 1
fi

# ── Helpers ────────────────────────────────────────────────────
timestamp() { date '+%H:%M:%S'; }

get_token() {
    curl -s "$ORCH_URL/api/auth/login" -X POST \
        -d "username=admin&password=admin" \
        | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
}

get_run_state() {
    local token=$1 run_id=$2
    curl -s "$ORCH_URL/api/baseline-tests/$run_id" \
        -H "Authorization: Bearer $token"
}

LOG_LINES_SEEN=0
check_new_logs() {
    local total_lines
    total_lines=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$total_lines" -gt "$LOG_LINES_SEEN" ]; then
        local new_count=$((total_lines - LOG_LINES_SEEN))
        tail -n "$new_count" "$LOG_FILE" \
            | grep -v "HTTP/1.1" \
            | grep -iv "^INFO:" \
            | while IFS= read -r line; do
                echo "  [log] $line"
            done || true
        LOG_LINES_SEEN=$total_lines
    fi
}

build_targets_json() {
    local test_type=$1
    if [ "$test_type" = "new_baseline" ]; then
        echo "[
          {\"server_id\": $ROCKY_SERVER_ID, \"test_snapshot_id\": $ROCKY_TEST_SNAPSHOT},
          {\"server_id\": $WIN_SERVER_ID, \"test_snapshot_id\": $WIN_TEST_SNAPSHOT}
        ]"
    else
        echo "[
          {\"server_id\": $ROCKY_SERVER_ID, \"test_snapshot_id\": $ROCKY_TEST_SNAPSHOT, \"compare_snapshot_id\": $ROCKY_COMPARE_SNAPSHOT},
          {\"server_id\": $WIN_SERVER_ID, \"test_snapshot_id\": $WIN_TEST_SNAPSHOT, \"compare_snapshot_id\": $WIN_COMPARE_SNAPSHOT}
        ]"
    fi
}

# ── restart_orchestrator ───────────────────────────────────────
restart_orchestrator() {
    if [ "$RESTART" = true ]; then
        echo "$(timestamp) ── Restarting orchestrator ──"
        PIDS=$(tasklist 2>/dev/null | grep -i "python" | awk '{print $2}' || true)
        if [ -n "$PIDS" ]; then
            for pid in $PIDS; do
                cmd //c "taskkill /PID $pid /F" 2>/dev/null || true
            done
            sleep 2
        fi
        cd "$ORCH_DIR"
        python -m uvicorn orchestrator.app:create_app \
            --host 0.0.0.0 --port 8000 --factory \
            > "$LOG_FILE" 2>&1 &
        echo "  PID: $!"
        for i in $(seq 1 15); do
            HEALTH=$(curl -s "$ORCH_URL/health" 2>/dev/null || true)
            if echo "$HEALTH" | grep -q '"ok"'; then
                echo "  Health: OK"
                break
            fi
            if [ "$i" -eq 15 ]; then
                echo "  ERROR: Orchestrator did not start within 15s"
                exit 1
            fi
            sleep 1
        done
    else
        echo "$(timestamp) ── Skipping restart (--no-restart) ──"
        HEALTH=$(curl -s "$ORCH_URL/health" 2>/dev/null || true)
        if ! echo "$HEALTH" | grep -q '"ok"'; then
            echo "  ERROR: Orchestrator not running"
            exit 1
        fi
        echo "  Health: OK"
    fi
    LOG_LINES_SEEN=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
}

# ── run_one_test ───────────────────────────────────────────────
run_one_test() {
    local test_type=$1
    local targets
    targets=$(build_targets_json "$test_type")

    echo ""
    echo "========================================================"
    echo "  TEST: $test_type"
    echo "========================================================"

    # Create
    echo ""
    echo "$(timestamp) ── Creating $test_type test run ──"
    TOKEN=$(get_token)
    CREATE_RESP=$(curl -s "$ORCH_URL/api/baseline-tests" -X POST \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d "{
            \"scenario_id\": $SCENARIO_ID,
            \"test_type\": \"$test_type\",
            \"load_profile_ids\": $LOAD_PROFILE_IDS,
            \"targets\": $targets
        }")

    RUN_ID=$(echo "$CREATE_RESP" | python -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)
    if [ -z "$RUN_ID" ]; then
        echo "  ERROR: Failed to create test run"
        echo "  Response: $CREATE_RESP"
        return 1
    fi
    echo "  Run ID: $RUN_ID"

    # Start
    echo ""
    echo "$(timestamp) ── Starting run $RUN_ID ──"
    START_RESP=$(curl -s "$ORCH_URL/api/baseline-tests/$RUN_ID/start" -X POST \
        -H "Authorization: Bearer $TOKEN")
    echo "  $START_RESP"

    # Poll
    echo ""
    echo "$(timestamp) ── Monitoring (poll every ${POLL_SEC}s) ──"
    echo ""

    local PREV_STATE=""
    local START_TIME
    START_TIME=$(date +%s)

    while true; do
        sleep "$POLL_SEC"
        TOKEN=$(get_token 2>/dev/null || echo "$TOKEN")
        RUN_JSON=$(get_run_state "$TOKEN" "$RUN_ID" 2>/dev/null || echo "{}")

        STATE=$(echo "$RUN_JSON" | python -c "import sys,json; print(json.load(sys.stdin).get('state','unknown'))" 2>/dev/null || echo "unknown")
        ERROR=$(echo "$RUN_JSON" | python -c "import sys,json; print(json.load(sys.stdin).get('error_message') or '')" 2>/dev/null || echo "")
        LOAD_PROFILE=$(echo "$RUN_JSON" | python -c "import sys,json; print(json.load(sys.stdin).get('current_load_profile_id') or '-')" 2>/dev/null || echo "-")

        local ELAPSED=$(( $(date +%s) - START_TIME ))
        local ELAPSED_MIN=$((ELAPSED / 60))
        local ELAPSED_SEC=$((ELAPSED % 60))

        if [ "$STATE" != "$PREV_STATE" ]; then
            echo "$(timestamp) [${ELAPSED_MIN}m${ELAPSED_SEC}s] STATE: $PREV_STATE -> $STATE  (load_profile=$LOAD_PROFILE)"
            PREV_STATE="$STATE"
        else
            echo "$(timestamp) [${ELAPSED_MIN}m${ELAPSED_SEC}s] state=$STATE  load_profile=$LOAD_PROFILE"
        fi

        check_new_logs

        if [ -n "$ERROR" ]; then
            echo "  !! ERROR: $ERROR"
        fi

        if [ "$STATE" = "completed" ] || [ "$STATE" = "failed" ]; then
            VERDICT=$(echo "$RUN_JSON" | python -c "import sys,json; print(json.load(sys.stdin).get('verdict') or 'N/A')" 2>/dev/null || echo "N/A")
            COMPLETED=$(echo "$RUN_JSON" | python -c "import sys,json; print(json.load(sys.stdin).get('completed_at') or 'N/A')" 2>/dev/null || echo "N/A")
            echo ""
            echo "----------------------------------------------------"
            echo "  Run $RUN_ID ($test_type): $STATE"
            echo "  Duration: ${ELAPSED_MIN}m ${ELAPSED_SEC}s"
            echo "  Verdict: $VERDICT"
            echo "  Completed: $COMPLETED"
            if [ -n "$ERROR" ]; then
                echo "  Error: $ERROR"
            fi
            echo "----------------------------------------------------"

            echo ""
            echo "── Last 20 log lines ──"
            tail -20 "$LOG_FILE" | grep -v "HTTP/1.1" || true

            if [ "$STATE" = "failed" ]; then
                return 1
            fi
            return 0
        fi
    done
}

# ── Main ───────────────────────────────────────────────────────
restart_orchestrator

OVERALL_START=$(date +%s)
RESULTS=""

if [ "$TEST_MODE" = "all" ]; then
    TEST_TYPES="new_baseline compare compare_with_new_calibration"
else
    TEST_TYPES="$TEST_MODE"
fi

PASS_COUNT=0
FAIL_COUNT=0

for tt in $TEST_TYPES; do
    if run_one_test "$tt"; then
        RESULTS="${RESULTS}\n  $tt: PASSED"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        RESULTS="${RESULTS}\n  $tt: FAILED"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        # For 'all' mode: stop on first failure
        if [ "$TEST_MODE" = "all" ]; then
            echo ""
            echo "!! Stopping — $tt failed. Fix before running remaining tests."
            break
        fi
    fi
    # Don't restart between tests in 'all' mode
    RESTART=false
done

OVERALL_ELAPSED=$(( $(date +%s) - OVERALL_START ))
OVERALL_MIN=$((OVERALL_ELAPSED / 60))
OVERALL_SEC=$((OVERALL_ELAPSED % 60))

echo ""
echo "========================================================"
echo "  SUMMARY"
echo "  Total time: ${OVERALL_MIN}m ${OVERALL_SEC}s"
echo "  Passed: $PASS_COUNT  Failed: $FAIL_COUNT"
echo -e "$RESULTS"
echo "========================================================"

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
