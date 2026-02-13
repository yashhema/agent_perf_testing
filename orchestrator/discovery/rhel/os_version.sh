#!/bin/bash
# Discover RHEL/CentOS/Rocky/Alma OS version information.
# Outputs JSON to stdout.
source /etc/os-release
MAJOR=$(echo "$VERSION_ID" | cut -d. -f1)
MINOR=$(echo "$VERSION_ID" | cut -d. -f2)
KERNEL=$(uname -r)
echo "{\"os_major_ver\": \"$MAJOR\", \"os_minor_ver\": \"$MINOR\", \"os_build\": \"$VERSION_ID\", \"os_kernel_ver\": \"$KERNEL\"}"
