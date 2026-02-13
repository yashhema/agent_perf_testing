# Discover Windows Server OS version information.
# Outputs JSON to stdout.
$os = Get-CimInstance Win32_OperatingSystem
$ver = [System.Environment]::OSVersion.Version
@{os_major_ver=$ver.Major.ToString(); os_minor_ver=$ver.Minor.ToString(); os_build=$os.BuildNumber; os_kernel_ver="$($ver.Major).$($ver.Minor).$($os.BuildNumber)"} | ConvertTo-Json -Compress
