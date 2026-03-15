"""Task 1: Make service account admin on all machines.

The service account already exists on all machines.
This task logs in with 'firsttime' creds (your personal admin) and:
  - Linux (RHEL):  Adds service account to wheel, grants NOPASSWD sudo, enables SSH password auth
  - Windows:       Adds service account to Administrators, ensures WinRM is enabled
"""

import logging
from .common import (
    ServerEntry, Credentials, SetupConfig,
    ssh_run, winrm_run, load_servers, load_credentials, validate_servers,
)

logger = logging.getLogger("setup.task1")


def _provision_linux(server: ServerEntry, creds: Credentials, config: SetupConfig):
    """Elevate service account to admin on a Linux (RHEL) machine."""
    svc_user = creds.svc_user

    commands = [
        # Verify user exists
        f"id {svc_user} && echo 'USER_EXISTS' || echo 'USER_MISSING'",
        # Add to wheel group (admin)
        f"usermod -aG wheel {svc_user} && echo 'WHEEL_OK'",
        # Grant NOPASSWD sudo for automation
        f"echo '{svc_user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{svc_user} && "
        f"chmod 440 /etc/sudoers.d/{svc_user} && echo 'SUDOERS_OK'",
        # Enable password auth in sshd if needed
        "grep -q '^PasswordAuthentication yes' /etc/ssh/sshd_config && echo 'SSHD_OK' || "
        "(sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config "
        "&& systemctl restart sshd && echo 'SSHD_RESTARTED')",
        # Verify: show groups
        f"id {svc_user}",
    ]

    logger.info("Elevating service account on Linux: %s (%s)", server.hostname, server.ip)
    results = ssh_run(server.ip, creds.firsttime_user, creds.firsttime_pass, commands)

    # Check if user exists
    if results and "USER_MISSING" in results[0].get("stdout", ""):
        logger.error("  FAILED on %s: user '%s' does not exist", server.hostname, svc_user)
        return False

    for r in results:
        if r["rc"] != 0:
            logger.error("  FAILED on %s: cmd='%s' err='%s'", server.hostname, r["cmd"][:60], r["stderr"])
            return False

    logger.info("  OK: %s — '%s' is now admin (wheel + NOPASSWD sudo)", server.hostname, svc_user)
    return True


def _provision_windows(server: ServerEntry, creds: Credentials, config: SetupConfig):
    """Elevate service account to admin on a Windows machine."""
    svc_user = creds.svc_user

    commands = [
        # Verify user exists
        f"if (Get-LocalUser -Name '{svc_user}' -ErrorAction SilentlyContinue) {{ 'USER_EXISTS' }} else {{ 'USER_MISSING' }}",
        # Add to Administrators group (idempotent — ignores if already member)
        f"""
        try {{
            Add-LocalGroupMember -Group 'Administrators' -Member '{svc_user}' -ErrorAction Stop
            Write-Output 'ADDED_TO_ADMINS'
        }} catch {{
            if ($_.Exception.Message -like '*already a member*') {{
                Write-Output 'ALREADY_ADMIN'
            }} else {{
                throw $_
            }}
        }}
        """,
        # Verify membership
        f"Get-LocalGroupMember -Group 'Administrators' | Where-Object {{ $_.Name -like '*{svc_user}*' }}",
        # Ensure WinRM is configured
        "Enable-PSRemoting -Force -SkipNetworkProfileCheck 2>$null; 'WINRM_OK'",
    ]

    logger.info("Elevating service account on Windows: %s (%s)", server.hostname, server.ip)
    results = winrm_run(server.ip, creds.firsttime_user, creds.firsttime_pass, commands)

    # Check if user exists
    if results and "USER_MISSING" in results[0].get("stdout", ""):
        logger.error("  FAILED on %s: user '%s' does not exist", server.hostname, svc_user)
        return False

    for r in results:
        if r["rc"] != 0:
            logger.error("  FAILED on %s: cmd='%s' err='%s'", server.hostname, r["cmd"][:60], r["stderr"])
            return False

    logger.info("  OK: %s — '%s' is now admin (Administrators group)", server.hostname, svc_user)
    return True


def run(config: SetupConfig):
    """Run Task 1: make service account admin on all servers."""
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)
    validate_servers(servers)

    logger.info("=" * 60)
    logger.info("TASK 1: Elevate service account '%s' to admin on %d servers", creds.svc_user, len(servers))
    logger.info("  Using '%s' creds to login", creds.firsttime_user)
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

    logger.info("Task 1 complete — service account is admin on all servers.")
    return True
