# Discover CrowdStrike Falcon agent version and status on Windows Server.
# Outputs JSON to stdout.
$svc = Get-Service -Name CSFalconService -ErrorAction SilentlyContinue
$version = "unknown"
$file = Get-ChildItem "C:\Windows\System32\drivers\CrowdStrike\CSAgent.sys" -ErrorAction SilentlyContinue
if ($file) { $version = $file.VersionInfo.FileVersion }
$status = if ($svc) { $svc.Status.ToString() } else { "not_found" }
@{version=$version; status=$status} | ConvertTo-Json -Compress
