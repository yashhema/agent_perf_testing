# Install Java JRE on Windows Server if not present.
# Idempotent - skips if java is already on PATH.
$ErrorActionPreference = "Stop"

$javaCmd = Get-Command java -ErrorAction SilentlyContinue
if ($javaCmd) {
    $ver = & java -version 2>&1 | Select-Object -First 1
    Write-Host "Java already installed: $ver"
    exit 0
}

Write-Host "Java not found - installing Adoptium JRE 11..."

$jreUrl = "https://api.adoptium.net/v3/binary/latest/11/ga/windows/x64/jre/hotspot/normal/eclipse"
$tempMsi = "$env:TEMP\adoptium-jre11.msi"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $jreUrl -OutFile $tempMsi -UseBasicParsing

Start-Process msiexec.exe -ArgumentList "/i `"$tempMsi`" ADDLOCAL=FeatureMain,FeatureJavaHome INSTALLDIR=`"C:\Java\jre-11`" /qn" -Wait -NoNewWindow

# Add to PATH for this session and permanently
$javaHome = "C:\Java\jre-11"
$env:JAVA_HOME = $javaHome
$env:PATH = "$javaHome\bin;$env:PATH"
[Environment]::SetEnvironmentVariable("JAVA_HOME", $javaHome, "Machine")
$machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
if ($machinePath -notlike "*$javaHome\bin*") {
    [Environment]::SetEnvironmentVariable("PATH", "$javaHome\bin;$machinePath", "Machine")
}

Remove-Item $tempMsi -Force -ErrorAction SilentlyContinue
& java -version 2>&1
Write-Host "Java JRE installed successfully"
