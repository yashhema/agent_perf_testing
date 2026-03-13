#!/bin/bash
# Prerequisite script for Java emulator on RHEL/Rocky Linux
# Installs OpenJDK 17 JRE (headless) if not already present

set -e

echo "=== Java Emulator Prerequisites ==="

# Ensure basic tools are available (minimal images may lack these)
dnf install -y curl tar gzip >/dev/null 2>&1 || true

# Check if Java 17+ is already installed
if java -version 2>&1 | grep -qE '"(17|18|19|20|21)'; then
    echo "Java 17+ already installed:"
    java -version 2>&1
    exit 0
fi

echo "Installing OpenJDK 17 JRE..."

# Detect package manager
if command -v dnf &>/dev/null; then
    dnf install -y java-17-openjdk-headless
elif command -v yum &>/dev/null; then
    yum install -y java-17-openjdk-headless
else
    echo "ERROR: Neither dnf nor yum found"
    exit 1
fi

# Verify
echo "Java installed:"
java -version 2>&1
echo "=== Prerequisites complete ==="
