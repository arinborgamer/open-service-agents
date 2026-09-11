param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$mutexName = 'Local\OpenServiceAgents-' + ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($repo)))).Substring(0,16)
$created = $false
$mutex = [Threading.Mutex]::new($true, $mutexName, [ref]$created)
if (-not $created) { $mutex.Dispose(); exit 0 }
Set-Content -LiteralPath "$repo\.local\supervisor.pid" -Value $PID
$children = @{}
try {
    foreach ($service in @('serve', 'worker', 'mail-worker')) {
        $children[$service] = $null
    }
    while ($true) {
        foreach ($service in @('serve', 'worker', 'mail-worker')) {
            if (-not $children[$service] -or $children[$service].HasExited) {
                $children[$service] = Start-Process -FilePath $Python -ArgumentList @('-u', '-m', 'open_service_agents', '--data', "`"$repo\.local\data`"", '--env-file', "`"$repo\.local\runtime.env`"", $service) -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput "$repo\.local\$service.log" -RedirectStandardError "$repo\.local\$service.error.log"
                Set-Content -LiteralPath "$repo\.local\$service.pid" -Value $children[$service].Id
            }
        }
        Start-Sleep -Seconds 10
    }
} finally {
    foreach ($process in $children.Values) {
        if ($process -and -not $process.HasExited) { $process.Kill() }
    }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
