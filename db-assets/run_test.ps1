<#
.SYNOPSIS
    Master script to run Agent Performance Tests

.DESCRIPTION
    Complete workflow:
    1. Check prerequisites
    2. Generate all files (schema, seed+params, queries, JMX)
    3. Setup database
    4. Run JMeter test
    5. Generate results report

.PARAMETER Action
    What to do: check, generate, setup-db, run-test, full

.PARAMETER DbType
    Database: mssql, postgresql

.PARAMETER DbHost
    Database host (default: localhost)

.PARAMETER Threads
    Number of concurrent threads (default: 10)

.PARAMETER Duration
    Test duration in seconds (default: 300)

.EXAMPLE
    # Full setup and test (SQL Server with Windows Auth)
    .\run_test.ps1 -Action full -DbType mssql -TrustedConnection

.EXAMPLE
    # Just run test (database already set up)
    .\run_test.ps1 -Action run-test -DbType mssql -Threads 20 -Duration 600
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("check", "generate", "setup-db", "run-test", "full", "help")]
    [string]$Action = "help",

    [ValidateSet("mssql", "postgresql", "oracle", "db2")]
    [string]$DbType = "mssql",

    [string]$DbHost = "localhost",
    [string]$DbPort = "",
    [string]$DbName = "agent_performance_measurement",
    [string]$DbUser = "",
    [string]$DbPassword = "",

    [int]$Threads = 10,
    [int]$RampUp = 60,
    [int]$Duration = 300,

    [string]$JMeterHome = $env:JMETER_HOME,
    [string]$ResultsDir = "",

    [switch]$TrustedConnection,
    [switch]$SkipDbSetup,
    [switch]$GUI
)

$ErrorActionPreference = "Stop"
$BaseDir = $PSScriptRoot
$ScriptsDir = Join-Path $BaseDir "scripts"
$OutputDir = Join-Path $BaseDir "output"

# Colors
function Write-Step { param($msg) Write-Host "`n========== $msg ==========" -ForegroundColor Cyan }
function Write-OK { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Show-Help {
    Write-Host @"

================================================================================
             AGENT PERFORMANCE MEASUREMENT - TEST RUNNER
================================================================================

DATABASE: agent_performance_measurement

USAGE:
  .\run_test.ps1 -Action <action> -DbType <db> [options]

ACTIONS:
  check       Check prerequisites (Java, Python, JMeter, JDBC drivers)
  generate    Generate all files (schema, seed+params, queries, JMX)
  setup-db    Setup database (create + populate)
  run-test    Run JMeter load test
  full        Do everything: check -> generate -> setup-db -> run-test

OPTIONS:
  -DbType           Database type: mssql, postgresql, oracle, db2
  -DbHost           Database host (default: localhost)
  -DbPort           Database port (auto-detected if not specified)
  -DbName           Database name (default: agent_performance_measurement)
  -TrustedConnection Use Windows Auth for SQL Server
  -Threads          Concurrent threads (default: 10)
  -RampUp           Ramp-up seconds (default: 60)
  -Duration         Test duration seconds (default: 300)
  -JMeterHome       Path to JMeter installation
  -ResultsDir       Custom results directory
  -GUI              Open JMeter in GUI mode (for debugging)
  -SkipDbSetup      Skip database setup in 'full' action

EXAMPLES:
  # Check everything is ready
  .\run_test.ps1 -Action check

  # Full test with SQL Server (Windows Auth)
  .\run_test.ps1 -Action full -DbType mssql -TrustedConnection

  # Just run test (5 min, 20 threads)
  .\run_test.ps1 -Action run-test -DbType mssql -Threads 20 -Duration 300

  # Generate files only
  .\run_test.ps1 -Action generate -DbType mssql

RESULTS:
  Results are saved to: results/<dbtype>/<timestamp>/
    - results.jtl         JMeter raw results
    - jmeter.log          JMeter log
    - html-report/        HTML dashboard
    - run_command.txt     Exact command used

================================================================================
"@
}

function Invoke-Check {
    Write-Step "Checking Prerequisites"
    & "$ScriptsDir\check_prerequisites.ps1"
    return $LASTEXITCODE -eq 0
}

function Invoke-Generate {
    Write-Step "Generating All Files"

    Push-Location $BaseDir
    try {
        Write-Host "Generating for $DbType..."
        Write-Host ""

        # Generate all at once
        python -m generator.main all -d $DbType

        if ($LASTEXITCODE -eq 0) {
            Write-OK "All files generated successfully"
            Write-Host ""
            Write-Host "Output:" -ForegroundColor Yellow
            Write-Host "  Schema:  $OutputDir\$DbType\schema\"
            Write-Host "  Seed:    $OutputDir\$DbType\seed\"
            Write-Host "  Params:  $OutputDir\$DbType\params\"
            Write-Host "  JMX:     $OutputDir\jmx\"
            return $true
        } else {
            Write-Err "Generation failed"
            return $false
        }
    } finally {
        Pop-Location
    }
}

function Invoke-SetupDb {
    Write-Step "Setting Up Database: $DbName"

    $schemaDir = Join-Path $OutputDir "$DbType\schema"
    $seedDir = Join-Path $OutputDir "$DbType\seed"

    if (-not (Test-Path $schemaDir)) {
        Write-Err "Schema files not found. Run 'generate' first."
        return $false
    }

    if ($DbType -eq "mssql") {
        $connArgs = "-S $DbHost"
        if ($TrustedConnection) {
            $connArgs += " -E"
        } else {
            if (-not $DbUser) { $DbUser = Read-Host "SQL Server username" }
            if (-not $DbPassword) {
                $secPass = Read-Host "SQL Server password" -AsSecureString
                $DbPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPass))
            }
            $connArgs += " -U $DbUser -P $DbPassword"
        }

        # Run scripts in order
        $scripts = @(
            @{ File = "00_create_database.sql"; UseDb = $false },
            @{ File = "01_create_tables.sql"; UseDb = $true },
            @{ File = "02_create_indexes.sql"; UseDb = $true },
            @{ File = "03_create_constraints.sql"; UseDb = $true },
            @{ File = "04_create_users.sql"; UseDb = $true }
        )

        foreach ($script in $scripts) {
            $scriptPath = Join-Path $schemaDir $script.File
            if (Test-Path $scriptPath) {
                Write-Host "  Running $($script.File)..."
                $args = $connArgs
                if ($script.UseDb) { $args += " -d $DbName" }
                $cmd = "sqlcmd $args -i `"$scriptPath`" -b"
                $output = cmd /c $cmd 2>&1
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn "$($script.File) may have issues"
                    if ($output) { Write-Host "    $output" -ForegroundColor Gray }
                } else {
                    Write-OK "$($script.File)"
                }
            }
        }

        # Seed data
        $seedFile = Join-Path $seedDir "seed_data.sql"
        if (Test-Path $seedFile) {
            Write-Host "  Loading seed data (this may take a while)..."
            $cmd = "sqlcmd $connArgs -d $DbName -i `"$seedFile`" -b"
            cmd /c $cmd 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-OK "Seed data loaded"
            } else {
                Write-Warn "Seed data may have had issues"
            }
        }

        Write-OK "Database setup complete: $DbName"
        return $true
    } else {
        Write-Host ""
        Write-Host "For $DbType, run these scripts manually:" -ForegroundColor Yellow
        Get-ChildItem $schemaDir -Filter "*.sql" | Sort-Object Name | ForEach-Object {
            Write-Host "  $($_.FullName)"
        }
        Write-Host "  $(Join-Path $seedDir 'seed_data.sql')"
        return $true
    }
}

function Invoke-RunTest {
    Write-Step "Running JMeter Load Test"

    $runScript = Join-Path $ScriptsDir "run_jmeter_db_test.ps1"

    $params = @{
        DbType = $DbType
        DbHost = $DbHost
        DbName = $DbName
        Threads = $Threads
        RampUp = $RampUp
        Duration = $Duration
    }

    if ($DbPort) { $params.DbPort = $DbPort }
    if ($JMeterHome) { $params.JMeterHome = $JMeterHome }
    if ($ResultsDir) { $params.ResultsDir = $ResultsDir }
    if ($TrustedConnection) { $params.TrustedConnection = $true }
    if ($GUI) { $params.GUI = $true }

    # Set user credentials
    if ($TrustedConnection) {
        # For Windows Auth, we still need to provide user for JMeter's regular queries
        $params.DbUser = "test_user_1"
        $params.DbPassword = "Test@123"
        $params.DbAdminUser = "test_admin"
        $params.DbAdminPassword = "Admin@789"
    } else {
        if ($DbUser) { $params.DbUser = $DbUser }
        if ($DbPassword) { $params.DbPassword = $DbPassword }
    }

    & $runScript @params
}

# ============================================================
# Main
# ============================================================

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "    Agent Performance Measurement - Test Runner" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Database:  $DbName"
Write-Host "  DB Type:   $DbType"
Write-Host "  Action:    $Action"
Write-Host "================================================================" -ForegroundColor Cyan

switch ($Action) {
    "help" {
        Show-Help
    }
    "check" {
        Invoke-Check
    }
    "generate" {
        Invoke-Generate
    }
    "setup-db" {
        Invoke-SetupDb
    }
    "run-test" {
        Invoke-RunTest
    }
    "full" {
        $ok = Invoke-Check
        if (-not $ok) {
            Write-Err "Prerequisites check failed. Fix issues above first."
            exit 1
        }

        $ok = Invoke-Generate
        if (-not $ok) {
            Write-Err "File generation failed"
            exit 1
        }

        if (-not $SkipDbSetup) {
            $ok = Invoke-SetupDb
            if (-not $ok) {
                Write-Err "Database setup failed"
                exit 1
            }
        }

        Invoke-RunTest
    }
}

Write-Host ""
