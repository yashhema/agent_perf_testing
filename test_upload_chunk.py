"""Test chunked WinRM upload using run_ps with small base64 chunks."""
import winrm
import base64
import os

HOST = "10.0.0.91"
USER = "Administrator"
PASS = "Test1234!"
CHUNK_SIZE = 1500  # raw bytes per chunk -> ~2KB base64

s = winrm.Session(f"http://{HOST}:5985/wsman", auth=(USER, PASS), transport="ntlm")

# Use the actual emulator package
pkg_path = os.path.join(os.path.dirname(__file__),
    "orchestrator", "artifacts", "packages", "emulator-windows.tar.gz")
with open(pkg_path, "rb") as f:
    content = f.read()
print(f"File size: {len(content)} bytes")

remote_path = "C:/emulator-pkg/emulator-windows.tar.gz"

# Step 1: Create directory
r = s.run_ps("New-Item -ItemType Directory -Force -Path 'C:/emulator-pkg' | Out-Null")
print(f"mkdir: rc={r.status_code}")

# Step 2: Write first chunk (creates the file)
encoded = base64.b64encode(content).decode("ascii")
chunks = [encoded[i:i+2000] for i in range(0, len(encoded), 2000)]
print(f"Total base64 length: {len(encoded)}, chunks: {len(chunks)}")

# Write chunk 0 - create file
r = s.run_ps(f"Set-Content -Path '{remote_path}.b64' -Value '{chunks[0]}' -NoNewline")
print(f"chunk 0: rc={r.status_code}, err={r.std_err.decode().strip()[:100]}")

# Append remaining chunks
for i, chunk in enumerate(chunks[1:], 1):
    r = s.run_ps(f"Add-Content -Path '{remote_path}.b64' -Value '{chunk}' -NoNewline")
    if r.status_code != 0:
        print(f"chunk {i} FAILED: {r.std_err.decode().strip()[:200]}")
        break
    if i % 5 == 0:
        print(f"  chunk {i}/{len(chunks)} OK")

print(f"All chunks written")

# Step 3: Decode base64 file
r = s.run_ps(f"""
$b64 = Get-Content -Path '{remote_path}.b64' -Raw
$bytes = [Convert]::FromBase64String($b64)
[IO.File]::WriteAllBytes('{remote_path}', $bytes)
Remove-Item '{remote_path}.b64' -Force
Write-Output "Decoded $($bytes.Length) bytes"
""")
print(f"Decode: rc={r.status_code}, out={r.std_out.decode().strip()}, err={r.std_err.decode().strip()[:200]}")

# Step 4: Verify
r = s.run_ps(f"(Get-Item '{remote_path}').Length")
print(f"Remote file size: {r.std_out.decode().strip()}")
print(f"Expected: {len(content)}")
