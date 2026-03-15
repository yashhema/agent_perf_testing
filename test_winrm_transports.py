"""Test all WinRM transport options to find what works on fresh VM."""
import winrm

HOST = "10.0.0.91"
USER = "Administrator"
PASS = "Test1234!"

for transport in ["ntlm", "basic", "plaintext"]:
    print(f"\n=== Transport: {transport} ===")
    try:
        s = winrm.Session(
            f"http://{HOST}:5985/wsman",
            auth=(USER, PASS),
            transport=transport,
        )
        r = s.run_cmd("hostname")
        print(f"  OK: {r.std_out.decode().strip()}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:150]}")
