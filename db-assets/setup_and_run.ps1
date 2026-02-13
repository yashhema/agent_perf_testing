<#
.SYNOPSIS
    Setup and Run Agent Performance Testing with JMeter

.DESCRIPTION
    This script sets up the database and runs JMeter tests for agent performance measurement.

    Database: agent_performance_measurement
    Supported: SQL Server (mssql), PostgreSQL, Oracle, DB2

.PARAMETER Action
    Action to perform: generate, setup-db, run-emulator-test, run-db-test, all

.PARAMETER DbType
    Database type: mssql, postgresql, oracle, db2

.PARAMETER SqlServerInstance
    SQL Server instance (default: localhost)

.PARAMETER TrustedConnection
    Use Windows Authentication (default: $true)

.EXAMPLE
    .\setup_and_run.ps1 -Action all -DbType mssql

.EXAMPLE
    .\setup_and_run.ps1 -Action setup-db -DbType mssql -SqlServerInstance "localhost\SQLEXPRESS"
#>

param(
    [ValidateSet("generate", "setup-db", "run-emulator-test", "run-db-test", "all", "help")]
    [string]$Action = "help",

    [ValidateSet("mssql", "postgresql", "oracle", "db2")]
    [string]$DbType = "mssql",

    [string]$SqlServerInstance = "localhost",

    [bool]$TrustedConnection = $true,

    [string]$JMeterPath = "",

    [int]$SeedRecords = 1000
)

# Configuration
$DatabaseName = "agent_performance_measurement"
$ScriptDir = $PSScriptRoot
$OutputDir = Join-Path $ScriptDir "output"
$DbOutputDir = Join-Path $OutputDir $DbType
$JmxOutputDir = Join-Path $OutputDir "jmx"

# Colors for output
function Write-Step { param($msg) Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Show-Help {
    Write-Host @"

========================================================================
         AGENT PERFORMANCE MEASUREMENT - SETUP AND RUN GUIDE
========================================================================

DATABASE NAME: agent_performance_measurement

ACTIONS:
  generate          - Generate all files (schema, seed+params, queries, JMX)
  setup-db          - Setup database (create DB, tables, seed data)
  run-emulator-test - Run JMeter emulator tests (requires 2 emulator instances)
  run-db-test       - Run JMeter database load test
  all               - Do everything: generate + setup-db

EXAMPLES:
  # Generate all files for SQL Server
  .\setup_and_run.ps1 -Action generate -DbType mssql

  # Setup SQL Server database
  .\setup_and_run.ps1 -Action setup-db -DbType mssql

  # Full setup
  .\setup_and_run.ps1 -Action all -DbType mssql

  # With named instance
  .\setup_and_run.ps1 -Action all -DbType mssql -SqlServerInstance "localhost\SQLEXPRESS"

PREREQUISITES:
  1. Python 3.8+ with required packages (pip install -r requirements.txt)
  2. SQL Server running locally (or other DB)
  3. JMeter 5.x installed (for running tests)
  4. JDBC driver in JMeter lib folder

OUTPUT FILES:
  output/mssql/schema/
    00_create_database.sql  <- Run FIRST (creates agent_performance_measurement)
    01_create_tables.sql
    02_create_indexes.sql
    03_create_constraints.sql
    04_create_users.sql

  output/mssql/seed/
    seed_data.sql           <- INSERT statements

  output/mssql/params/
    customer_ids.csv        <- ACTUAL values from seed data
    order_ids.csv
    ...

  output/jmx/
    server-normal.jmx
    server-file-heavy.jmx
    server-file-heavy_withconfidential.jmx
    db-load-mssql.jmx

========================================================================
"@
}

function Test-Prerequisites {
    Write-Step "Checking Prerequisites"

    # Check Python
    try {
        $pythonVersion = python --version 2>&1
        Write-Success "Python: $pythonVersion"
    } catch {
        Write-Error "Python not found. Please install Python 3.8+"
        return $false
    }

    # Check if generator module exists
    if (-not (Test-Path (Join-Path $ScriptDir "generator"))) {
        Write-Error "Generator module not found at $ScriptDir\generator"
        return $false
    }
    Write-Success "Generator module found"

    # Check for sqlcmd (SQL Server)
    if ($DbType -eq "mssql") {
        try {
            $sqlcmdVersion = sqlcmd -? 2>&1 | Select-Object -First 1
            Write-Success "sqlcmd available"
        } catch {
            Write-Warning "sqlcmd not found. You may need to run SQL scripts manually."
        }
    }

    return $true
}

function Invoke-Generate {
    Write-Step "Generating All Files"

    Push-Location $ScriptDir
    try {
        # Generate schema
        Write-Host "Generating schema for $DbType..."
        python -m generator.main schema -d $DbType

        # Generate seed data + params (SINGLE-PASS)
        Write-Host "Generating seed data + params (single-pass)..."
        python -m generator.main seed -d $DbType

        # Generate queries
        Write-Host "Generating queries..."
        python -m generator.main queries -d $DbType

        # Generate JMX templates
        Write-Host "Generating JMX templates..."
        python -m generator.main jmx -d $DbType

        Write-Success "All files generated successfully"
        Write-Host ""
        Write-Host "Generated files:"
        Write-Host "  Schema: $DbOutputDir\schema\"
        Write-Host "  Seed:   $DbOutputDir\seed\"
        Write-Host "  Params: $DbOutputDir\params\"
        Write-Host "  JMX:    $JmxOutputDir\"
    }
    finally {
        Pop-Location
    }
}

function Invoke-SetupDatabase {
    Write-Step "Setting Up Database: $DatabaseName"

    $schemaDir = Join-Path $DbOutputDir "schema"
    $seedDir = Join-Path $DbOutputDir "seed"

    if (-not (Test-Path $schemaDir)) {
        Write-Error "Schema files not found. Run 'generate' first."
        return $false
    }

    if ($DbType -eq "mssql") {
        $connectionString = if ($TrustedConnection) {
            "-S $SqlServerInstance -E"
        } else {
            $user = Read-Host "Enter SQL Server username"
            $pass = Read-Host "Enter SQL Server password" -AsSecureString
            $plainPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass))
            "-S $SqlServerInstance -U $user -P $plainPass"
        }

        # Run scripts in order
        $scripts = @(
            "00_create_database.sql",
            "01_create_tables.sql",
            "02_create_indexes.sql",
            "03_create_constraints.sql",
            "04_create_users.sql"
        )

        foreach ($script in $scripts) {
            $scriptPath = Join-Path $schemaDir $script
            if (Test-Path $scriptPath) {
                Write-Host "Running $script..."
                $cmd = "sqlcmd $connectionString -i `"$scriptPath`""
                Invoke-Expression $cmd
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "Script $script may have had issues"
                } else {
                    Write-Success "$script completed"
                }
            }
        }

        # Run seed data
        $seedFile = Join-Path $seedDir "seed_data.sql"
        if (Test-Path $seedFile) {
            Write-Host "Running seed_data.sql (this may take a while)..."
            # Use the database now
            $dbConnection = "-S $SqlServerInstance -d $DatabaseName"
            if ($TrustedConnection) { $dbConnection += " -E" }
            $cmd = "sqlcmd $dbConnection -i `"$seedFile`""
            Invoke-Expression $cmd
            Write-Success "Seed data loaded"
        }

        Write-Success "Database setup complete: $DatabaseName"
    }
    else {
        Write-Host ""
        Write-Host "For $DbType, please run the following scripts manually:"
        Write-Host ""
        Get-ChildItem $schemaDir -Filter "*.sql" | Sort-Object Name | ForEach-Object {
            Write-Host "  $($_.FullName)"
        }
        Write-Host ""
        Write-Host "Then run seed data:"
        Write-Host "  $(Join-Path $seedDir 'seed_data.sql')"
    }

    return $true
}

function Invoke-RunEmulatorTest {
    Write-Step "Running Emulator Test"

    Write-Host @"

EMULATOR TEST PREREQUISITES:
1. Start two emulator instances:
   - Instance 1: python -m emulator.app --port 8080
   - Instance 2: python -m emulator.app --port 8081

2. JMX files available:
   - $JmxOutputDir\server-normal.jmx
   - $JmxOutputDir\server-file-heavy.jmx

3. JMeter installed at: $JMeterPath

"@

    if (-not $JMeterPath -or -not (Test-Path $JMeterPath)) {
        $JMeterPath = Read-Host "Enter path to jmeter.bat (e.g., C:\apache-jmeter-5.6.3\bin\jmeter.bat)"
    }

    if (Test-Path $JMeterPath) {
        $jmxFile = Join-Path $JmxOutputDir "server-normal.jmx"
        if (Test-Path $jmxFile) {
            Write-Host "Starting JMeter with server-normal.jmx..."
            Start-Process $JMeterPath -ArgumentList "-t `"$jmxFile`""
        }
    } else {
        Write-Error "JMeter not found at: $JMeterPath"
    }
}

function Invoke-RunDbTest {
    Write-Step "Running Database Load Test"

    Write-Host @"

DATABASE TEST PREREQUISITES:
1. Database '$DatabaseName' is set up with seed data
2. JMeter installed with JDBC driver
3. JDBC driver for $DbType in JMeter's lib folder

JMX FILE: $JmxOutputDir\db-load-$DbType.jmx

JDBC CONNECTION (update in JMeter):
"@

    if ($DbType -eq "mssql") {
        Write-Host @"
  Driver: com.microsoft.sqlserver.jdbc.SQLServerDriver
  URL: jdbc:sqlserver://${SqlServerInstance};databaseName=$DatabaseName;integratedSecurity=true

  Download JDBC driver from:
  https://docs.microsoft.com/en-us/sql/connect/jdbc/download-microsoft-jdbc-driver-for-sql-server

  Copy mssql-jdbc-*.jar to JMeter's lib folder
"@
    }

    if (-not $JMeterPath -or -not (Test-Path $JMeterPath)) {
        $JMeterPath = Read-Host "Enter path to jmeter.bat"
    }

    if (Test-Path $JMeterPath) {
        $jmxFile = Join-Path $JmxOutputDir "db-load-$DbType.jmx"
        if (Test-Path $jmxFile) {
            Write-Host "Starting JMeter with db-load-$DbType.jmx..."
            Start-Process $JMeterPath -ArgumentList "-t `"$jmxFile`""
        } else {
            Write-Error "JMX file not found: $jmxFile"
        }
    }
}

# Main execution
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Agent Performance Measurement Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Database: $DatabaseName"
Write-Host " DB Type:  $DbType"
Write-Host " Action:   $Action"
Write-Host "========================================" -ForegroundColor Cyan

switch ($Action) {
    "help" {
        Show-Help
    }
    "generate" {
        if (Test-Prerequisites) {
            Invoke-Generate
        }
    }
    "setup-db" {
        Invoke-SetupDatabase
    }
    "run-emulator-test" {
        Invoke-RunEmulatorTest
    }
    "run-db-test" {
        Invoke-RunDbTest
    }
    "all" {
        if (Test-Prerequisites) {
            Invoke-Generate
            Invoke-SetupDatabase
        }
    }
}

Write-Host ""
