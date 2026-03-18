#!/bin/bash
# Build all artifacts needed by the orchestrator.
# Run this on the remote machine after sync_setup.py.
#
# Builds:
#   1. JMeter 5.6.3 — downloads from Apache mirror
#   2. Emulator (Java) — builds from source with Maven
#   3. Emulator (Python) — packages from source
#
# Output: orchestrator/artifacts/packages/*.tar.gz
#
# Usage:
#   cd /path/to/repo
#   bash setup/build_artifacts.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARTIFACTS_DIR="$REPO_ROOT/orchestrator/artifacts"
PACKAGES_DIR="$ARTIFACTS_DIR/packages"

echo "============================================================"
echo "Building artifacts"
echo "  Repo root:  $REPO_ROOT"
echo "  Output dir: $PACKAGES_DIR"
echo "============================================================"

mkdir -p "$PACKAGES_DIR"
mkdir -p "$ARTIFACTS_DIR/jmx"
mkdir -p "$ARTIFACTS_DIR/scripts"

# ── 1. JMeter ──────────────────────────────────────────────────
JMETER_VER="5.6.3"
JMETER_TGZ="$PACKAGES_DIR/jmeter-${JMETER_VER}-linux.tar.gz"

if [ -f "$JMETER_TGZ" ]; then
    echo "[1/3] JMeter $JMETER_VER already exists: $JMETER_TGZ"
else
    echo "[1/3] Downloading JMeter $JMETER_VER..."
    JMETER_URL="https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VER}.tgz"

    if command -v curl &>/dev/null; then
        curl -fSL "$JMETER_URL" -o "$JMETER_TGZ"
    elif command -v wget &>/dev/null; then
        wget -q "$JMETER_URL" -O "$JMETER_TGZ"
    else
        echo "ERROR: Neither curl nor wget available. Install one or download manually:"
        echo "  $JMETER_URL -> $JMETER_TGZ"
        exit 1
    fi
    echo "  Downloaded: $JMETER_TGZ ($(du -h "$JMETER_TGZ" | cut -f1))"
fi

# ── 2. Emulator (Java) ────────────────────────────────────────
EMULATOR_JAVA_DIR="$REPO_ROOT/emulator_java"
EMULATOR_JAVA_LINUX_TGZ="$PACKAGES_DIR/emulator-java-linux.tar.gz"
EMULATOR_JAVA_WIN_TGZ="$PACKAGES_DIR/emulator-java-windows.tar.gz"

if [ -f "$EMULATOR_JAVA_LINUX_TGZ" ] && [ -f "$EMULATOR_JAVA_WIN_TGZ" ]; then
    echo "[2/3] Java emulator packages already exist"
else
    echo "[2/3] Building Java emulator..."

    if [ ! -d "$EMULATOR_JAVA_DIR" ]; then
        echo "ERROR: emulator_java/ directory not found at $EMULATOR_JAVA_DIR"
        exit 1
    fi

    # Build with Maven (skip tests for speed)
    if command -v mvn &>/dev/null; then
        cd "$EMULATOR_JAVA_DIR"
        mvn clean package -DskipTests -q 2>&1 | tail -5
        cd "$REPO_ROOT"
    else
        echo "WARNING: Maven not installed. Trying to package from existing build..."
    fi

    # Find the built JAR
    JAR=$(find "$EMULATOR_JAVA_DIR/target" -name "*.jar" -not -name "*-sources*" -not -name "*-javadoc*" | head -1)
    if [ -z "$JAR" ]; then
        echo "ERROR: No JAR found in emulator_java/target/. Run 'mvn package' first."
        exit 1
    fi
    echo "  Found JAR: $JAR"

    # Package for Linux
    TMPDIR=$(mktemp -d)
    mkdir -p "$TMPDIR/emulator"
    cp "$JAR" "$TMPDIR/emulator/emulator.jar"
    cp "$EMULATOR_JAVA_DIR/start.sh" "$TMPDIR/emulator/"
    chmod +x "$TMPDIR/emulator/start.sh"
    tar -czf "$EMULATOR_JAVA_LINUX_TGZ" -C "$TMPDIR" emulator
    echo "  Built: $EMULATOR_JAVA_LINUX_TGZ ($(du -h "$EMULATOR_JAVA_LINUX_TGZ" | cut -f1))"

    # Package for Windows (same JAR, different start script)
    cp "$EMULATOR_JAVA_DIR/start.ps1" "$TMPDIR/emulator/" 2>/dev/null || true
    tar -czf "$EMULATOR_JAVA_WIN_TGZ" -C "$TMPDIR" emulator
    echo "  Built: $EMULATOR_JAVA_WIN_TGZ ($(du -h "$EMULATOR_JAVA_WIN_TGZ" | cut -f1))"
    rm -rf "$TMPDIR"
fi

# ── 3. Emulator (Python) ──────────────────────────────────────
EMULATOR_PY_DIR="$REPO_ROOT/emulator"
EMULATOR_LINUX_TGZ="$PACKAGES_DIR/emulator-linux.tar.gz"
EMULATOR_WIN_TGZ="$PACKAGES_DIR/emulator-windows.tar.gz"

if [ -f "$EMULATOR_LINUX_TGZ" ] && [ -f "$EMULATOR_WIN_TGZ" ]; then
    echo "[3/3] Python emulator packages already exist"
else
    echo "[3/3] Packaging Python emulator..."

    if [ ! -d "$EMULATOR_PY_DIR" ]; then
        echo "WARNING: emulator/ directory not found — skipping Python emulator"
    else
        TMPDIR=$(mktemp -d)
        mkdir -p "$TMPDIR/emulator"
        cp -r "$EMULATOR_PY_DIR/app" "$TMPDIR/emulator/"
        cp "$EMULATOR_PY_DIR/requirements.txt" "$TMPDIR/emulator/"
        cp "$EMULATOR_PY_DIR/start.sh" "$TMPDIR/emulator/" 2>/dev/null || true
        cp "$EMULATOR_PY_DIR/start.ps1" "$TMPDIR/emulator/" 2>/dev/null || true
        chmod +x "$TMPDIR/emulator/start.sh" 2>/dev/null || true

        tar -czf "$EMULATOR_LINUX_TGZ" -C "$TMPDIR" emulator
        echo "  Built: $EMULATOR_LINUX_TGZ ($(du -h "$EMULATOR_LINUX_TGZ" | cut -f1))"

        tar -czf "$EMULATOR_WIN_TGZ" -C "$TMPDIR" emulator
        echo "  Built: $EMULATOR_WIN_TGZ ($(du -h "$EMULATOR_WIN_TGZ" | cut -f1))"
        rm -rf "$TMPDIR"
    fi
fi

# ── Summary ────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "Artifacts:"
echo "============================================================"
ls -lh "$PACKAGES_DIR/"
echo ""
echo "JMX templates:"
ls -lh "$ARTIFACTS_DIR/jmx/" 2>/dev/null || echo "  (none — sync from git)"
echo ""
echo "Scripts:"
ls -lh "$ARTIFACTS_DIR/scripts/" 2>/dev/null || echo "  (none — sync from git)"
echo ""
echo "Done. JMX and scripts are synced from git via sync_setup.py."
