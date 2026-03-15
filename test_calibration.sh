#!/bin/bash
# Standalone calibration test — binary search for thread count that produces target CPU%
# Usage: bash test_calibration.sh <emulator_ip> <loadgen_ip>
# Example: bash test_calibration.sh 10.0.0.92 10.0.0.83

set -e

EMULATOR_HOST="${1:-10.0.0.92}"
LOADGEN_HOST="${2:-10.0.0.83}"
EMULATOR_PORT=8080
SSH_OPTS="-o StrictHostKeyChecking=no"

# Calibration parameters (match orchestrator config)
TARGET_CPU_MIN=15
TARGET_CPU_MAX=50
MIN_THREADS=1
MAX_THREADS=30
OBSERVATION_SEC=30
RAMP_UP_SEC=5
STABILITY_DURATION_SEC=60
STABILITY_MIN_IN_RANGE_PCT=55

echo "============================================"
echo "Calibration Test"
echo "Target: $EMULATOR_HOST:$EMULATOR_PORT"
echo "Loadgen: $LOADGEN_HOST"
echo "CPU target: ${TARGET_CPU_MIN}-${TARGET_CPU_MAX}%"
echo "Thread range: ${MIN_THREADS}-${MAX_THREADS}"
echo "============================================"
echo ""

# Step 1: Verify emulator is up (restart manually if needed)
echo "--- Checking emulator ---"
HEALTH=$(curl -s --connect-timeout 5 http://$EMULATOR_HOST:$EMULATOR_PORT/health)
if [ -z "$HEALTH" ]; then
    echo "Emulator not reachable. Trying SSH restart (Linux only)..."
    ssh $SSH_OPTS root@$EMULATOR_HOST 'ps -eo pid,args | grep uvicorn | grep -v grep | while read pid rest; do kill $pid 2>/dev/null; done' 2>/dev/null
    sleep 3
    ssh $SSH_OPTS -f root@$EMULATOR_HOST 'cd /opt/emulator && nohup python3 -m uvicorn app.main:create_app --host 0.0.0.0 --port 8080 --factory > /tmp/emulator.log 2>&1 &' 2>/dev/null
    sleep 5
    HEALTH=$(curl -s --connect-timeout 5 http://$EMULATOR_HOST:$EMULATOR_PORT/health)
fi
echo "Emulator: $HEALTH"
if [ -z "$HEALTH" ]; then
    echo "ERROR: Emulator not reachable. Start it manually."
    exit 1
fi
echo ""

# Function: run one observation and return avg CPU
run_observation() {
    local THREADS=$1
    local DURATION=$2
    local RAMP=$3
    local TAG=$4

    # Start stats
    RESP=$(curl -s http://$EMULATOR_HOST:$EMULATOR_PORT/api/v1/tests/start \
      -X POST -H "Content-Type: application/json" \
      -d "{
        \"test_run_id\": \"cal_${TAG}\",
        \"scenario_id\": \"calibration\",
        \"mode\": \"calibration\",
        \"collect_interval_sec\": 1.0,
        \"thread_count\": 1
      }")
    TEST_ID=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['test_id'])")

    # Prime stats (first /proc/stat read)
    sleep 2

    # Start JMeter
    ssh $SSH_OPTS -f root@$LOADGEN_HOST "nohup /opt/jmeter/bin/jmeter -n \
      -t /tmp/test_normal.jmx \
      -l /tmp/cal_${TAG}.jtl \
      -j /tmp/cal_${TAG}.log \
      -Jthreads=$THREADS \
      -Jrampup=$RAMP \
      -Jduration=$DURATION \
      -Jhost=$EMULATOR_HOST \
      -Jport=$EMULATOR_PORT \
      -Jops_sequence=/tmp/ops_sequence_test.csv \
      > /tmp/cal_${TAG}_stdout.log 2>&1 &"

    # Wait for ramp + observation + buffer
    sleep $((RAMP + DURATION + 5))

    # Stop stats
    curl -s http://$EMULATOR_HOST:$EMULATOR_PORT/api/v1/tests/$TEST_ID/stop \
      -X POST -H "Content-Type: application/json" -d '{}' > /dev/null

    # Get stats and compute avg CPU (skip first 5s of ramp and last 3s)
    curl -s "http://$EMULATOR_HOST:$EMULATOR_PORT/api/v1/stats/recent?count=500" | python -c "
import sys, json
data = json.load(sys.stdin)
samples = data['samples']
# Skip ramp-up samples (first ${RAMP}+2 seconds) and tail idle samples
active = [s for s in samples if s['elapsed_sec'] >= $((RAMP + 2)) and s['cpu_percent'] > 0.5]
all_during_load = [s for s in samples if s['elapsed_sec'] >= $((RAMP + 2)) and s['elapsed_sec'] <= $((RAMP + DURATION + 2))]

if not all_during_load:
    print('AVG_CPU=0.0')
    print('IN_RANGE_PCT=0.0')
    print('DETAIL=no samples')
    sys.exit(0)

cpus = [s['cpu_percent'] for s in all_during_load]
avg = sum(cpus) / len(cpus)
in_range = sum(1 for c in cpus if $TARGET_CPU_MIN <= c <= $TARGET_CPU_MAX)
pct_in_range = (in_range / len(cpus)) * 100

print(f'AVG_CPU={avg:.1f}')
print(f'IN_RANGE_PCT={pct_in_range:.1f}')
print(f'DETAIL=samples={len(cpus)} min={min(cpus):.1f} max={max(cpus):.1f} avg={avg:.1f} in_range={in_range}/{len(cpus)} ({pct_in_range:.0f}%)')
" 2>/dev/null
}

# Step 2: Binary search
echo "=== Binary Search Phase ==="
LOW=$MIN_THREADS
HIGH=$MAX_THREADS
BEST_THREADS=0
ITERATION=0

while [ $LOW -le $HIGH ]; do
    ITERATION=$((ITERATION + 1))
    MID=$(( (LOW + HIGH) / 2 ))

    echo ""
    echo "--- Iteration $ITERATION: threads=$MID (range $LOW-$HIGH) ---"

    RESULT=$(run_observation $MID $OBSERVATION_SEC $RAMP_UP_SEC "bs_${ITERATION}")
    AVG_CPU=$(echo "$RESULT" | grep AVG_CPU | cut -d= -f2)
    IN_RANGE=$(echo "$RESULT" | grep IN_RANGE_PCT | cut -d= -f2)
    DETAIL=$(echo "$RESULT" | grep DETAIL | cut -d= -f2-)

    echo "  Result: $DETAIL"

    # Compare avg CPU to target range
    BELOW=$(python -c "print('yes' if $AVG_CPU < $TARGET_CPU_MIN else 'no')")
    ABOVE=$(python -c "print('yes' if $AVG_CPU > $TARGET_CPU_MAX else 'no')")

    if [ "$BELOW" = "yes" ]; then
        echo "  -> avg CPU ${AVG_CPU}% < ${TARGET_CPU_MIN}% minimum, increasing threads"
        LOW=$((MID + 1))
    elif [ "$ABOVE" = "yes" ]; then
        echo "  -> avg CPU ${AVG_CPU}% > ${TARGET_CPU_MAX}% maximum, decreasing threads"
        HIGH=$((MID - 1))
    else
        echo "  -> avg CPU ${AVG_CPU}% is IN RANGE [${TARGET_CPU_MIN}-${TARGET_CPU_MAX}%]!"
        BEST_THREADS=$MID
        break
    fi

    # Safety: max 8 iterations
    if [ $ITERATION -ge 8 ]; then
        echo "  Max iterations reached"
        BEST_THREADS=$MID
        break
    fi
done

echo ""
echo "============================================"
echo "Binary search result: $BEST_THREADS threads -> ${AVG_CPU}% avg CPU"
echo "============================================"

if [ $BEST_THREADS -eq 0 ]; then
    echo "FAILED: Could not find thread count in target range"
    exit 1
fi

# Step 3: Stability check
echo ""
echo "=== Stability Check: $BEST_THREADS threads for ${STABILITY_DURATION_SEC}s ==="
RESULT=$(run_observation $BEST_THREADS $STABILITY_DURATION_SEC $RAMP_UP_SEC "stability")
AVG_CPU=$(echo "$RESULT" | grep AVG_CPU | cut -d= -f2)
IN_RANGE=$(echo "$RESULT" | grep IN_RANGE_PCT | cut -d= -f2)
DETAIL=$(echo "$RESULT" | grep DETAIL | cut -d= -f2-)

echo "  Result: $DETAIL"

PASSED=$(python -c "print('PASS' if float('$IN_RANGE') >= $STABILITY_MIN_IN_RANGE_PCT else 'FAIL')")
echo ""
echo "============================================"
echo "Stability: $PASSED (${IN_RANGE}% in range, need ${STABILITY_MIN_IN_RANGE_PCT}%)"
echo "Calibration result: $BEST_THREADS threads = ${AVG_CPU}% avg CPU"
echo "============================================"
