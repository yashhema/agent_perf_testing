# Workfile — Source Code Changes Log

All source code changes made during test plan execution are logged here.

| # | Date | File(s) Changed | Reason | Change Summary | Commit |
|---|------|-----------------|--------|----------------|--------|
| 1 | 2026-03-09 | `orchestrator/src/orchestrator/infra/remote_executor.py` | WinRM file transfer fails for large files | Rewrote WinRMExecutor.upload: HTTP pull for >4KB files, inline base64 for small files; added UTF-8 BOM for .ps1; added orchestrator_url param to factory | pending |
| 2 | 2026-03-09 | `orchestrator/src/orchestrator/app.py` | WinRM targets need HTTP access to packages | Added static file mounts for /packages and /prerequisites directories | pending |
| 3 | 2026-03-09 | `orchestrator/prerequisites/windows_server/python_emulator.ps1` | Em-dash chars corrupt PowerShell 5.1 parsing | Replaced em-dashes with ASCII dashes; wrapped import checks with ErrorActionPreference=Continue | pending |
| 4 | 2026-03-09 | `orchestrator/prerequisites/windows_server/java_jre.ps1` | Em-dash chars corrupt PowerShell 5.1 parsing | Replaced em-dashes with ASCII dashes | pending |
| 5 | 2026-03-09 | `orchestrator/scripts/setup_proxmox_lab.py` | Package deployment paths/commands incorrect | Fixed root_install_path (added filename), extraction_command (mkdir + tar instead of Expand-Archive), install/run commands for all 3 packages | pending |
| 6 | 2026-03-09 | `orchestrator/scripts/setup_proxmox_lab.py` | Linux emulator tar extracts nested directory | Added --strip-components=1 to Linux emulator extraction_command | pending |
| 7 | 2026-03-09 | `orchestrator/prerequisites/rhel/python_emulator.sh`, `orchestrator/prerequisites/rhel/java_jre.sh` | tar missing on minimal Rocky 9 installs | Added tar install check to both RHEL prereq scripts | pending |
