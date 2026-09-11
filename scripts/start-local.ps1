param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
if (-not (Test-Path -LiteralPath "$repo\.local\runtime.env")) {
    & $Python -m open_service_agents init
    if ($LASTEXITCODE -ne 0) { throw 'Runtime initialization failed.' }
}
$shell = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $shell) { throw 'PowerShell 7 (pwsh) is required for the supervisor.' }
$resolvedPython = (Get-Command $Python -ErrorAction Stop).Source
$process = Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-File', "`"$PSScriptRoot\supervise.ps1`"", '-Python', "`"$resolvedPython`"") -WorkingDirectory $repo -WindowStyle Hidden -PassThru
Write-Output 'Local API and worker supervisor started. Health: http://127.0.0.1:8787/health'
