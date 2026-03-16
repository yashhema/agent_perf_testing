#!/bin/bash
# =============================================================================
# Install and configure PostgreSQL on RHEL for the orchestrator
# Run as the service account (with NOPASSWD sudo)
#
# Usage: bash install_postgres.sh [db_name] [db_user] [db_password]
#   Defaults: orchestrator / orchestrator / orchestrator
# =============================================================================

set -e

DB_NAME="${1:-orchestrator}"
DB_USER="${2:-orchestrator}"
DB_PASS="${3:-orchestrator}"

echo "=== PostgreSQL Setup ==="
echo "  DB: $DB_NAME  User: $DB_USER"
echo ""

# --- Step 1: Install ---
if which psql &>/dev/null; then
    echo "[1/6] PostgreSQL already installed: $(psql --version)"
else
    echo "[1/6] Installing PostgreSQL ..."
    sudo dnf install -y postgresql-server postgresql-contrib
fi

# --- Step 2: Init DB (skip if already running) ---
if sudo -u postgres psql -c "SELECT 1" &>/dev/null; then
    echo "[2/6] PostgreSQL already running — skipping initdb"
else
    echo "[2/6] Initializing database ..."
    sudo postgresql-setup --initdb
fi

# --- Step 3: Find data dir and configure pg_hba.conf ---
PG_DATA=$(sudo -u postgres psql -tAc "SHOW data_directory" 2>/dev/null | tr -d '[:space:]')
if [ -z "$PG_DATA" ]; then
    # Fallback: common paths
    for d in /var/lib/pgsql/data /var/lib/pgsql/16/data /var/lib/pgsql/15/data; do
        if [ -f "$d/PG_VERSION" ]; then
            PG_DATA="$d"
            break
        fi
    done
fi

if [ -z "$PG_DATA" ]; then
    echo "WARNING: Could not find data directory — skipping pg_hba.conf config"
    echo "  PostgreSQL may already be configured correctly"
else
    echo "  Data directory: $PG_DATA"
fi

HBA="$PG_DATA/pg_hba.conf"
if [ -n "$PG_DATA" ] && [ -f "$HBA" ]; then
    echo "[3/6] Configuring $HBA for md5 auth ..."
    sudo cp "$HBA" "${HBA}.bak" 2>/dev/null || true
    sudo sed -i 's/^\(local.*all.*all.*\)peer$/\1md5/' "$HBA"
    sudo sed -i 's/^\(host.*all.*all.*127\.0\.0\.1\/32.*\)ident$/\1md5/' "$HBA"
    sudo sed -i 's/^\(host.*all.*all.*::1\/128.*\)ident$/\1md5/' "$HBA"
    echo "  pg_hba.conf updated"
else
    echo "[3/6] Skipping pg_hba.conf (not found or already configured)"
fi

# --- Step 4: Start/restart ---
echo "[4/6] Starting PostgreSQL ..."
sudo systemctl enable postgresql
sudo systemctl restart postgresql

# Wait for it
for i in $(seq 1 10); do
    if sudo -u postgres psql -c "SELECT 1" &>/dev/null; then
        echo "  PostgreSQL is running"
        break
    fi
    sleep 1
done

# --- Step 5: Create user ---
echo "[5/6] Creating user '$DB_USER' ..."
USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null)
if [ "$USER_EXISTS" = "1" ]; then
    echo "  User '$DB_USER' already exists"
    # Update password
    sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null
else
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null
    echo "  User '$DB_USER' created"
fi

# --- Step 6: Create database ---
echo "[6/6] Creating database '$DB_NAME' ..."
DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null)
if [ "$DB_EXISTS" = "1" ]; then
    echo "  Database '$DB_NAME' already exists"
else
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null
    echo "  Database '$DB_NAME' created"
fi

# --- Verify ---
echo ""
echo "=== Verification ==="
if PGPASSWORD="$DB_PASS" psql -h localhost -U "$DB_USER" -d "$DB_NAME" -c "SELECT version();" 2>/dev/null | head -3; then
    echo ""
    echo "SUCCESS: PostgreSQL is ready"
    echo "  Connection: postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
else
    echo ""
    echo "WARNING: Could not connect with password auth."
    echo "  Check pg_hba.conf and restart: sudo systemctl restart postgresql"
fi
