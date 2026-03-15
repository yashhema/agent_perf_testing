"""Full Windows emulator deploy: upload, extract, prereq (bundled Python), start, verify."""
import http.server
import os
import socket
import threading
import time
import requests
import winrm

HOST = "10.0.0.91"
PKG_DIR = r"C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\orchestrator\artifacts\packages"
PREREQ_DIR = r"C:\OfficeWork\Claude_understanding\FinalDocs\agent_perf_testing\orchestrator\prerequisites\windows_server"
PKG_NAME = "emulator-windows.tar.gz"
PREREQ_NAME = "python_emulator.ps1"
HTTP_PORT = 9999
PWD = "Test1234!"


def get_my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("10.0.0.91", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def serve_http():
    """Serve both packages and prereqs."""
    # We'll serve from a temp dir with symlinks/copies
    import shutil
    serve_dir = os.path.join(os.environ.get("TEMP", "/tmp"), "emu_serve")
    os.makedirs(serve_dir, exist_ok=True)
    # Copy package and prereq to serve dir
    shutil.copy2(os.path.join(PKG_DIR, PKG_NAME), serve_dir)
    shutil.copy2(os.path.join(PREREQ_DIR, PREREQ_NAME), serve_dir)
    os.chdir(serve_dir)
    httpd = http.server.HTTPServer(("0.0.0.0", HTTP_PORT), http.server.SimpleHTTPRequestHandler)
    httpd.serve_forever()


def sess():
    return winrm.Session(f"http://{HOST}:5985/wsman", auth=("Administrator", PWD), transport="ntlm")


def ps(s, cmd, label="", timeout=60):
    old = s.protocol.transport.read_timeout_sec
    s.protocol.transport.read_timeout_sec = timeout
    try:
        r = s.run_ps(cmd)
    finally:
        s.protocol.transport.read_timeout_sec = old
    out = r.std_out.decode().strip()
    err = r.std_err.decode().strip()
    if out:
        print(f"  [{label}] {out[-800:]}")
    # Filter CLIXML progress noise
    clean_err = ""
    if err:
        for line in err.split("\n"):
            if "CLIXML" not in line and "<Obj" not in line and "<TN" not in line and "</MS>" not in line and "<I64" not in line and "<PR " not in line and "</TN>" not in line and "</Obj" not in line and "<MS>" not in line and "<AV>" not in line and "<AI>" not in line and "</PR>" not in line and "<Objs" not in line and "</Objs>" not in line and "<S " not in line and "<T>" not in line and "</T>" not in line:
                clean_err += line + "\n"
        clean_err = clean_err.strip()
        if clean_err:
            print(f"  [{label}] ERR: {clean_err[:400]}")
    return r


def run_cmd(s, command, label="", timeout=60):
    old = s.protocol.transport.read_timeout_sec
    s.protocol.transport.read_timeout_sec = timeout
    try:
        r = s.run_cmd(command)
    finally:
        s.protocol.transport.read_timeout_sec = old
    out = r.std_out.decode().strip()
    err = r.std_err.decode().strip()
    if out:
        print(f"  [{label}] {out[-600:]}")
    if err:
        print(f"  [{label}] ERR: {err[:300]}")
    return r


def main():
    my_ip = get_my_ip()
    print(f"Dev IP: {my_ip}")

    threading.Thread(target=serve_http, daemon=True).start()
    time.sleep(1)

    s = sess()
    r = s.run_cmd("hostname")
    print(f"Connected: {r.std_out.decode().strip()}")

    # 1. Download + extract package
    print("\n=== 1. Deploy package ===")
    url = f"http://{my_ip}:{HTTP_PORT}/{PKG_NAME}"
    ps(s, f"""
New-Item -ItemType Directory -Path 'C:\\emulator' -Force | Out-Null
Invoke-WebRequest -Uri '{url}' -OutFile 'C:\\emulator\\{PKG_NAME}' -UseBasicParsing
(Get-Item 'C:\\emulator\\{PKG_NAME}').Length
""", "download", timeout=120)

    run_cmd(s, f'cmd /c "cd /d C:\\emulator && tar -xzf {PKG_NAME}"', "extract", timeout=120)
    run_cmd(s, f'del "C:\\emulator\\{PKG_NAME}"', "rm-tar")

    # Verify
    ps(s, "Get-ChildItem 'C:\\emulator' | Format-Table Name -AutoSize", "contents")
    ps(s, "Test-Path 'C:\\emulator\\installers\\python-3.11.9-amd64.exe'", "has-installer")

    # 2. Run prereq (installs Python from bundled installer + pip deps)
    print("\n=== 2. Run prereq (Python + deps) ===")
    # Download prereq script
    prereq_url = f"http://{my_ip}:{HTTP_PORT}/{PREREQ_NAME}"
    ps(s, f"Invoke-WebRequest -Uri '{prereq_url}' -OutFile 'C:\\emulator\\prereq.ps1' -UseBasicParsing", "dl-prereq")
    ps(s, "powershell -ExecutionPolicy Bypass -File 'C:\\emulator\\prereq.ps1'", "prereq", timeout=300)

    # 3. Firewall
    print("\n=== 3. Firewall ===")
    ps(s, "New-NetFirewallRule -DisplayName Emulator_API -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow -ErrorAction SilentlyContinue | Out-Null; Write-Output 'OK'", "fw")

    # 4. Start emulator
    print("\n=== 4. Start emulator ===")
    ps(s, "powershell -ExecutionPolicy Bypass -File 'C:\\emulator\\start.ps1'", "start", timeout=30)

    # 5. Health check
    print("\n=== 5. Health check ===")
    time.sleep(3)
    ok = False
    for attempt in range(5):
        try:
            resp = requests.get(f"http://{HOST}:8080/health", timeout=5)
            print(f"  HEALTH: {resp.json()}")
            ok = True
            break
        except Exception as e:
            print(f"  Attempt {attempt+1}: {e}")
            time.sleep(3)

    if not ok:
        print("  FAILED — checking logs")
        ps(s, "Get-Content 'C:\\emulator\\emulator_err.log' -Tail 30 -ErrorAction SilentlyContinue", "errlog")
        ps(s, "Get-Content 'C:\\emulator\\emulator.log' -Tail 10 -ErrorAction SilentlyContinue", "log")
        return False

    print("\n=== WINDOWS EMULATOR DEPLOYED AND RUNNING ===")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
