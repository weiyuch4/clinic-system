# setup_autostart.ps1
# Run once on the clinic PC (as the normal user, not admin).
# Registers the sync agent as a silent background task that starts at login.

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw    = Join-Path $ProjectDir "venv\Scripts\pythonw.exe"
$Script     = Join-Path $ProjectDir "sync_agent.py"

if (-not (Test-Path $Pythonw)) {
    Write-Host "ERROR: pythonw.exe not found at $Pythonw" -ForegroundColor Red
    Write-Host "Make sure you are running this from the project folder and the venv is set up."
    pause
    exit 1
}

$TaskName = "ClinicSyncAgent"

# Remove any old registration first (idempotent)
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute  $Pythonw `
    -Argument "`"$Script`"" `
    -WorkingDirectory $ProjectDir

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  ([TimeSpan]::Zero) `
    -RestartCount        5 `
    -RestartInterval     (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -MultipleInstances   IgnoreNew

Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $Action `
    -Trigger   $Trigger `
    -Settings  $Settings `
    -RunLevel  Limited `
    -Force | Out-Null

Write-Host ""
Write-Host "Done. '$TaskName' will start silently at every login." -ForegroundColor Green
Write-Host "To start it now without rebooting, run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Cyan
Write-Host ""
Write-Host "To stop it:   Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "To remove it: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
pause
