"""Shared utilities for setup tasks: config loading, SSH, WinRM helpers."""

import csv
import os
import socket
import sys
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
import paramiko
import winrm

logger = logging.getLogger("setup")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ServerEntry:
    hostname: str
    os: str  # rhel8, rhel9, win2016, win2019, win2022
    role: str  # orchestrator, loadgen, target, unassigned
    ip: str = ""  # optional — resolved from hostname via DNS if empty

    def __post_init__(self):
        if not self.ip:
            try:
                self.ip = socket.gethostbyname(self.hostname)
            except socket.gaierror:
                self.ip = self.hostname  # fallback: use hostname directly

    @property
    def is_linux(self) -> bool:
        return self.os.startswith("rhel")

    @property
    def is_windows(self) -> bool:
        return self.os.startswith("win")

    @property
    def os_family(self) -> str:
        return "linux" if self.is_linux else "windows"

    @property
    def os_major_ver(self) -> str:
        if self.is_linux:
            return self.os.replace("rhel", "")  # "8" or "9"
        return self.os.replace("win", "")  # "2016", "2019", "2022"

    @property
    def os_vendor_family(self) -> str:
        if self.is_linux:
            return "rhel"
        return "windows_server"


@dataclass
class Credentials:
    firsttime_user: str
    firsttime_pass: str
    vsphere_user: str
    vsphere_pass: str
    svc_user: str
    svc_pass: str


@dataclass
class SetupConfig:
    repo_path: str
    servers_file: str
    credentials_file: str
    vsphere_host: str
    vsphere_port: int
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    lab_name: str
    lab_description: str
    load_profiles: list
    discovery_file: str
    credentials_json_path: str
    create_ssh_key: bool
    base_dir: str  # directory where setup_config.yaml lives


# ---------------------------------------------------------------------------
# Config / CSV loaders
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> SetupConfig:
    """Load setup_config.yaml and return a SetupConfig object."""
    config_path = os.path.abspath(config_path)
    base_dir = os.path.dirname(config_path)

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    def resolve(p: str) -> str:
        if os.path.isabs(p):
            return p
        return os.path.join(base_dir, p)

    return SetupConfig(
        repo_path=raw["repo_path"],
        servers_file=resolve(raw["servers_file"]),
        credentials_file=resolve(raw["credentials_file"]),
        vsphere_host=raw["vsphere"]["host"],
        vsphere_port=raw["vsphere"].get("port", 443),
        postgres_host=raw["postgres"].get("host", "localhost"),
        postgres_port=raw["postgres"].get("port", 5432),
        postgres_db=raw["postgres"]["db_name"],
        postgres_user=raw["postgres"]["db_user"],
        postgres_password=raw["postgres"]["db_password"],
        lab_name=raw["lab"]["name"],
        lab_description=raw["lab"].get("description", ""),
        load_profiles=raw.get("load_profiles", []),
        discovery_file=resolve(raw["output"]["discovery_file"]),
        credentials_json_path=resolve(raw["output"]["credentials_json"]),
        create_ssh_key=raw.get("service_account", {}).get("create_ssh_key", False),
        base_dir=base_dir,
    )


def load_servers(servers_file: str) -> list[ServerEntry]:
    """Load servers.csv, skip comment lines starting with #.

    CSV columns: hostname, os, role [, ip]
    If 'ip' column is missing or empty, it's resolved from hostname via DNS.
    """
    servers = []
    with open(servers_file) as f:
        # Filter out comment lines
        lines = [line for line in f if not line.strip().startswith("#") and line.strip()]
        reader = csv.DictReader(lines)
        for row in reader:
            servers.append(ServerEntry(
                hostname=row["hostname"].strip(),
                os=row["os"].strip().lower(),
                role=row["role"].strip().lower(),
                ip=row.get("ip", "").strip(),
            ))
    return servers


def load_credentials(cred_file: str) -> Credentials:
    """Load mycred.txt and return a Credentials object."""
    entries = {}
    with open(cred_file) as f:
        lines = [line for line in f if not line.strip().startswith("#") and line.strip()]
        reader = csv.DictReader(lines)
        for row in reader:
            entries[row["entity"].strip().lower()] = row

    if "firsttime" not in entries:
        raise ValueError("mycred.txt must have a 'firsttime' entity row")
    if "vsphere" not in entries:
        raise ValueError("mycred.txt must have a 'vsphere' entity row")
    if "serviceaccount" not in entries:
        raise ValueError("mycred.txt must have a 'serviceaccount' entity row")

    return Credentials(
        firsttime_user=entries["firsttime"]["username"].strip(),
        firsttime_pass=entries["firsttime"]["password"].strip(),
        vsphere_user=entries["vsphere"]["username"].strip(),
        vsphere_pass=entries["vsphere"]["password"].strip(),
        svc_user=entries["serviceaccount"]["username"].strip(),
        svc_pass=entries["serviceaccount"]["password"].strip(),
    )


# ---------------------------------------------------------------------------
# SSH helper (Linux)
# ---------------------------------------------------------------------------

def ssh_run(host: str, username: str, password: str, commands: list[str],
            port: int = 22, timeout: int = 30) -> list[dict]:
    """Execute commands via SSH. Returns list of {cmd, stdout, stderr, rc}."""
    results = []
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=username, password=password,
                       timeout=timeout, look_for_keys=False, allow_agent=False)
        for cmd in commands:
            logger.info("  [SSH %s] %s", host, cmd)
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            results.append({"cmd": cmd, "stdout": out, "stderr": err, "rc": rc})
            if rc != 0:
                logger.warning("  [SSH %s] rc=%d stderr=%s", host, rc, err)
    finally:
        client.close()
    return results


# ---------------------------------------------------------------------------
# WinRM helper (Windows)
# ---------------------------------------------------------------------------

def winrm_run(host: str, username: str, password: str, commands: list[str],
              port: int = 5985, use_ssl: bool = False) -> list[dict]:
    """Execute PowerShell commands via WinRM. Returns list of {cmd, stdout, stderr, rc}."""
    results = []
    endpoint = f"{'https' if use_ssl else 'http'}://{host}:{port}/wsman"
    session = winrm.Session(
        endpoint,
        auth=(username, password),
        transport="ntlm",
        server_cert_validation="ignore",
    )
    for cmd in commands:
        logger.info("  [WinRM %s] %s", host, cmd)
        result = session.run_ps(cmd)
        rc = result.status_code
        out = result.std_out.decode("utf-8", errors="replace").strip()
        err = result.std_err.decode("utf-8", errors="replace").strip()
        results.append({"cmd": cmd, "stdout": out, "stderr": err, "rc": rc})
        if rc != 0:
            logger.warning("  [WinRM %s] rc=%d stderr=%s", host, rc, err)
    return results


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-5s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_servers(servers: list[ServerEntry]):
    """Validate server list has correct role assignments."""
    orchestrators = [s for s in servers if s.role == "orchestrator"]
    if len(orchestrators) != 1:
        raise ValueError(f"Expected exactly 1 orchestrator, found {len(orchestrators)}")

    orch = orchestrators[0]
    if not orch.is_linux:
        raise ValueError(f"Orchestrator must be Linux, got {orch.os}")

    loadgens = [s for s in servers if s.role == "loadgen"]
    for lg in loadgens:
        if not lg.is_linux:
            raise ValueError(f"Loadgen {lg.hostname} must be Linux, got {lg.os}")

    targets = [s for s in servers if s.role == "target"]
    if not targets:
        raise ValueError("Need at least 1 target server")

    logger.info("Servers validated: %d orchestrator, %d loadgen, %d target, %d unassigned",
                len(orchestrators), len(loadgens), len(targets),
                len([s for s in servers if s.role == "unassigned"]))
