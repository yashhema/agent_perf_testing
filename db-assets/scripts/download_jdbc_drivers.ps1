<#
.SYNOPSIS
    Download JDBC drivers for all supported databases

.DESCRIPTION
    Downloads JDBC drivers and places them in the lib/ folder.
    These drivers should be copied to JMeter's lib folder.
#>

param(
    [string]$OutputDir = "$PSScriptRoot\..\lib\jdbc"
)

$ErrorActionPreference = "Stop"

# Create output directory
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Downloading JDBC Drivers" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Output: $OutputDir"
Write-Host ""

# JDBC Driver URLs (update versions as needed)
$drivers = @{
    "mssql" = @{
        "url" = "https://go.microsoft.com/fwlink/?linkid=2262913"  # mssql-jdbc-12.8.1.jre11.jar
        "filename" = "mssql-jdbc-12.8.1.jre11.jar"
        "description" = "Microsoft SQL Server JDBC Driver"
    }
    "postgresql" = @{
        "url" = "https://jdbc.postgresql.org/download/postgresql-42.7.4.jar"
        "filename" = "postgresql-42.7.4.jar"
        "description" = "PostgreSQL JDBC Driver"
    }
    # Oracle requires manual download from Oracle website (login required)
    # DB2 requires manual download from IBM website
}

foreach ($dbType in $drivers.Keys) {
    $driver = $drivers[$dbType]
    $outputPath = Join-Path $OutputDir $driver.filename

    Write-Host "Downloading $($driver.description)..." -ForegroundColor Yellow

    try {
        if (Test-Path $outputPath) {
            Write-Host "  Already exists: $($driver.filename)" -ForegroundColor Green
        } else {
            Invoke-WebRequest -Uri $driver.url -OutFile $outputPath -UseBasicParsing
            Write-Host "  Downloaded: $($driver.filename)" -ForegroundColor Green
        }
    } catch {
        Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Manual download: $($driver.url)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Manual Downloads Required:" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Oracle JDBC Driver:" -ForegroundColor Yellow
Write-Host "  1. Go to: https://www.oracle.com/database/technologies/appdev/jdbc-downloads.html"
Write-Host "  2. Download ojdbc11.jar"
Write-Host "  3. Copy to: $OutputDir"
Write-Host ""
Write-Host "IBM DB2 JDBC Driver:" -ForegroundColor Yellow
Write-Host "  1. Go to: https://www.ibm.com/support/pages/db2-jdbc-driver-versions-and-downloads"
Write-Host "  2. Download db2jcc4.jar"
Write-Host "  3. Copy to: $OutputDir"
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Next Steps:" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Copy all JAR files from:"
Write-Host "  $OutputDir"
Write-Host "To your JMeter lib folder:"
Write-Host "  C:\apache-jmeter-5.x\lib\"
Write-Host ""
