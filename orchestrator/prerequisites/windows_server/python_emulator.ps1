# Install Python3 + emulator dependencies on Windows Server if not present.
# Idempotent — skips if Python and packages are already available.
$ErrorActionPreference = "Stop"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}

if (-not $pythonCmd) {
    Write-Host "Python not found — installing Python 3.11..."

    $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $tempExe = "$env:TEMP\python-3.11.9-amd64.exe"

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $pyUrl -OutFile $tempExe -UseBasicParsing

    Start-Process $tempExe -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait -NoNewWindow
    Remove-Item $tempExe -Force -ErrorAction SilentlyContinue

    # Refresh PATH
    $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
    Write-Host "Python installed: $(python --version)"
} else {
    Write-Host "Python already installed: $($pythonCmd.Source)"
}

# Install emulator runtime dependencies
$required = @("fastapi", "uvicorn", "pydantic", "psutil")
foreach ($pkg in $required) {
    $check = python -c "import $pkg" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "$pkg already installed"
    } else {
        Write-Host "Installing $pkg..."
        python -m pip install -q $pkg
    }
}

Write-Host "Python emulator prerequisites installed successfully"
