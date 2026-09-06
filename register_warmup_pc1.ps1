# Run this script ONCE on PC1 (right-click → Run with PowerShell)
# It registers a silent startup task that pre-warms the clinic server every morning.

$scriptPath = "C:\Users\weiyu\OneDrive\Documents\Visual Studio\clinic-system\warmup_ping.ps1"
$taskName   = "ClinicSystemWarmup"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""

$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName    $taskName `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Limited `
    -Description "Pre-warms the clinic system server cache at login so the first nurse visit is fast." `
    -Force

Write-Host "Done — ClinicSystemWarmup task registered for user: $env:USERNAME"
Write-Host "It will run silently every time you log into PC1."
Read-Host "Press Enter to close"
