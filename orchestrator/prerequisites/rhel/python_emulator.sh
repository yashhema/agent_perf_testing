#!/bin/bash
# Install Python3 + pip + emulator dependencies on RHEL/CentOS/Rocky if not present.
# Idempotent — skips packages that are already installed.
set -e

if ! command -v python3 &>/dev/null; then
    echo "Python3 not found — installing..."
    if command -v dnf &>/dev/null; then
        dnf install -y -q python3 python3-pip
    else
        yum install -y -q python3 python3-pip
    fi
else
    echo "Python3 already installed: $(python3 --version)"
fi

if ! python3 -m pip --version &>/dev/null; then
    echo "pip not found — installing..."
    if command -v dnf &>/dev/null; then
        dnf install -y -q python3-pip
    else
        yum install -y -q python3-pip
    fi
fi

REQUIRED="fastapi uvicorn pydantic psutil"
for pkg in $REQUIRED; do
    if python3 -c "import $pkg" 2>/dev/null; then
        echo "$pkg already installed"
    else
        echo "Installing $pkg..."
        python3 -m pip install -q "$pkg"
    fi
done

echo "Python emulator prerequisites installed successfully"
