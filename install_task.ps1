param(
    [string]$Time = "07:50",
    [string]$TaskName = "SparkAuto"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (python -c "import sys; print(sys.executable)").Trim()

if (-not (Test-Path $python)) {
    Write-Error "找不到 python，请先运行 setup.bat"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$root\main.py`" run --random"
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "抖音每日续火花（本地运行）" `
    -Force | Out-Null

Write-Host "已创建计划任务：$TaskName"
Write-Host "每天 $Time 启动，程序会在 08:00-22:00 之间随机挑时间发送"
Write-Host "删除任务：schtasks /Delete /TN `"$TaskName`" /F"
