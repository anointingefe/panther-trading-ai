param(
    [string]$RepoPath = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "PANTHER Trading AI",
    [int]$Port = 8090,
    [ValidateSet("simulated", "mt5")]
    [string]$Broker = "mt5"
)

$ErrorActionPreference = "Stop"
$launcher = Join-Path $RepoPath "scripts\Start-Panther.ps1"
if (-not (Test-Path $launcher)) {
    throw "Launcher not found: $launcher"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -RepoPath `"$RepoPath`" -Port $Port -Broker $Broker -StartDemoLoop"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $RepoPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Pull and run the guarded PANTHER Trading AI dashboard." -Force | Out-Null
Write-Host "Installed '$TaskName'. It will pull main and start PANTHER when you sign in."
