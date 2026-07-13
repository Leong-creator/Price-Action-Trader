param(
    [string]$TaskName = "PriceActionTrader-M15-Startup",
    [string]$Distro = "Ubuntu",
    [string]$RepoPath = "/home/hgl/projects/Price-Action-Trader"
)

$ErrorActionPreference = "Stop"

$wslPath = Join-Path $env:WINDIR "System32\wsl.exe"
if (-not (Test-Path $wslPath)) {
    throw "wsl.exe not found at $wslPath"
}

$scriptPath = "./scripts/start_m15_trading_stack_after_boot.sh"
$bashCommand = "cd $RepoPath && $scriptPath"
$argument = "-d `"$Distro`" -- bash -lc `"$bashCommand`""

function Install-StartupFolderFallback {
    $startupDir = [Environment]::GetFolderPath("Startup")
    if (-not $startupDir) {
        throw "Windows Startup folder not found."
    }
    New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
    $legacyCmdPath = Join-Path $startupDir "$TaskName.cmd"
    $legacyWatchdogPath = Join-Path $startupDir "$TaskName-Watchdog.ps1"
    $vbsPath = Join-Path $startupDir "$TaskName.vbs"
    $launcherPath = Join-Path $startupDir "$TaskName-Launcher.ps1"
    Remove-Item -Force -ErrorAction SilentlyContinue $legacyCmdPath, $legacyWatchdogPath, $launcherPath
    $wslCommand = "`"$wslPath`" -d `"$Distro`" -- bash -lc `"cd $RepoPath && $scriptPath`""
    $escapedWslCommand = $wslCommand.Replace('"', '""')
    $vbs = @"
Set shell = CreateObject("WScript.Shell")
shell.Run "$escapedWslCommand", 0, False
"@
    Set-Content -Path $vbsPath -Value $vbs -Encoding ASCII
    Write-Output "Installed direct hidden startup-folder launcher: $vbsPath"
    Write-Output "Fallback runs the paper-trading startup script once per Windows logon without a PowerShell or console window."
}

try {
    $action = New-ScheduledTaskAction -Execute $wslPath -Argument $argument
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn
    $weekdayTrigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At "21:10"
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -Hidden `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -StartWhenAvailable

    $description = "Hidden user-level task for Price-Action-Trader startup at Windows logon and weekdays 21:10."

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger @($logonTrigger, $weekdayTrigger) `
        -Principal $principal `
        -Settings $settings `
        -Description $description `
        -Force | Out-Null

    Write-Output "Installed scheduled task: $TaskName"
    Write-Output "Action: $wslPath $argument"
} catch {
    $message = $_.Exception.Message
    $errorId = [string]$_.FullyQualifiedErrorId
    if ($message -match "Access is denied|拒绝访问|0x80070005|权限" -or $errorId -match "PermissionDenied|AccessDenied|0x80070005") {
        Write-Warning "Scheduled task install denied by current Windows permissions, falling back to hidden logon-only Startup launcher: $message"
        Install-StartupFolderFallback
    } else {
        throw
    }
}
