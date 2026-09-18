param(
    [string]$TaskName = "PriceActionTrader-M15-Startup",
    [string]$Distro = "Ubuntu",
    [string]$RepoPath = "/home/hgl/projects/Price-Action-Trader"
)

$ErrorActionPreference = "Stop"
$wslPath = Join-Path $env:WINDIR "System32\wsl.exe"
if (-not (Test-Path $wslPath)) { throw "wsl.exe not found at $wslPath" }
$scriptPath = "$RepoPath/scripts/start_m15_trading_stack_after_boot.sh"
$launcherDir = Join-Path $env:LOCALAPPDATA "PriceActionTrader\M15"
New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
$vbsPath = Join-Path $launcherDir "$TaskName.vbs"
$wslCommand = "`"$wslPath`" -d `"$Distro`" --exec bash `"$scriptPath`""
$escapedWslCommand = $wslCommand.Replace('"', '""')
$vbs = @"
Set shell = CreateObject("WScript.Shell")
exitCode = shell.Run("$escapedWslCommand", 0, True)
WScript.Quit exitCode
"@
Set-Content -Path $vbsPath -Value $vbs -Encoding ASCII

# A single registered task owns both triggers and invokes the same hidden entry.
# Fail visibly if registration is denied; do not install an alternate launcher.
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`""
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$weekdayTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At "20:45"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -Hidden -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger @($logonTrigger, $weekdayTrigger) -Principal $principal `
    -Settings $settings -Description "M15 verified read-only startup at logon and weekdays 20:45" `
    -Force | Out-Null

# Registration succeeded: retire previous automatic entries with this exact name.
$startupDir = [Environment]::GetFolderPath("Startup")
if ($startupDir) {
    foreach ($suffix in @(".vbs", ".cmd", "-Watchdog.ps1", "-Launcher.ps1")) {
        $legacyPath = Join-Path $startupDir "$TaskName$suffix"
        Remove-Item -Force -ErrorAction SilentlyContinue $legacyPath
    }
}
Write-Output "Installed one hidden task with two triggers: $TaskName"
Write-Output "Canonical entry: $scriptPath; no order dispatch or automatic retry."
