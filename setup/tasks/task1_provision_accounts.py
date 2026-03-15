"""Task 1: Provision service account on all machines.

For each server in servers.csv:
  - Linux (RHEL):  SSH with firsttime creds, create user, add to wheel, set password
  - Windows:       WinRM with firsttime creds, create user, add to Administrators
"""

import logging
from .common import (
    ServerEntry, Credentials, SetupConfig,
    ssh_run, winrm_run, load_servers, load_credentials, validate_servers,
)

logger = logging.getLogger("setup.task1")


def _provision_linux(server: ServerEntry, creds: Credentials, config: SetupConfig):
    """Create service account on a Linux (RHEL) machine."""
    svc_user = creds.svc_user
    svc_pass = creds.svc_pass

    commands = [
        # Check if user already exists
        f"id {svc_user} 2>/dev/null && echo 'USER_EXISTS' || echo 'USER_MISSING'",
        # Create user if missing, set password, add to wheel
        f"""
        if ! id {svc_user} 2>/dev/null; then
            useradd -m -s /bin/bash {svc_user}
            echo '{svc_user}:{svc_pass}' | chpasswd
            usermod -aG wheel {svc_user}
            echo 'CREATED'
        else
            echo '{svc_user}:{svc_pass}' | chpasswd
            usermod -aG wheel {svc_user}
            echo 'UPDATED'
        fi
        """,
        # Verify: check groups
        f"id {svc_user}",
        # Enable password auth in sshd if needed
        "grep -q '^PasswordAuthentication yes' /etc/ssh/sshd_config || "
        "(sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config "
        "&& systemctl restart sshd && echo 'SSHD_RESTARTED') || echo 'SSHD_OK'",
        # Ensure sudo without password for wheel (optional, for automation)
        f"grep -q '^{svc_user}' /etc/sudoers.d/{svc_user} 2>/dev/null || "
        f"echo '{svc_user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{svc_user} && "
        f"chmod 440 /etc/sudoers.d/{svc_user}",
    ]

    logger.info("Provisioning service account on Linux: %s (%s)", server.hostname, server.ip)
    results = ssh_run(server.ip, creds.firsttime_user, creds.firsttime_pass, commands)

    # Check result of user creation
    for r in results:
        if r["rc"] != 0 and "USER_EXISTS" not in r.get("stdout", ""):
            logger.error("  FAILED on %s: %s", server.hostname, r["stderr"])
            return False

    logger.info("  OK: %s — service account '%s' ready", server.hostname, svc_user)
    return True


def _provision_windows(server: ServerEntry, creds: Credentials, config: SetupConfig):
    """Create service account on a Windows machine."""
    svc_user = creds.svc_user
    svc_pass = creds.svc_pass

    commands = [
        # Check if user exists
        f"if (Get-LocalUser -Name '{svc_user}' -ErrorAction SilentlyContinue) {{ 'USER_EXISTS' }} else {{ 'USER_MISSING' }}",
        # Create or update user
        f"""
        $user = Get-LocalUser -Name '{svc_user}' -ErrorAction SilentlyContinue
        if (-not $user) {{
            $secPass = ConvertTo-SecureString '{svc_pass}' -AsPlainText -Force
            New-LocalUser -Name '{svc_user}' -Password $secPass -FullName 'Performance Test Service' -Description 'Agent perf testing service account' -PasswordNeverExpires
            Add-LocalGroupMember -Group 'Administrators' -Member '{svc_user}'
            Write-Output 'CREATED'
        }} else {{
            $secPass = ConvertTo-SecureString '{svc_pass}' -AsPlainText -Force
            Set-LocalUser -Name '{svc_user}' -Password $secPass
            # Ensure in Administrators
            $members = Get-LocalGroupMember -Group 'Administrators' | Select-Object -ExpandProperty Name
            if ($members -notcontains "$env:COMPUTERNAME\\{svc_user}") {{
                Add-LocalGroupMember -Group 'Administrators' -Member '{svc_user}'
            }}
            Write-Output 'UPDATED'
        }}
        """,
        # Verify
        f"Get-LocalUser -Name '{svc_user}' | Format-List Name,Enabled",
        f"Get-LocalGroupMember -Group 'Administrators' | Where-Object {{ $_.Name -like '*{svc_user}*' }}",
        # Ensure WinRM is configured for the service account
        "Enable-PSRemoting -Force -SkipNetworkProfileCheck 2>$null; 'WINRM_OK'",
    ]

    logger.info("Provisioning service account on Windows: %s (%s)", server.hostname, server.ip)
    results = winrm_run(server.ip, creds.firsttime_user, creds.firsttime_pass, commands)

    for r in results:
        if r["rc"] != 0 and "USER_EXISTS" not in r.get("stdout", ""):
            logger.error("  FAILED on %s: %s", server.hostname, r["stderr"])
            return False

    logger.info("  OK: %s — service account '%s' ready", server.hostname, svc_user)
    return True


def run(config: SetupConfig):
    """Run Task 1: provision service accounts on all servers."""
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)
    validate_servers(servers)

    logger.info("=" * 60)
    logger.info("TASK 1: Provision service account '%s' on %d servers", creds.svc_user, len(servers))
    logger.info("=" * 60)

    success = []
    failed = []

    for server in servers:
        try:
            if server.is_linux:
                ok = _provision_linux(server, creds, config)
            else:
                ok = _provision_windows(server, creds, config)

            if ok:
                success.append(server.hostname)
            else:
                failed.append(server.hostname)
        except Exception as e:
            logger.error("  EXCEPTION on %s: %s", server.hostname, e)
            failed.append(server.hostname)

    logger.info("-" * 60)
    logger.info("Results: %d succeeded, %d failed", len(success), len(failed))
    if failed:
        logger.error("Failed servers: %s", ", ".join(failed))
        return False

    logger.info("Task 1 complete — all servers provisioned.")
    return True
