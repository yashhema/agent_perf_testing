#!/usr/bin/env python3
"""Quick test: verify service account has NOPASSWD sudo on all Linux servers.

Usage:
    python test_sudo.py                    # test all Linux servers
    python test_sudo.py hostname1          # test specific server(s)
    python test_sudo.py hostname1 hostname2
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tasks.common import load_config, load_servers, load_credentials, ssh_run

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_config.yaml")


def main():
    config = load_config(CONFIG)
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)

    # Filter to Linux only
    linux_servers = [s for s in servers if s.is_linux]

    # Filter to specific hostnames if provided
    if len(sys.argv) > 1:
        filter_hosts = [h.lower() for h in sys.argv[1:]]
        linux_servers = [s for s in linux_servers if s.hostname.lower() in filter_hosts]

    if not linux_servers:
        print("No Linux servers to test.")
        return

    domain = config.ad_domain
    login_user = f"{creds.svc_user}@{domain}" if domain else creds.svc_user

    print(f"Testing NOPASSWD sudo for '{login_user}' on {len(linux_servers)} Linux servers\n")

    ok = 0
    fail = 0

    for server in linux_servers:
        try:
            results = ssh_run(
                server.ip, login_user, creds.svc_pass,
                ["sudo -n whoami"],  # -n = non-interactive, fails if password needed
                timeout=15,
            )
            stdout = results[0]["stdout"].strip()
            rc = results[0]["rc"]

            if rc == 0 and "root" in stdout:
                print(f"  [OK]   {server.hostname:30s} sudo works (got root)")
                ok += 1
            else:
                print(f"  [FAIL] {server.hostname:30s} rc={rc} stdout='{stdout}' stderr='{results[0]['stderr']}'")
                fail += 1
        except Exception as e:
            print(f"  [FAIL] {server.hostname:30s} {e}")
            fail += 1

    print(f"\n{ok} OK, {fail} failed out of {len(linux_servers)}")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
