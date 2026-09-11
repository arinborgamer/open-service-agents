param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$resolvedPython = (Get-Command $Python -ErrorAction Stop).Source
$shell = (Get-Command pwsh -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $shell -Argument "-NoProfile -WindowStyle Hidden -File `"$PSScriptRoot\supervise.ps1`" -Python `"$resolvedPython`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'OpenServiceAgents-Local' -Action $action -Trigger $trigger -Settings $settings -Description 'Open Service Agents local API and durable worker' -Force | Select-Object TaskName,State
