#!/bin/bash
# Install Java JRE on RHEL/CentOS/Rocky if not present.
# Idempotent — skips if java is already available.
set -e

# Ensure tar is available (minimal Rocky installs may lack it)
if ! command -v tar &>/dev/null; then
    echo "tar not found - installing..."
    if command -v dnf &>/dev/null; then
        dnf install -y -q tar
    else
        yum install -y -q tar
    fi
fi

if command -v java &>/dev/null; then
    JAVA_VER=$(java -version 2>&1 | head -1)
    echo "Java already installed: $JAVA_VER"
    exit 0
fi

echo "Java not found — installing OpenJDK 11 JRE..."
if command -v dnf &>/dev/null; then
    dnf install -y -q java-11-openjdk-headless
else
    yum install -y -q java-11-openjdk-headless
fi
java -version 2>&1
echo "Java JRE installed successfully"
