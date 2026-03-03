#!/bin/bash
# Install Java JRE on Ubuntu/Debian if not present.
# Idempotent — skips if java is already available.
set -e

if command -v java &>/dev/null; then
    JAVA_VER=$(java -version 2>&1 | head -1)
    echo "Java already installed: $JAVA_VER"
    exit 0
fi

echo "Java not found — installing OpenJDK 11 JRE..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq openjdk-11-jre-headless
java -version 2>&1
echo "Java JRE installed successfully"
