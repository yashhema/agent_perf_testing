# Java Emulator startup script for Windows
# Equivalent to Python emulator's start.ps1

$ErrorActionPreference = "Continue"
$emulatorDir = "C:\emulator"

Set-Location $emulatorDir

# Create required directories
New-Item -ItemType Directory -Force -Path "$emulatorDir\output" | Out-Null
New-Item -ItemType Directory -Force -Path "$emulatorDir\stats" | Out-Null

# Firewall rule
$rule = Get-NetFirewallRule -DisplayName "Emulator API" -ErrorAction SilentlyContinue
if (-not $rule) {
    Write-Host "Adding firewall rule for port 8080..."
    New-NetFirewallRule -DisplayName "Emulator API" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow | Out-Null
}

# Kill existing java processes on port 8080
Write-Host "Stopping any existing emulator processes..."
Get-Process -Name java -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Find Java
$javaExe = $null

# Check bundled JRE first
$bundledJre = Join-Path $emulatorDir "jre\bin\java.exe"
if (Test-Path $bundledJre) {
    $javaExe = $bundledJre
    Write-Host "Using bundled JRE: $javaExe"
} else {
    # Check standard install locations
    $standardPaths = @(
        "C:\Program Files\Java\jdk-17\bin\java.exe",
        "C:\Program Files\Eclipse Adoptium\jre-17*\bin\java.exe",
        "C:\Program Files\Microsoft\jdk-17*\bin\java.exe",
        "C:\Program Files\Java\jre-17*\bin\java.exe"
    )
    foreach ($pattern in $standardPaths) {
        $found = Get-Item $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $javaExe = $found.FullName
            Write-Host "Using system Java: $javaExe"
            break
        }
    }

    # Check PATH
    if (-not $javaExe) {
        $javaExe = (Get-Command java -ErrorAction SilentlyContinue).Source
        if ($javaExe) {
            Write-Host "Using Java from PATH: $javaExe"
        }
    }
}

if (-not $javaExe) {
    Write-Host "ERROR: Java not found. Install Adoptium JRE 17 or bundle jre/ in emulator package."
    exit 1
}

# Verify Java
& $javaExe -version 2>&1 | ForEach-Object { Write-Host $_ }

# Build command
$jarPath = Join-Path $emulatorDir "emulator.jar"
if (-not (Test-Path $jarPath)) {
    Write-Host "ERROR: emulator.jar not found at $jarPath"
    exit 1
}

# Calculate JVM heap: total RAM minus 2 GB for OS, minimum 1 GB
$totalRamMB = [math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)
$reserveMB = 2048
$heapMB = $totalRamMB - $reserveMB
if ($heapMB -lt 1024) { $heapMB = 1024 }
Write-Host "System RAM: ${totalRamMB} MB, JVM heap: ${heapMB} MB (reserving ${reserveMB} MB for OS)"

# Write a batch file to launch the emulator — avoids quoting issues with paths
# containing spaces (e.g. "C:\Program Files\...") when passed through WMI Create()
$batchContent = @"
@echo off
cd /d $emulatorDir
"$javaExe" -Xmx${heapMB}m -jar emulator.jar --server.port=8080 > emulator.log 2> emulator_err.log
"@
$batchPath = Join-Path $emulatorDir "run_emulator.bat"
Set-Content -Path $batchPath -Value $batchContent -Encoding ASCII

Write-Host "Starting Java emulator via WMI..."
$cmd = "cmd.exe /c $batchPath"
$process = ([wmiclass]"Win32_Process").Create($cmd, $emulatorDir, $null)

if ($process.ReturnValue -ne 0) {
    Write-Host "ERROR: Failed to start process (return code: $($process.ReturnValue))"
    exit 1
}

Write-Host "Process created with PID: $($process.ProcessId)"

# Verify process is alive after 3 seconds
Start-Sleep -Seconds 3
$proc = Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Host "ERROR: Process died within 3 seconds. Check emulator_err.log"
    if (Test-Path "$emulatorDir\emulator_err.log") {
        Get-Content "$emulatorDir\emulator_err.log" -Tail 20
    }
    exit 1
}

# Health check (30s for Spring Boot startup)
Write-Host "Waiting for emulator to start..."
for ($i = 0; $i -lt 30; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host "Emulator started successfully (took $($i + 3)s)"
            exit 0
        }
    } catch {
        # Not ready yet
    }
    Start-Sleep -Seconds 1
}

Write-Host "WARNING: Health check failed after 30s. Check emulator.log and emulator_err.log"
exit 1
