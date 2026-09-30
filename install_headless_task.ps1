param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [string]$DependencyPath = '',
    [string]$TaskName = 'ADRIAN AI background server'
)
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$serverScript = Join-Path $appRoot 'start_server.py'
if (-not (Test-Path -LiteralPath $PythonPath) -or -not (Test-Path -LiteralPath $serverScript)) { throw 'Python and server entry point must exist.' }
$taskArguments = '"' + $serverScript + '"'
if ($DependencyPath) {
    if (-not (Test-Path -LiteralPath $DependencyPath)) { throw 'Dependency directory does not exist.' }
    $taskArguments += ' --dependencies "' + $DependencyPath + '"'
}
$taskAction = New-ScheduledTaskAction -Execute $PythonPath -Argument $taskArguments -WorkingDirectory $appRoot
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At '09:20'
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$taskSettings.Hidden = $true
$taskPrincipal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.Actions.Execute -ne $PythonPath) { throw 'An existing task uses a different executable. Review it before replacing.' }
Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger @($logonTrigger,$dailyTrigger) -Settings $taskSettings -Principal $taskPrincipal -Description 'Runs the locally configured ADRIAN.AI app and its authorized paper-only trading workers. Credentials remain in encrypted app settings.' -Force | Out-Null
Write-Output 'Background task registered for Windows sign-in and 09:20 daily. The app calendar schedules market updates and learned swing decisions. PC must be on and this user signed in.'
