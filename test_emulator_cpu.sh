#!/bin/bash
# End-to-end test: restart emulator, run JMeter, collect CPU stats
# Usage: bash test_emulator_cpu.sh

set -e

EMULATOR_HOST="10.0.0.92"
LOADGEN_HOST="10.0.0.83"
EMULATOR_PORT=8080
SSH_OPTS="-o StrictHostKeyChecking=no"
THREADS=10
RAMPUP=5
DURATION=20

echo "=== Step 1: Kill emulator ==="
ssh $SSH_OPTS root@$EMULATOR_HOST 'ps -eo pid,args | grep uvicorn | grep -v grep | while read pid rest; do kill $pid 2>/dev/null; done'
sleep 3

echo "=== Step 2: Start emulator ==="
ssh $SSH_OPTS -f root@$EMULATOR_HOST 'cd /opt/emulator && nohup python3 -m uvicorn app.main:create_app --host 0.0.0.0 --port 8080 --factory > /tmp/emulator.log 2>&1 &'
sleep 5

# Verify emulator is up
HEALTH=$(curl -s http://$EMULATOR_HOST:$EMULATOR_PORT/health)
echo "Health: $HEALTH"
UPTIME=$(echo "$HEALTH" | python -c "import sys,json; print(json.load(sys.stdin)['uptime_sec'])" 2>/dev/null)
echo "Uptime: ${UPTIME}s"
if (( $(echo "$UPTIME > 30" | bc -l 2>/dev/null || echo 0) )); then
    echo "ERROR: Emulator did not restart (uptime too high). Exiting."
    exit 1
fi

echo ""
echo "=== Step 3: Start stats collection ==="
RESP=$(curl -s http://$EMULATOR_HOST:$EMULATOR_PORT/api/v1/tests/start \
  -X POST -H "Content-Type: application/json" \
  -d "{
    \"test_run_id\": \"cpu_test\",
    \"scenario_id\": \"manual\",
    \"mode\": \"calibration\",
    \"collect_interval_sec\": 1.0,
    \"thread_count\": 1
  }")
TEST_ID=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['test_id'])")
echo "Test ID: $TEST_ID"

# Wait 3 seconds for stats to prime (first /proc/stat reading is baseline)
sleep 3

echo ""
echo "=== Step 4: Start JMeter ($THREADS threads, ${DURATION}s) ==="
ssh $SSH_OPTS -f root@$LOADGEN_HOST "nohup /opt/jmeter/bin/jmeter -n \
  -t /tmp/test_normal.jmx \
  -l /tmp/cpu_test.jtl \
  -j /tmp/cpu_test.log \
  -Jthreads=$THREADS \
  -Jrampup=$RAMPUP \
  -Jduration=$DURATION \
  -Jhost=$EMULATOR_HOST \
  -Jport=$EMULATOR_PORT \
  -Jops_sequence=/tmp/ops_sequence_test.csv \
  > /tmp/cpu_test_stdout.log 2>&1 &"

echo "JMeter started. Waiting for completion..."

# Wait for ramp + duration + buffer
TOTAL_WAIT=$((RAMPUP + DURATION + 10))
sleep $TOTAL_WAIT

echo ""
echo "=== Step 5: JMeter results ==="
ssh $SSH_OPTS root@$LOADGEN_HOST "tail -5 /tmp/cpu_test_stdout.log"

echo ""
echo "=== Step 6: Stop stats collection ==="
curl -s http://$EMULATOR_HOST:$EMULATOR_PORT/api/v1/tests/$TEST_ID/stop \
  -X POST -H "Content-Type: application/json" -d '{}' > /dev/null

echo ""
echo "=== Step 7: CPU stats (ALL samples) ==="
curl -s "http://$EMULATOR_HOST:$EMULATOR_PORT/api/v1/stats/recent?count=500" | python -c "
import sys, json
data = json.load(sys.stdin)
samples = data['samples']
print(f'Total samples: {len(samples)}')
print()
print(f'{\"t(s)\":>6}  {\"CPU%\":>6}  {\"MEM%\":>6}  {\"DiskW\":>8}  {\"NetR\":>8}')
print('-' * 42)
for s in samples:
    print(f'{s[\"elapsed_sec\"]:6.1f}  {s[\"cpu_percent\"]:6.1f}  {s[\"memory_percent\"]:6.1f}  {s[\"disk_write_rate_mbps\"]:8.3f}  {s[\"network_recv_rate_mbps\"]:8.3f}')

# Summary
cpus = [s['cpu_percent'] for s in samples]
print()
print(f'CPU Summary: min={min(cpus):.1f}% max={max(cpus):.1f}% avg={sum(cpus)/len(cpus):.1f}%')
non_zero = [c for c in cpus if c > 1.0]
print(f'Samples with CPU > 1%: {len(non_zero)} out of {len(cpus)}')
"

echo ""
echo "=== Done ==="
