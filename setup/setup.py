#!/usr/bin/env python3
"""Agent Performance Testing - Setup CLI.

Run tasks sequentially to set up the lab environment:

    python setup.py task1              # Provision service accounts on all machines
    python setup.py task2              # Discover server details from vSphere
    python setup.py task3              # Create DB schema, seed data, generate credentials.json
    python setup.py task4              # Install prerequisites (PostgreSQL, Python, JMeter)

    python setup.py verify             # Test connectivity to all servers
    python setup.py show-config        # Display loaded configuration
    python setup.py show-servers       # Display server list with roles

Recommended order: task1 → task2 → task4 → task3
  (task4 installs PostgreSQL, which task3 needs)

Config: setup_config.yaml (in the same directory as this script)
"""

import os
import sys
import click
import logging

# Ensure the setup directory is importable
SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
if SETUP_DIR not in sys.path:
    sys.path.insert(0, SETUP_DIR)

from tasks.common import (
    load_config, load_servers, load_credentials, validate_servers, setup_logging,
    ssh_run, winrm_run,
)

DEFAULT_CONFIG = os.path.join(SETUP_DIR, "setup_config.yaml")

logger = logging.getLogger("setup")


@click.group()
@click.option("--config", "-c", default=DEFAULT_CONFIG, help="Path to setup_config.yaml")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, config, verbose):
    """Agent Performance Testing - Lab Setup Tool."""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose


def _get_config(ctx):
    return load_config(ctx.obj["config_path"])


@cli.command()
@click.pass_context
def task1(ctx):
    """Task 1: Provision service accounts on all machines."""
    config = _get_config(ctx)
    from tasks.task1_provision_accounts import run
    success = run(config)
    sys.exit(0 if success else 1)


@cli.command()
@click.pass_context
def task2(ctx):
    """Task 2: Discover server details from vSphere."""
    config = _get_config(ctx)
    from tasks.task2_vsphere_discovery import run
    success = run(config)
    sys.exit(0 if success else 1)


@cli.command()
@click.pass_context
def task3(ctx):
    """Task 3: Create DB schema, seed data, generate credentials.json."""
    config = _get_config(ctx)
    from tasks.task3_seed_and_configure import run
    success = run(config)
    sys.exit(0 if success else 1)


@cli.command()
@click.pass_context
def task4(ctx):
    """Task 4: Install prerequisites (PostgreSQL, Python, JMeter, venv)."""
    config = _get_config(ctx)
    from tasks.task4_install_orchestrator import run
    success = run(config)
    sys.exit(0 if success else 1)


@cli.command()
@click.pass_context
def verify(ctx):
    """Test connectivity to all servers using service account."""
    config = _get_config(ctx)
    servers = load_servers(config.servers_file)
    creds = load_credentials(config.credentials_file)
    validate_servers(servers)

    ok = 0
    fail = 0
    for server in servers:
        try:
            if server.is_linux:
                results = ssh_run(server.ip, creds.svc_user, creds.svc_pass,
                                  ["hostname && whoami && uptime"])
                status = "OK" if results[0]["rc"] == 0 else "FAIL"
                detail = results[0]["stdout"] if results[0]["rc"] == 0 else results[0]["stderr"]
            else:
                results = winrm_run(server.ip, creds.svc_user, creds.svc_pass,
                                    ["$env:COMPUTERNAME; whoami; (Get-Date).ToString()"])
                status = "OK" if results[0]["rc"] == 0 else "FAIL"
                detail = results[0]["stdout"] if results[0]["rc"] == 0 else results[0]["stderr"]
        except Exception as e:
            status = "FAIL"
            detail = str(e)

        icon = "+" if status == "OK" else "X"
        click.echo(f"  [{icon}] {server.hostname:20s} {server.ip:15s} {server.os:8s} {server.role:12s} {detail}")
        if status == "OK":
            ok += 1
        else:
            fail += 1

    click.echo(f"\n  {ok} OK, {fail} failed out of {len(servers)}")
    sys.exit(0 if fail == 0 else 1)


@cli.command("show-config")
@click.pass_context
def show_config(ctx):
    """Display loaded configuration."""
    config = _get_config(ctx)
    click.echo(f"Config file:       {ctx.obj['config_path']}")
    click.echo(f"Repo path:         {config.repo_path}")
    click.echo(f"Servers file:      {config.servers_file}")
    click.echo(f"Credentials file:  {config.credentials_file}")
    click.echo(f"vSphere host:      {config.vsphere_host}:{config.vsphere_port}")
    click.echo(f"PostgreSQL:        {config.postgres_user}@{config.postgres_host}:{config.postgres_port}/{config.postgres_db}")
    click.echo(f"Lab name:          {config.lab_name}")
    click.echo(f"Discovery output:  {config.discovery_file}")
    click.echo(f"Credentials JSON:  {config.credentials_json_path}")
    click.echo(f"Load profiles:     {', '.join(lp['name'] for lp in config.load_profiles)}")


@cli.command("show-servers")
@click.pass_context
def show_servers(ctx):
    """Display server list with roles."""
    config = _get_config(ctx)
    servers = load_servers(config.servers_file)

    click.echo(f"{'Hostname':20s} {'IP':15s} {'OS':8s} {'Role':12s} {'Family':8s}")
    click.echo("-" * 65)
    for s in servers:
        click.echo(f"{s.hostname:20s} {s.ip:15s} {s.os:8s} {s.role:12s} {s.os_family:8s}")

    click.echo(f"\nTotal: {len(servers)} servers")
    by_role = {}
    for s in servers:
        by_role.setdefault(s.role, []).append(s.hostname)
    for role, hosts in by_role.items():
        click.echo(f"  {role}: {len(hosts)} — {', '.join(hosts)}")


if __name__ == "__main__":
    cli()
