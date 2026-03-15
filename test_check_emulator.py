"""Check emulator deployment state on Windows target."""
import winrm

s = winrm.Session('http://10.0.0.91:5985/wsman', auth=('Administrator', 'Test1234!'), transport='ntlm')

print("=== Emulator files ===")
r = s.run_cmd('dir C:\\emulator')
print(r.std_out.decode().strip())

print("\n=== requirements.txt ===")
r = s.run_cmd('type C:\\emulator\\requirements.txt')
print(r.std_out.decode().strip())

print("\n=== Installed pip packages ===")
r = s.run_cmd('pip list')
print(r.std_out.decode().strip())

print("\n=== Try starting emulator ===")
r = s.run_cmd('cd /d C:\\emulator && python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --timeout-keep-alive 5 &')
import time
time.sleep(3)

print("\n=== Health check ===")
r = s.run_ps("try { (Invoke-WebRequest -Uri http://localhost:8080/health -UseBasicParsing -TimeoutSec 5).Content } catch { $_.Exception.Message }")
print(f"rc={r.status_code}, out={r.std_out.decode().strip()[:200]}")
