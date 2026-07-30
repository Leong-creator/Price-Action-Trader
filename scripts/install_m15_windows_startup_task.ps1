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

$scriptPath = "$RepoPath/scripts/start_m15_trading_stack_after_boot.sh"
$argument = "-d `"$Distro`" --exec bash `"$scriptPath`" --keep-alive"

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
    # Avoid nested shell quoting. The bootstrap resolves and enters its own
    # repository root, so WSL can execute it directly and invisibly.
    $wslCommand = "$wslPath -d $Distro --exec bash $scriptPath --keep-alive"
    $escapedWslCommand = $wslCommand.Replace('"', '""')
    $vbs = @"
Set shell = CreateObject("WScript.Shell")
shell.Run "$escapedWslCommand", 0, False
"@
    Set-Content -Path $vbsPath -Value $vbs -Encoding ASCII
    Write-Output "Installed direct hidden startup-folder launcher: $vbsPath"
    Write-Output "Fallback keeps one hidden WSL process attached after logon so the paper-trading stack remains alive without periodic windows."
}

function Install-WeekdayWakeFallback {
    $startupDir = [Environment]::GetFolderPath("Startup")
    $vbsPath = Join-Path $startupDir "$TaskName.vbs"
    $taskAction = "wscript.exe `"$vbsPath`""
    $schtasksPath = Join-Path $env:WINDIR "System32\schtasks.exe"

    if (-not (Test-Path $schtasksPath)) {
        throw "schtasks.exe not found at $schtasksPath"
    }

    $arguments = @(
        "/Create",
        "/TN", $TaskName,
        "/TR", $taskAction,
        "/SC", "WEEKLY",
        "/D", "MON,TUE,WED,THU,FRI",
        "/ST", "20:45",
        "/RL", "LIMITED",
        "/IT",
        "/F"
    )
    $output = & $schtasksPath @arguments 2>&1
    $exitCode = $LASTEXITCODE
    Write-Output $output
    if ($exitCode -ne 0) {
        throw "schtasks.exe failed with exit code $exitCode"
    }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $task.Settings.DisallowStartIfOnBatteries = $false
    $task.Settings.StopIfGoingOnBatteries = $false
    $task.Settings.Hidden = $true
    $task.Settings.StartWhenAvailable = $true
    $task.Settings.ExecutionTimeLimit = "PT0S"
    Set-ScheduledTask -InputObject $task | Out-Null

    Write-Output "Installed hidden weekday 20:45 wake task through schtasks.exe: $TaskName"
}

try {
    $action = New-ScheduledTaskAction -Execute $wslPath -Argument $argument
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn
    $weekdayTrigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At "20:45"
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -Hidden `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -StartWhenAvailable

    $description = "Hidden user-level task for Price-Action-Trader startup at Windows logon and weekdays 20:45."

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
        Write-Warning "PowerShell scheduled-task registration was denied; installing the hidden logon launcher first: $message"
        Install-StartupFolderFallback
        try {
            Install-WeekdayWakeFallback
        } catch {
            Write-Warning "Weekday 20:45 wake task could not be installed; hidden logon startup remains active: $($_.Exception.Message)"
        }
    } else {
        throw
    }
}
