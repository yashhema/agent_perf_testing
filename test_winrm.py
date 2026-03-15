"""Standalone test: WinRM upload/download on Windows target using orchestrator code paths."""
import winrm
import base64
import sys

HOST = "10.0.0.91"
USER = "Administrator"
PASS = "Test1234!"

s = winrm.Session(
    f"http://{HOST}:5985/wsman",
    auth=(USER, PASS),
    transport="ntlm",
)

# Test 1: run_cmd
print("=== Test 1: run_cmd ===")
r = s.run_cmd("hostname")
print(f"  hostname: {r.std_out.decode().strip()}, rc={r.status_code}")

# Test 2: run_ps
print("\n=== Test 2: run_ps ===")
r = s.run_ps("$env:COMPUTERNAME")
print(f"  computername: {r.std_out.decode().strip()}, rc={r.status_code}")

# Test 3: Create directory via run_ps
print("\n=== Test 3: mkdir via run_ps ===")
r = s.run_ps("New-Item -ItemType Directory -Force -Path 'C:\\temp' | Out-Null; Test-Path 'C:\\temp'")
print(f"  rc={r.status_code}, out={r.std_out.decode().strip()}, err={r.std_err.decode().strip()[:200]}")

# Test 4: Upload file (same as orchestrator upload method)
print("\n=== Test 4: Upload via run_ps (orchestrator method) ===")
test_content = b"Hello from orchestrator test - upload works!"
encoded = base64.b64encode(test_content).decode("ascii")
remote_path = "C:\\temp\\test_upload.txt"
ps_script = f'[IO.File]::WriteAllBytes("{remote_path}", [Convert]::FromBase64String("{encoded}"))'
print(f"  ps_script (first 80): {ps_script[:80]}")
r = s.run_ps(ps_script)
print(f"  rc={r.status_code}, err={r.std_err.decode().strip()[:200]}")

# Test 5: Download file (same as orchestrator download method)
print("\n=== Test 5: Download via run_ps (orchestrator method) ===")
ps_script = f'[Convert]::ToBase64String([IO.File]::ReadAllBytes("{remote_path}"))'
r = s.run_ps(ps_script)
if r.status_code == 0:
    downloaded = base64.b64decode(r.std_out.decode().strip())
    print(f"  Downloaded: {downloaded.decode()}")
else:
    print(f"  FAILED: {r.std_err.decode().strip()[:200]}")

# Test 6: Cleanup
print("\n=== Test 6: Cleanup ===")
r = s.run_ps("Remove-Item 'C:\\temp\\test_upload.txt' -Force -ErrorAction SilentlyContinue")
print(f"  cleanup rc={r.status_code}")

print("\n=== ALL TESTS DONE ===")
