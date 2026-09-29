# Run as Administrator from extracted patch directory; user app path is fixed below.
$ErrorActionPreference='Stop'
$App='C:\Users\Aj123\Downloads\adrian-command-center-v1-1\adrian-command-center'
$Py=Join-Path $App '.venv\Scripts\python.exe'
$Runner=Join-Path $App 'job_v7_radar.py'
if (!(Test-Path $Py) -or !(Test-Path $Runner)) { throw 'STOP: install the radar first; expected files missing.' }
$Action=New-ScheduledTaskAction -Execute $Py -Argument ('"'+$Runner+'"') -WorkingDirectory $App
$Trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'ADRIAN_AI_Live_Job_Radar' -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Host 'SUCCESS: Radar task installed. Runs every 15 minutes, including before login when PC is awake.'
Write-Host 'Existing 8 AM / 5 PM and boot tasks were not changed.'
