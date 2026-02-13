<#
.SYNOPSIS
    Check all prerequisites for Agent Performance Testing

.DESCRIPTION
    Validates that all required software is installed and configured.
    Reports what's missing and provides installation guidance.
#>

param(
    [switch]$Detailed
)

$ErrorActionPreference = "SilentlyContinue"
$script:AllPassed = $true

function Test-Requirement {
    param(
        [string]$Name,
        [scriptblock]$Test,
        [string]$SuccessMsg,
        [string]$FailMsg,
        [string]$FixInstructions
    )

    Write-Host -NoNewline "  Checking $Name... "

    try {
        $result = & $Test
        if ($result) {
            Write-Host "OK" -ForegroundColor Green
            if ($Detailed -and $SuccessMsg) {
                Write-Host "    $SuccessMsg" -ForegroundColor Gray
            }
            return $true
        }
    } catch {}

    Write-Host "MISSING" -ForegroundColor Red
    $script:AllPassed = $false
    if ($FailMsg) {
        Write-Host "    $FailMsg" -ForegroundColor Yellow
    }
    if ($FixInstructions) {
        Write-Host "    Fix: $FixInstructions" -ForegroundColor Cyan
    }
    return $false
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   Agent Performance Testing - Prerequisites Check" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1. Java
# ============================================================
Write-Host "[1] Java Runtime" -ForegroundColor Yellow

$javaVersion = $null
Test-Requirement -Name "Java" -Test {
    $result = java -version 2>&1
    $script:javaVersion = $result | Select-String -Pattern 'version "(\d+)' | ForEach-Object { $_.Matches.Groups[1].Value }
    return $script:javaVersion -ge 11
} -SuccessMsg "Java $javaVersion detected" `
  -FailMsg "Java 11+ is required for JMeter" `
  -FixInstructions "Download from https://adoptium.net/ or https://www.oracle.com/java/technologies/downloads/"

# ============================================================
# 2. Python
# ============================================================
Write-Host ""
Write-Host "[2] Python Environment" -ForegroundColor Yellow

$pythonVersion = $null
Test-Requirement -Name "Python 3.8+" -Test {
    $result = python --version 2>&1
    if ($result -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        $script:pythonVersion = "$major.$minor"
        return ($major -eq 3 -and $minor -ge 8) -or $major -gt 3
    }
    return $false
} -SuccessMsg "Python $pythonVersion" `
  -FailMsg "Python 3.8+ required" `
  -FixInstructions "Download from https://www.python.org/downloads/"

Test-Requirement -Name "pip" -Test {
    $result = pip --version 2>&1
    return $result -match "pip \d+"
} -FailMsg "pip not found" `
  -FixInstructions "Run: python -m ensurepip --upgrade"

# Check Python packages
$requiredPackages = @("sqlalchemy", "faker", "pyyaml", "pandas", "openpyxl", "click")
foreach ($pkg in $requiredPackages) {
    Test-Requirement -Name "Python: $pkg" -Test {
        $result = pip show $pkg 2>&1
        return $result -match "Name: $pkg"
    } -FixInstructions "Run: pip install $pkg"
}

# ============================================================
# 3. JMeter
# ============================================================
Write-Host ""
Write-Host "[3] Apache JMeter" -ForegroundColor Yellow

$jmeterPath = $null
$jmeterFound = Test-Requirement -Name "JMeter" -Test {
    $paths = @(
        $env:JMETER_HOME,
        "C:\apache-jmeter-5.6.3",
        "C:\apache-jmeter-5.6.2",
        "C:\apache-jmeter-5.6",
        "C:\apache-jmeter-5.5",
        "C:\Program Files\Apache JMeter"
    )
    foreach ($p in $paths) {
        if ($p -and (Test-Path "$p\bin\jmeter.bat")) {
            $script:jmeterPath = $p
            return $true
        }
    }
    return $false
} -SuccessMsg "Found at $jmeterPath" `
  -FailMsg "JMeter not found" `
  -FixInstructions "Download from https://jmeter.apache.org/download_jmeter.cgi and extract to C:\apache-jmeter-5.6.3"

# ============================================================
# 4. Database
# ============================================================
Write-Host ""
Write-Host "[4] Database Connectivity" -ForegroundColor Yellow

Test-Requirement -Name "SQL Server (sqlcmd)" -Test {
    $result = sqlcmd -? 2>&1
    return $result -match "sqlcmd"
} -FailMsg "sqlcmd not found (optional - for SQL Server)" `
  -FixInstructions "Install SQL Server command line tools"

Test-Requirement -Name "SQL Server Service" -Test {
    $service = Get-Service -Name "MSSQLSERVER" -ErrorAction SilentlyContinue
    if (-not $service) {
        $service = Get-Service -Name "MSSQL`$*" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    return $service -and $service.Status -eq "Running"
} -FailMsg "SQL Server service not running (optional)" `
  -FixInstructions "Start SQL Server service or use remote database"

# ============================================================
# 5. JDBC Drivers
# ============================================================
Write-Host ""
Write-Host "[5] JDBC Drivers" -ForegroundColor Yellow

$libDir = Join-Path $PSScriptRoot "..\lib\jdbc"
$jmeterLib = if ($jmeterPath) { Join-Path $jmeterPath "lib" } else { $null }

$jdbcDrivers = @{
    "mssql" = "mssql-jdbc*.jar"
    "postgresql" = "postgresql*.jar"
    "oracle" = "ojdbc*.jar"
    "db2" = "db2jcc*.jar"
}

foreach ($db in $jdbcDrivers.Keys) {
    $pattern = $jdbcDrivers[$db]
    Test-Requirement -Name "JDBC: $db" -Test {
        # Check local lib folder
        if (Test-Path $libDir) {
            $found = Get-ChildItem -Path $libDir -Filter $pattern -ErrorAction SilentlyContinue
            if ($found) { return $true }
        }
        # Check JMeter lib folder
        if ($jmeterLib -and (Test-Path $jmeterLib)) {
            $found = Get-ChildItem -Path $jmeterLib -Filter $pattern -ErrorAction SilentlyContinue
            if ($found) { return $true }
        }
        return $false
    } -FailMsg "Driver not found: $pattern" `
      -FixInstructions "Run: .\scripts\download_jdbc_drivers.ps1"
}

# ============================================================
# 6. Generated Files
# ============================================================
Write-Host ""
Write-Host "[6] Generated Files" -ForegroundColor Yellow

$baseDir = Split-Path $PSScriptRoot -Parent
$outputDir = Join-Path $baseDir "output"

Test-Requirement -Name "Schema files" -Test {
    Test-Path (Join-Path $outputDir "mssql\schema\00_create_database.sql")
} -FailMsg "Schema not generated" `
  -FixInstructions "Run: python -m generator.main schema -d mssql"

Test-Requirement -Name "Seed + Params" -Test {
    (Test-Path (Join-Path $outputDir "mssql\seed\seed_data.sql")) -and
    (Test-Path (Join-Path $outputDir "mssql\params\customer_ids.csv"))
} -FailMsg "Seed/Params not generated" `
  -FixInstructions "Run: python -m generator.main seed -d mssql"

Test-Requirement -Name "JMX files" -Test {
    Test-Path (Join-Path $outputDir "jmx\db-load-mssql.jmx")
} -FailMsg "JMX not generated" `
  -FixInstructions "Run: python -m generator.main jmx -d mssql"

# ============================================================
# Summary
# ============================================================
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan

if ($script:AllPassed) {
    Write-Host "  All prerequisites met! Ready to run tests." -ForegroundColor Green
} else {
    Write-Host "  Some prerequisites are missing. See above for fixes." -ForegroundColor Yellow
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Return status
exit $(if ($script:AllPassed) { 0 } else { 1 })
