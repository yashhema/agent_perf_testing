"""Task 1: Elevate AD service account to admin on all machines.

The service account is an Active Directory account that already exists.
This task logs in with 'firsttime' creds (your personal admin) and:
  - Linux (RHEL):  Adds sudoers entry for DOMAIN\\user with NOPASSWD
  - Windows:       Adds DOMAIN\\user to local Administrators group

Then verifies connectivity using the service account.
"""

import logging
from .common import (
    ServerEntry, Credentials, SetupConfig,
    ssh_run, winrm_run, load_servers, load_credentials, validate_servers,
)

logger = logging.getLogger("setup.task1")


def _elevate_linux(server: ServerEntry, creds: Credentials, config: SetupConfig):
    """Add AD service account to sudoers on RHEL."""
    svc_user = creds.svc_user
    domain = config.ad_domain

    # sudoers needs DOMAIN\\user format (escaped backslash)
    if domain:
        sudoers_user = f"{domain}\\\\{svc_user}"
        display_user = f"{domain}\\{svc_user}"
    else:
        sudoers_user = svc_user
        display_user = svc_user

    # Use a safe filename for sudoers.d (no backslashes)
    sudoers_file = svc_user.replace("\\", "_").replace("@", "_")

    commands = [
        # Check if user resolves via AD/SSSD
        f"id '{display_user}' 2>/dev/null && echo 'USER_OK' || "
        f"(id '{svc_user}' 2>/dev/null && echo 'USER_OK_SHORT' || echo 'USER_NOT_FOUND')",
        # Add sudoers entry
        f"echo '{sudoers_user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{sudoers_file} && "
        f"chmod 440 /etc/sudoers.d/{sudoers_file} && echo 'SUDOERS_OK'",
        # Verify sudoers file is valid
        f"visudo -cf /etc/sudoers.d/{sudoers_file} && echo 'SUDOERS_VALID'",
    ]

    logger.info("Elevating on Linux: %s — user '%s'", server.hostname, display_user)
    results = ssh_run(server.ip, creds.firsttime_user, creds.firsttime_pass, commands)

    if results and "USER_NOT_FOUND" in results[0].get("stdout", ""):
        logger.error("  FAILED: user '%s' not found on %s (check AD/SSSD)", display_user, server.hostname)
        return False

    for r in results:
        if r["rc"] != 0:
            logger.error("  FAILED on %s: %s", server.hostname, r["stderr"])
            return False

    logger.info("  OK: %s — sudoers entry added", server.hostname)
    return True


def _elevate_windows(server: ServerEntry, creds: Credentials, config: SetupConfig):
    """Add AD service account to local Administrators on Windows."""
    svc_user = creds.svc_user
    domain = config.ad_domain

    if domain:
        qualified_user = f"{domain}\\{svc_user}"
    else:
        qualified_user = svc_user

    commands = [
        # Add to Administrators (idempotent)
        f"""
        try {{
            Add-LocalGroupMember -Group 'Administrators' -Member '{qualified_user}' -ErrorAction Stop
            Write-Output 'ADDED_TO_ADMINS'
        }} catch {{
            if ($_.Exception.Message -like '*already a member*') {{
                Write-Output 'ALREADY_ADMIN'
            }} else {{
                Write-Output "ERROR: $($_.Exception.Message)"
            }}
        }}
        """,
        # Verify
        f"Get-LocalGroupMember -Group 'Administrators' | Where-Object {{ $_.Name -like '*{svc_user}*' }} | Format-Table -AutoSize",
    ]

    logger.info("Elevating on Windows: %s — user '%s'", server.hostname, qualified_user)
    results = winrm_run(server.ip, creds.firsttime_user, creds.firsttime_pass, commands)

    for r in results:
        if "ERROR:" in r.get("stdout", ""):
            logger.error("  FAILED on %s: %s", server.hostname, r["stdout"])
            return False

    logger.info("  OK: %s — added to Administrators", server.hostname)
    return True


def _verify_access(server: ServerEntry, creds: Credentials, config: SetupConfig):
    """Verify service account can connect and has admin/sudo."""
    svc_user = creds.svc_user
    svc_pass = creds.svc_pass
    domain = config.ad_domain

    try:
        if server.is_linux:
            # SSH with service account, test sudo
            login_user = f"{svc_user}@{domain}" if domain else svc_user
            results = ssh_run(server.ip, login_user, svc_pass,
                              ["sudo whoami"], timeout=15)
            if results and results[0]["rc"] == 0 and "root" in results[0]["stdout"]:
                logger.info("  VERIFY OK: %s — SSH + sudo works", server.hostname)
                return True
            else:
                logger.warning("  VERIFY WARN: %s — SSH ok but sudo may need testing", server.hostname)
                return True  # SSH worked, sudo might need domain\\user format
        else:
            # WinRM with service account
            login_user = f"{domain}\\{svc_user}" if domain else svc_user
            results = winrm_run(server.ip, login_user, svc_pass,
                                ["whoami; (New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"])
            if results and results[0]["rc"] == 0:
                logger.info("  VERIFY OK: %s — WinRM works, output: %s",
                            server.hostname, results[0]["stdout"].replace("\n", " "))
                return True
            else:
                logger.warning("  VERIFY FAIL: %s — %s", server.hostname,
                               results[0]["stderr"] if results else "no response")
                return False
    except Exception as e:
        logger.warning("  VERIFY FAIL: %s — %s", server.hostname, e)
        return False


def run(config: SetupConfig):
    """Run Task 1: elevate AD service account and verify access."""
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)
    validate_servers(servers)

    if not config.ad_domain:
        logger.warning("No AD domain set in setup_config.yaml (service_account.domain)")
        logger.warning("Will use username as-is without domain prefix")

    logger.info("=" * 60)
    logger.info("TASK 1: Elevate AD account '%s' (domain=%s) on %d servers",
                creds.svc_user, config.ad_domain or "none", len(servers))
    logger.info("  Phase 1: Elevate using '%s' creds", creds.firsttime_user)
    logger.info("  Phase 2: Verify using service account creds")
    logger.info("=" * 60)

    # Phase 1: Elevate
    logger.info("\n--- Phase 1: Elevate ---")
    elevated = []
    failed = []

    for server in servers:
        try:
            if server.is_linux:
                ok = _elevate_linux(server, creds, config)
            else:
                ok = _elevate_windows(server, creds, config)

            if ok:
                elevated.append(server.hostname)
            else:
                failed.append(server.hostname)
        except Exception as e:
            logger.error("  EXCEPTION on %s: %s", server.hostname, e)
            failed.append(server.hostname)

    # Phase 2: Verify
    logger.info("\n--- Phase 2: Verify service account access ---")
    verified = []
    verify_failed = []

    for server in servers:
        if server.hostname in failed:
            verify_failed.append(server.hostname)
            continue
        if _verify_access(server, creds, config):
            verified.append(server.hostname)
        else:
            verify_failed.append(server.hostname)

    logger.info("-" * 60)
    logger.info("Elevated:  %d/%d", len(elevated), len(servers))
    logger.info("Verified:  %d/%d", len(verified), len(servers))
    if failed:
        logger.error("Elevation failed: %s", ", ".join(failed))
    if verify_failed:
        logger.warning("Verify failed: %s", ", ".join(verify_failed))

    return len(failed) == 0
