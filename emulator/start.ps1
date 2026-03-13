# Start the emulator service in background on Windows.
# WinRM-safe: uses WMI Win32_Process.Create to fully detach from the calling session.
# Health checks are done separately via status_command — this script only starts the process.
$ErrorActionPreference = "Stop"

$emulatorDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $emulatorDir

# Create output and stats directories
New-Item -ItemType Directory -Force -Path "C:\emulator\output" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\emulator\stats" | Out-Null

# Ensure firewall allows inbound on port 8080
$fwRule = Get-NetFirewallRule -DisplayName "Emulator API" -ErrorAction SilentlyContinue
if (-not $fwRule) {
    New-NetFirewallRule -DisplayName "Emulator API" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow | Out-Null
    Write-Host "Firewall rule created for port 8080"
}

# Kill existing emulator if running
Get-Process -Name python* -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Find python.exe — check both standard install and PATH
$pythonExe = $null
foreach ($candidate in @(
    "C:\Program Files\Python311\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python312\python.exe"
)) {
    if (Test-Path $candidate) { $pythonExe = $candidate; break }
}
if (-not $pythonExe) {
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $pythonExe) {
    Write-Host "ERROR: python.exe not found"
    exit 1
}
Write-Host "Using Python: $pythonExe"

# Verify uvicorn is importable
$uvCheck = & "$pythonExe" -c "import uvicorn; print('ok')" 2>&1
Write-Host "uvicorn check: $uvCheck"
if ("$uvCheck" -notlike "*ok*") {
    Write-Host "ERROR: uvicorn not importable"
    exit 1
}

# Use WMI to create a fully detached process (WinRM-safe — no handle inheritance)
# Wrap in cmd.exe /c to redirect stdout/stderr to log files
$logOut = "C:\emulator\emulator.log"
$logErr = "C:\emulator\emulator_err.log"
$cmdLine = "cmd.exe /c `"`"$pythonExe`" -m uvicorn app.main:create_app --host 0.0.0.0 --port 8080 --factory > `"$logOut`" 2> `"$logErr`"`""

$startupInfo = ([wmiclass]"Win32_ProcessStartup").CreateInstance()
$startupInfo.ShowWindow = 0  # Hidden

$result = ([wmiclass]"Win32_Process").Create($cmdLine, $emulatorDir, $startupInfo)
if ($result.ReturnValue -ne 0) {
    Write-Host "ERROR: WMI process creation failed (return=$($result.ReturnValue))"
    exit 1
}
$procId = $result.ProcessId
Write-Host "Emulator process created via WMI (pid=$procId)"

# Brief pause to let process initialize, then verify it's still alive
Start-Sleep -Seconds 3
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Host "ERROR: Process $procId died immediately"
    Write-Host "=== stdout log ==="
    if (Test-Path $logOut) { Get-Content $logOut -ErrorAction SilentlyContinue }
    Write-Host "=== stderr log ==="
    if (Test-Path $logErr) { Get-Content $logErr -ErrorAction SilentlyContinue }
    exit 1
}

Write-Host "Emulator started successfully (pid=$procId)"
exit 0
