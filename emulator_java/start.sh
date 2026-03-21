#!/bin/bash
# Java Emulator startup script for Linux
#
# Usage:
#   bash start.sh           # Auto-calculate heap (RAM - 2GB) — for targets
#   bash start.sh 512       # Use 512 MB heap — for loadgens
#   bash start.sh 0         # No -Xmx flag (JVM default) — fallback

EMULATOR_DIR="/opt/emulator"
LOG_DIR="${HOME}"
LOG_FILE="${LOG_DIR}/emulator.log"

cd "$EMULATOR_DIR" || { echo "ERROR: $EMULATOR_DIR not found"; exit 1; }

# Create required directories (output/stats on /data if mounted, else local)
if mountpoint -q /data 2>/dev/null; then
    mkdir -p /data/output /data/stats 2>/dev/null || true
else
    mkdir -p "$EMULATOR_DIR/output" "$EMULATOR_DIR/stats" 2>/dev/null || true
fi

# Firewall - open port 8080
if command -v firewall-cmd &>/dev/null; then
    firewall-cmd --add-port=8080/tcp --permanent 2>/dev/null
    firewall-cmd --reload 2>/dev/null
elif command -v ufw &>/dev/null; then
    ufw allow 8080/tcp 2>/dev/null
fi

# Kill existing process on port 8080
fuser -k 8080/tcp 2>/dev/null || true
sleep 1

# Find Java (prefer 17+)
JAVA_CMD="java"
if [ -d "$EMULATOR_DIR/jre" ]; then
    JAVA_CMD="$EMULATOR_DIR/jre/bin/java"
elif ! command -v java &>/dev/null; then
    echo "ERROR: Java not found. Install OpenJDK 17: dnf install -y java-17-openjdk-headless"
    exit 1
fi

# Verify Java version
JAVA_VERSION=$($JAVA_CMD -version 2>&1 | head -1)
echo "Using Java: $JAVA_CMD ($JAVA_VERSION)"

# Determine heap size
HEAP_ARG=""
if [ -n "$1" ]; then
    # Explicit heap from argument
    if [ "$1" -gt 0 ] 2>/dev/null; then
        HEAP_ARG="-Xmx${1}m"
        echo "Heap: ${1} MB (from argument)"
    else
        echo "Heap: JVM default (argument=$1)"
    fi
else
    # Auto-calculate: total RAM minus 2 GB for OS, minimum 1 GB
    TOTAL_RAM_MB=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
    RESERVE_MB=2048
    HEAP_MB=$((TOTAL_RAM_MB - RESERVE_MB))
    if [ "$HEAP_MB" -lt 1024 ]; then
        HEAP_MB=1024
    fi
    HEAP_ARG="-Xmx${HEAP_MB}m"
    echo "System RAM: ${TOTAL_RAM_MB} MB, JVM heap: ${HEAP_MB} MB (reserving ${RESERVE_MB} MB for OS)"
fi

# Start the emulator
echo "Starting Java emulator (log: $LOG_FILE)..."
nohup $JAVA_CMD $HEAP_ARG -jar "$EMULATOR_DIR/emulator.jar" \
    --server.port=8080 \
    > "$LOG_FILE" 2>&1 &

EMULATOR_PID=$!
echo "Emulator PID: $EMULATOR_PID"

# Health check (Spring Boot takes ~10-20s to start)
echo "Waiting for emulator to start..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        echo "Emulator started successfully (took ${i}s)"
        exit 0
    fi
    sleep 1
done

echo "WARNING: Health check failed after 30s. Check $LOG_FILE"
exit 1
