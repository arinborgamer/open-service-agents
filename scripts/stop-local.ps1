$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$task = Get-ScheduledTask -TaskName 'OpenServiceAgents-Local' -ErrorAction SilentlyContinue
if ($task) { Stop-ScheduledTask -TaskName $task.TaskName }
# Verify command lines and executable names before acting on persisted PIDs.
foreach ($service in @('supervisor', 'serve', 'worker', 'mail-worker')) {
    $pidPath = "$repo\.local\$service.pid"
    if (Test-Path -LiteralPath $pidPath) {
        $recordedId = [int](Get-Content -LiteralPath $pidPath)
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedId" -ErrorAction SilentlyContinue
        if ($proc -and (($service -eq 'supervisor' -and $proc.CommandLine.Contains("$PSScriptRoot\supervise.ps1")) -or ($service -ne 'supervisor' -and $proc.CommandLine.Contains("$repo\.local\data") -and $proc.CommandLine -match "open_service_agents.+$service"))) {
            Stop-Process -Id $recordedId
        }
    }
}
Write-Output 'Local processes stopped. The scheduled task will still run at the next sign-in.'
