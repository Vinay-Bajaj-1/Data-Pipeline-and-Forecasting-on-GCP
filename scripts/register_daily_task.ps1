param([string]$At = '18:30')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw 'Project venv Python not found' }
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + (Join-Path $projectDir 'run_pipeline.py') + '" --mode daily') -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'FinFlow GCP Daily' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'FinFlow daily ingestion and forecasting; current user must be logged in.'
