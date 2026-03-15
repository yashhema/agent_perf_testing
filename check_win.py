import winrm
s = winrm.Session("http://10.0.0.91:5985/wsman", auth=("Administrator", "Test1234!"), transport="ntlm")
# Check if python installed
r = s.run_cmd("cmd", ["/c", "dir", "C:\\emulator"])
print("DIR:", r.std_out.decode()[:500])
r = s.run_cmd("cmd", ["/c", "dir", "C:\\emulator\\installers"])
print("INSTALLERS:", r.std_out.decode()[:500])
r = s.run_cmd("python", ["--version"])
print("PYTHON:", r.std_out.decode().strip(), "ERR:", r.std_err.decode().strip()[:200])
# Check running processes
r = s.run_cmd("tasklist", ["/fi", "imagename eq python*"])
print("PROCS:", r.std_out.decode()[:300])
