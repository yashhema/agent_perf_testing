#!/bin/bash
# Discover native OS service versions and status on Ubuntu/Debian systems.
# Checks sshd, cron, rsyslogd, systemd-journald.
# Outputs JSON to stdout.

# SSH daemon
SSHD_VER=$(sshd -V 2>&1 | head -1 | grep -oP 'OpenSSH_\K[\d.p]+' || echo "unknown")
SSHD_STATUS=$(systemctl is-active sshd 2>/dev/null || systemctl is-active ssh 2>/dev/null || echo "unknown")

# Cron
CRON_VER=$(dpkg-query -W -f='${Version}' cron 2>/dev/null || echo "unknown")
CRON_STATUS=$(systemctl is-active cron 2>/dev/null || echo "unknown")

# Rsyslog
RSYSLOG_VER=$(rsyslogd -v 2>/dev/null | head -1 | grep -oP '[\d.]+' | head -1 || echo "unknown")
RSYSLOG_STATUS=$(systemctl is-active rsyslog 2>/dev/null || echo "unknown")

# systemd-journald
JOURNALD_STATUS=$(systemctl is-active systemd-journald 2>/dev/null || echo "unknown")
SYSTEMD_VER=$(systemctl --version 2>/dev/null | head -1 | grep -oP 'systemd\s+\K[\d]+' || echo "unknown")

echo "{\"version\": \"sshd=${SSHD_VER},cron=${CRON_VER},rsyslog=${RSYSLOG_VER},systemd=${SYSTEMD_VER}\", \"status\": \"sshd=${SSHD_STATUS},cron=${CRON_STATUS},rsyslog=${RSYSLOG_STATUS},journald=${JOURNALD_STATUS}\"}"
