# Prerequisite script for Java emulator on Windows Server 2022
# Installs Microsoft OpenJDK 17 via Invoke-WebRequest + MSI
#
# Tested on: Windows Server 2022 (TARGET-WIN-01, 10.0.0.91)
# winget is NOT available on Windows Server, so we download the MSI directly.
# Download URL: https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.msi (~168 MB)
# Install path: C:\Program Files\Microsoft\jdk-17.x.x-hotspot\

Write-Host "=== Java Emulator Prerequisites ==="

# ── Step 1: Check if Java 17+ is already installed ──────────────────────────
$javaFound = $false

# Check PATH first
try {
    $versionOutput = & java -version 2>&1 | Out-String
    if ($versionOutput -match '"(17|18|19|20|21)') {
        Write-Host "Java 17+ already in PATH:"
        Write-Host $versionOutput
        $javaFound = $true
    }
} catch {}

# Check standard install locations
if (-not $javaFound) {
    $standardPaths = @(
        "C:\Program Files\Microsoft\jdk-17*\bin\java.exe",
        "C:\Program Files\Java\jdk-17*\bin\java.exe",
        "C:\Program Files\Eclipse Adoptium\jre-17*\bin\java.exe",
        "C:\Program Files\Amazon Corretto\jdk17*\bin\java.exe"
    )
    foreach ($pattern in $standardPaths) {
        $found = Get-Item $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            Write-Host "Java 17+ found at: $($found.FullName)"
            & $found.FullName -version 2>&1 | ForEach-Object { Write-Host $_ }
            $javaFound = $true
            break
        }
    }
}

if ($javaFound) {
    Write-Host "=== Prerequisites complete (Java already installed) ==="
    exit 0
}

# ── Step 2: Download Microsoft OpenJDK 17 MSI ──────────────────────────────
Write-Host "Java 17 not found. Downloading Microsoft OpenJDK 17 MSI..."

$downloadDir = "C:\jdk_install"
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$msiUrl = "https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.msi"
$msiPath = Join-Path $downloadDir "jdk17.msi"

try {
    Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing
    $fileSize = (Get-Item $msiPath).Length
    Write-Host "Downloaded: $msiPath ($fileSize bytes)"
} catch {
    Write-Host "ERROR: Download failed: $_"
    exit 1
}

if ($fileSize -lt 1000000) {
    Write-Host "ERROR: Downloaded file too small ($fileSize bytes), likely failed"
    exit 1
}

# ── Step 3: Install MSI silently ────────────────────────────────────────────
Write-Host "Installing Microsoft OpenJDK 17..."
$installArgs = "/i `"$msiPath`" /quiet /norestart ADDLOCAL=FeatureMain,FeatureEnvironment,FeatureJarFileRunWith,FeatureJavaHome"
$proc = Start-Process msiexec.exe -ArgumentList $installArgs -Wait -PassThru -NoNewWindow
Write-Host "MSI installer exit code: $($proc.ExitCode)"

if ($proc.ExitCode -ne 0) {
    Write-Host "ERROR: MSI installation failed with exit code $($proc.ExitCode)"
    exit 1
}

# ── Step 4: Refresh PATH for current session ────────────────────────────────
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

# ── Step 5: Verify installation ─────────────────────────────────────────────
Write-Host "Verifying Java installation..."
$javaExe = Get-Item "C:\Program Files\Microsoft\jdk-17*\bin\java.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($javaExe) {
    Write-Host "Java installed at: $($javaExe.FullName)"
    & $javaExe.FullName -version 2>&1 | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "ERROR: Java not found after installation!"
    exit 1
}

# ── Step 6: Cleanup ────────────────────────────────────────────────────────
Write-Host "Cleaning up installer..."
Remove-Item $msiPath -Force -ErrorAction SilentlyContinue
Remove-Item $downloadDir -Force -Recurse -ErrorAction SilentlyContinue

Write-Host "=== Prerequisites complete ==="
