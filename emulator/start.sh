#!/bin/bash
# Start the emulator service in background.
# Creates required directories and starts uvicorn.
# Idempotent — kills existing emulator process if running.
set -e

EMULATOR_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$EMULATOR_DIR"

# Create output and stats directories
mkdir -p /opt/emulator/output
mkdir -p /opt/emulator/stats

# Open firewall port 8080 (idempotent — no-op if already open)
if command -v ufw &>/dev/null; then
    ufw allow 8080/tcp >/dev/null 2>&1 || true
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent --add-port=8080/tcp >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
fi

# Kill existing emulator if running — use fuser to kill by port (catches forked workers)
fuser -k 8080/tcp 2>/dev/null || true
pkill -9 -f "uvicorn app.main" 2>/dev/null || true
sleep 2

# Start emulator in background
nohup python3 -m uvicorn app.main:create_app --host 0.0.0.0 --port 8080 --factory \
    > /opt/emulator/emulator.log 2>&1 &

# Wait for startup
for i in $(seq 1 10); do
    if curl -sf --max-time 3 http://localhost:8080/health > /dev/null 2>&1; then
        echo "Emulator started successfully (pid=$!)"
        exit 0
    fi
    sleep 1
done

echo "ERROR: Emulator failed to start within 10s"
cat /opt/emulator/emulator.log
exit 1
