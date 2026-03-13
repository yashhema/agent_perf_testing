# Install Python3 + emulator dependencies on Windows Server if not present.
# Idempotent - skips if Python and packages are already available.
# Python installer is bundled in the package under installers/ (no internet needed).
$ErrorActionPreference = "Stop"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}

if (-not $pythonCmd) {
    Write-Host "Python not found - installing from bundled installer..."

    # Installer is bundled in the emulator package under C:\emulator\installers\
    $installerDir = "C:\emulator\installers"
    $installer = Get-ChildItem -Path $installerDir -Filter "python-*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1

    if (-not $installer) {
        Write-Error "No Python installer found in $installerDir. Ensure emulator package is extracted first."
        exit 1
    }

    Write-Host "Using installer: $($installer.FullName)"
    Start-Process $installer.FullName -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait -NoNewWindow

    # Refresh PATH
    $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
    Write-Host "Python installed: $(python --version)"
} else {
    Write-Host "Python already installed: $($pythonCmd.Source)"
}

# Install emulator runtime dependencies
# Temporarily relax error preference so failed import checks don't terminate
$ErrorActionPreference = "Continue"
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
$ErrorActionPreference = "Stop"

Write-Host "Python emulator prerequisites installed successfully"
