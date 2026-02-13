<#
.SYNOPSIS
    Run JMeter database load test with all parameters on command line

.DESCRIPTION
    Runs JMeter in non-GUI mode with all configuration passed via command line.
    Results are saved to specified output directory.

.PARAMETER JMeterHome
    Path to JMeter installation (e.g., C:\apache-jmeter-5.6.3)

.PARAMETER DbType
    Database type: mssql, postgresql, oracle, db2

.PARAMETER DbHost
    Database host (default: localhost)

.PARAMETER DbPort
    Database port (default: auto based on db type)

.PARAMETER DbName
    Database name (default: agent_performance_measurement)

.PARAMETER DbUser
    Database user (default: test_user_1)

.PARAMETER DbPassword
    Database password (default: Test@123)

.PARAMETER Threads
    Number of concurrent threads (default: 10)

.PARAMETER RampUp
    Ramp-up time in seconds (default: 60)

.PARAMETER Duration
    Test duration in seconds (default: 300)

.PARAMETER ResultsDir
    Directory for results output (default: ./results)

.EXAMPLE
    .\run_jmeter_db_test.ps1 -JMeterHome "C:\apache-jmeter-5.6.3" -DbType mssql -Threads 20 -Duration 600
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$JMeterHome = $env:JMETER_HOME,

    [Parameter(Mandatory=$false)]
    [ValidateSet("mssql", "postgresql", "oracle", "db2")]
    [string]$DbType = "mssql",

    [string]$DbHost = "localhost",
    [string]$DbPort = "",
    [string]$DbName = "agent_performance_measurement",
    [string]$DbUser = "test_user_1",
    [string]$DbPassword = "Test@123",
    [string]$DbAdminUser = "test_admin",
    [string]$DbAdminPassword = "Admin@789",

    [int]$Threads = 10,
    [int]$RampUp = 60,
    [int]$Duration = 300,

    [string]$ResultsDir = "",
    [string]$ParamsDir = "",

    [switch]$TrustedConnection,
    [switch]$GUI
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$BaseDir = Split-Path $ScriptDir -Parent

# Default ports per database
$DefaultPorts = @{
    "mssql" = "1433"
    "postgresql" = "5432"
    "oracle" = "1521"
    "db2" = "50000"
}

# Set default port if not specified
if (-not $DbPort) {
    $DbPort = $DefaultPorts[$DbType]
}

# Set default results directory
if (-not $ResultsDir) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $ResultsDir = Join-Path $BaseDir "results\$DbType\$timestamp"
}

# Set default params directory
if (-not $ParamsDir) {
    $ParamsDir = Join-Path $BaseDir "output\$DbType\params"
}

# JMX file path
$JmxFile = Join-Path $BaseDir "output\jmx\db-load-$DbType.jmx"

# Create results directory
New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null

# Results file paths
$ResultsJtl = Join-Path $ResultsDir "results.jtl"
$ResultsLog = Join-Path $ResultsDir "jmeter.log"
$HtmlReportDir = Join-Path $ResultsDir "html-report"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "       JMeter Database Load Test Runner" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Database Type:    $DbType"
Write-Host "  Database Host:    $DbHost"
Write-Host "  Database Port:    $DbPort"
Write-Host "  Database Name:    $DbName"
Write-Host "  Database User:    $DbUser"
Write-Host "  Admin User:       $DbAdminUser"
Write-Host "  Threads:          $Threads"
Write-Host "  Ramp-Up:          $RampUp seconds"
Write-Host "  Duration:         $Duration seconds"
Write-Host ""
Write-Host "Files:" -ForegroundColor Yellow
Write-Host "  JMX File:         $JmxFile"
Write-Host "  Params Dir:       $ParamsDir"
Write-Host "  Results Dir:      $ResultsDir"
Write-Host "  Results JTL:      $ResultsJtl"
Write-Host "  HTML Report:      $HtmlReportDir"
Write-Host ""

# Find JMeter
if (-not $JMeterHome) {
    # Try common locations
    $commonPaths = @(
        "C:\apache-jmeter-5.6.3",
        "C:\apache-jmeter-5.6.2",
        "C:\apache-jmeter-5.6",
        "C:\apache-jmeter-5.5",
        "C:\Program Files\Apache JMeter",
        "$env:USERPROFILE\apache-jmeter-5.6.3"
    )
    foreach ($path in $commonPaths) {
        if (Test-Path "$path\bin\jmeter.bat") {
            $JMeterHome = $path
            break
        }
    }
}

if (-not $JMeterHome -or -not (Test-Path "$JMeterHome\bin\jmeter.bat")) {
    Write-Host "ERROR: JMeter not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please either:"
    Write-Host "  1. Set JMETER_HOME environment variable"
    Write-Host "  2. Pass -JMeterHome parameter"
    Write-Host "  3. Install JMeter to C:\apache-jmeter-5.6.3"
    Write-Host ""
    exit 1
}

$JMeterBat = Join-Path $JMeterHome "bin\jmeter.bat"
Write-Host "JMeter:             $JMeterHome" -ForegroundColor Green
Write-Host ""

# Check JMX file exists
if (-not (Test-Path $JmxFile)) {
    Write-Host "ERROR: JMX file not found: $JmxFile" -ForegroundColor Red
    Write-Host "Run 'python -m generator.main jmx -d $DbType' first" -ForegroundColor Yellow
    exit 1
}

# Check params directory exists
if (-not (Test-Path $ParamsDir)) {
    Write-Host "ERROR: Params directory not found: $ParamsDir" -ForegroundColor Red
    Write-Host "Run 'python -m generator.main seed -d $DbType' first" -ForegroundColor Yellow
    exit 1
}

# Build JDBC URL
$JdbcUrl = switch ($DbType) {
    "mssql" {
        if ($TrustedConnection) {
            "jdbc:sqlserver://${DbHost}:${DbPort};databaseName=${DbName};integratedSecurity=true;trustServerCertificate=true"
        } else {
            "jdbc:sqlserver://${DbHost}:${DbPort};databaseName=${DbName};trustServerCertificate=true"
        }
    }
    "postgresql" { "jdbc:postgresql://${DbHost}:${DbPort}/${DbName}" }
    "oracle" { "jdbc:oracle:thin:@${DbHost}:${DbPort}:${DbName}" }
    "db2" { "jdbc:db2://${DbHost}:${DbPort}/${DbName}" }
}

Write-Host "JDBC URL: $JdbcUrl" -ForegroundColor Yellow
Write-Host ""

# Build JMeter command line arguments
$jmeterArgs = @()

if ($GUI) {
    # GUI mode for debugging
    $jmeterArgs += "-t", "`"$JmxFile`""
} else {
    # Non-GUI mode for actual testing
    $jmeterArgs += "-n"                              # Non-GUI mode
    $jmeterArgs += "-t", "`"$JmxFile`""              # Test file
    $jmeterArgs += "-l", "`"$ResultsJtl`""           # Results file
    $jmeterArgs += "-j", "`"$ResultsLog`""           # Log file
    $jmeterArgs += "-e"                              # Generate HTML report
    $jmeterArgs += "-o", "`"$HtmlReportDir`""        # HTML report directory
}

# Add JMeter properties
$jmeterArgs += "-Jthreads=$Threads"
$jmeterArgs += "-Jrampup=$RampUp"
$jmeterArgs += "-Jduration=$Duration"
$jmeterArgs += "-Jdb_host=$DbHost"
$jmeterArgs += "-Jdb_port=$DbPort"
$jmeterArgs += "-Jdb_name=$DbName"
$jmeterArgs += "-Jdb_user=$DbUser"
$jmeterArgs += "-Jdb_password=$DbPassword"
$jmeterArgs += "-Jdb_admin_user=$DbAdminUser"
$jmeterArgs += "-Jdb_admin_password=$DbAdminPassword"
$jmeterArgs += "-Jdb_url=$JdbcUrl"
$jmeterArgs += "-Jparams_dir=$ParamsDir"

# Build full command
$command = "`"$JMeterBat`" $($jmeterArgs -join ' ')"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "Starting JMeter..." -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Command:" -ForegroundColor Yellow
Write-Host $command
Write-Host ""

# Save command to file for reference
$command | Out-File (Join-Path $ResultsDir "run_command.txt")

# Run JMeter
$startTime = Get-Date
Write-Host "Test started at: $startTime" -ForegroundColor Cyan
Write-Host ""

try {
    & cmd /c $command
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$endTime = Get-Date
$elapsed = $endTime - $startTime

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "Test Complete" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Duration:      $($elapsed.ToString('hh\:mm\:ss'))"
Write-Host "Exit Code:     $exitCode"
Write-Host ""
Write-Host "Results:" -ForegroundColor Yellow
Write-Host "  JTL File:    $ResultsJtl"
Write-Host "  Log File:    $ResultsLog"
Write-Host "  HTML Report: $HtmlReportDir\index.html"
Write-Host ""

if ($exitCode -eq 0 -and (Test-Path "$HtmlReportDir\index.html")) {
    Write-Host "Opening HTML report..." -ForegroundColor Green
    Start-Process "$HtmlReportDir\index.html"
}
