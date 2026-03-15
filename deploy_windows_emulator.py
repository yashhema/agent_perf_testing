"""Deploy new emulator package to Windows target and start it."""
import http.server
import os
import socket
import threading
import time

import requests
import winrm

HOST = "10.0.0.91"
PKG_DIR = r"C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\orchestrator\artifacts\packages"
PKG_NAME = "emulator-windows.tar.gz"
INSTALL_DIR = r"C:\emulator"
HTTP_PORT = 9999


def get_my_ip():
    """Get local IP on the 10.0.0.0/24 network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("10.0.0.91", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def start_http_server():
    """Serve package files over HTTP."""
    os.chdir(PKG_DIR)
    handler = http.server.SimpleHTTPRequestHandler
    httpd = http.server.HTTPServer(("0.0.0.0", HTTP_PORT), handler)
    httpd.serve_forever()


def winrm_session():
    return winrm.Session(
        f"http://{HOST}:5985/wsman",
        auth=("Administrator", "Test1234!"),
        transport="ntlm",
    )


def run_ps(s, cmd, label=""):
    """Run PowerShell command and print results."""
    r = s.run_ps(cmd)
    out = r.std_out.decode().strip()
    err = r.std_err.decode().strip()
    # Filter CLIXML progress noise
    if err and "CLIXML" not in err[:20]:
        print(f"  [{label}] ERR: {err[:300]}")
    if out:
        print(f"  [{label}] {out[:500]}")
    return r


def run_cmd(s, cmd, label="", timeout_sec=30):
    """Run CMD command."""
    old_timeout = s.protocol.transport.read_timeout_sec
    s.protocol.transport.read_timeout_sec = timeout_sec
    try:
        r = s.run_cmd(cmd)
    finally:
        s.protocol.transport.read_timeout_sec = old_timeout
    out = r.std_out.decode().strip()
    err = r.std_err.decode().strip()
    if err:
        print(f"  [{label}] ERR: {err[:300]}")
    if out:
        print(f"  [{label}] {out[:500]}")
    return r


def main():
    my_ip = get_my_ip()
    print(f"My IP: {my_ip}")

    # Start HTTP server
    print(f"Starting HTTP server on :{HTTP_PORT}")
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()
    time.sleep(1)

    s = winrm_session()

    # Test connection
    r = s.run_cmd("hostname")
    print(f"Connected to: {r.std_out.decode().strip()}")

    # Stop existing emulator
    print("1. Stopping existing emulator...")
    run_ps(s, "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue", "stop")

    # Clean and create install dir
    print("2. Cleaning install dir...")
    run_ps(s, f'if (Test-Path "{INSTALL_DIR}") {{ Remove-Item -Recurse -Force "{INSTALL_DIR}" }}', "clean")
    run_ps(s, f'New-Item -ItemType Directory -Path "{INSTALL_DIR}" -Force | Out-Null', "mkdir")

    # Download package
    url = f"http://{my_ip}:{HTTP_PORT}/{PKG_NAME}"
    dest = f"{INSTALL_DIR}\\{PKG_NAME}"
    print(f"3. Downloading {url}")
    run_ps(s, f'Invoke-WebRequest -Uri "{url}" -OutFile "{dest}" -UseBasicParsing', "download")
    # Verify download
    r = run_ps(s, f'(Get-Item "{dest}").Length', "size")

    # Extract
    print("4. Extracting...")
    run_cmd(s, f'cd /d "{INSTALL_DIR}" && tar -xzf "{PKG_NAME}"', "extract", timeout_sec=120)
    run_cmd(s, f'del "{dest}"', "cleanup")

    # List contents
    print("5. Installed files:")
    run_ps(s, f'Get-ChildItem "{INSTALL_DIR}" | Format-Table Name, Length -AutoSize', "list")
    run_ps(s, f'Get-ChildItem "{INSTALL_DIR}\\data\\normal" -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count', "normal_count")
    run_ps(s, f'Get-ChildItem "{INSTALL_DIR}\\data\\confidential" -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count', "conf_count")

    # Check Python available
    print("6. Checking Python...")
    run_cmd(s, "python --version", "python")

    # Install pip deps
    print("7. Installing pip deps...")
    run_cmd(s, "pip install fastapi uvicorn psutil", "pip", timeout_sec=120)

    # Open firewall
    print("8. Opening firewall...")
    run_ps(s, 'New-NetFirewallRule -DisplayName Emulator_API -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null', "fw")

    # Start emulator
    print("9. Starting emulator...")
    run_ps(s, f'powershell -ExecutionPolicy Bypass -File "{INSTALL_DIR}\\start.ps1"', "start")

    # Check health
    print("10. Checking health...")
    time.sleep(3)
    try:
        resp = requests.get(f"http://{HOST}:8080/health", timeout=5)
        print(f"  Health: {resp.json()}")
    except Exception as e:
        print(f"  Health check failed: {e}")

    # Verify new code is present
    print("11. Verifying new code...")
    run_ps(s, f'Select-String -Path "{INSTALL_DIR}\\app\\config.py" -Pattern "_EMULATOR_ROOT" | Select-Object -First 1 -ExpandProperty Line', "config_check")
    run_ps(s, f'Select-String -Path "{INSTALL_DIR}\\app\\services\\file_builder.py" -Pattern "os.walk" | Select-Object -First 1 -ExpandProperty Line', "filebuilder_check")

    print("\nDone!")


if __name__ == "__main__":
    main()
