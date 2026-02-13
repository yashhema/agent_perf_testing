#!/bin/bash
# Discover CrowdStrike Falcon agent version and status on RHEL-family systems.
# Outputs JSON to stdout.
VERSION=$(/opt/CrowdStrike/falconctl -g --version 2>/dev/null | grep -oP 'version\s*=\s*\K[\d.]+' || echo "unknown")
STATUS=$(systemctl is-active falcon-sensor 2>/dev/null || echo "unknown")
echo "{\"version\": \"$VERSION\", \"status\": \"$STATUS\"}"
