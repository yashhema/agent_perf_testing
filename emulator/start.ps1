# Start the emulator service in background on Windows.
# Creates required directories and starts uvicorn.
$ErrorActionPreference = "Stop"

$emulatorDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $emulatorDir

# Create required directories
New-Item -ItemType Directory -Force -Path "C:\emulator\data\normal" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\emulator\data\confidential" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\emulator\output" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\emulator\stats" | Out-Null

# Create sample input files if they don't exist
if (-not (Test-Path "C:\emulator\data\normal\sample.txt")) {
    [System.IO.File]::WriteAllBytes("C:\emulator\data\normal\sample.txt", (1..10240 | ForEach-Object { Get-Random -Maximum 256 }))
}
if (-not (Test-Path "C:\emulator\data\confidential\secret.txt")) {
    [System.IO.File]::WriteAllBytes("C:\emulator\data\confidential\secret.txt", (1..5120 | ForEach-Object { Get-Random -Maximum 256 }))
}

# Kill existing emulator if running
Get-Process -Name python* -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Start emulator in background
$proc = Start-Process python -ArgumentList "-m uvicorn app.main:create_app --host 0.0.0.0 --port 8080 --factory" `
    -WorkingDirectory $emulatorDir -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "C:\emulator\emulator.log" -RedirectStandardError "C:\emulator\emulator_err.log"

# Wait for startup
for ($i = 0; $i -lt 15; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host "Emulator started successfully (pid=$($proc.Id))"
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 1
}

Write-Host "ERROR: Emulator failed to start within 15s"
Get-Content "C:\emulator\emulator.log" -ErrorAction SilentlyContinue
exit 1
