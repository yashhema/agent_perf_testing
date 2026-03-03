# Discover native OS service versions and status on Windows Server.
# Checks sshd, W32Time, EventLog, WinRM.
# Outputs JSON to stdout.
$services = @("sshd", "W32Time", "EventLog", "WinRM")
$parts = @()
$statuses = @()
foreach ($svcName in $services) {
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if ($svc) {
        $statuses += "$svcName=$($svc.Status.ToString())"
    } else {
        $statuses += "$svcName=not_found"
    }
}
$osVer = [System.Environment]::OSVersion.Version.ToString()
@{version="os=$osVer"; status=($statuses -join ",")} | ConvertTo-Json -Compress
