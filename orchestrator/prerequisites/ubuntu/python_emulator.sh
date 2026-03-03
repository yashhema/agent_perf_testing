#!/bin/bash
# Install Python3 + pip + emulator dependencies on Ubuntu/Debian if not present.
# Idempotent — skips packages that are already installed.
set -e

# Ensure python3 and pip
if ! command -v python3 &>/dev/null; then
    echo "Python3 not found — installing..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip python3-venv
else
    echo "Python3 already installed: $(python3 --version)"
fi

if ! command -v pip3 &>/dev/null && ! python3 -m pip --version &>/dev/null; then
    echo "pip not found — installing..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3-pip
fi

# Install emulator runtime dependencies (skip test deps)
REQUIRED="fastapi uvicorn pydantic psutil"
for pkg in $REQUIRED; do
    if python3 -c "import $pkg" 2>/dev/null; then
        echo "$pkg already installed"
    else
        echo "Installing $pkg..."
        python3 -m pip install --break-system-packages -q "$pkg" 2>/dev/null \
            || pip3 install -q "$pkg"
    fi
done

echo "Python emulator prerequisites installed successfully"
