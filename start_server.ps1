param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$env:PSModulePath = (Join-Path $PSHOME 'Modules') + ';' + $env:PSModulePath
# Windows PowerShell can inherit both PATH and Path from another shell.
$launchPath = [Environment]::GetEnvironmentVariable('Path', 'Process')
[Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
[Environment]::SetEnvironmentVariable('Path', $null, 'Process')
[Environment]::SetEnvironmentVariable('Path', $launchPath, 'Process')
$url = 'http://127.0.0.1:8088'
$mutex = New-Object System.Threading.Mutex($false, 'Local\TaiwanRevenueMonitorLauncher')
$locked = $false

function Read-Health {
    try {
        return Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
    } catch {
        return $null
    }
}

try {
    $locked = $mutex.WaitOne(45000)
    if (-not $locked) { throw 'Another launch is still in progress. Please try again shortly.' }
    Set-Location -LiteralPath $PSScriptRoot
    $serverFile = Join-Path $PSScriptRoot 'server.py'
    $version = (Get-FileHash -LiteralPath $serverFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $health = Read-Health
    if ($health -and $health.app -eq 'taiwan-revenue-monitor' -and $health.serverVersion -ne $version) {
        $listener = netstat.exe -ano -p tcp | Where-Object {
            $_ -match '^\s*TCP\s+(?:127\.0\.0\.1|0\.0\.0\.0):8088\s+\S+\s+LISTENING\s+(\d+)\s*$' -and
            [int]$Matches[1] -eq [int]$health.processId
        }
        $process = Get-Process -Id $health.processId -ErrorAction SilentlyContinue
        if (-not $listener -or -not $process -or $process.ProcessName -notmatch '^python(w)?$') {
            throw 'Cannot verify the existing server process. Please close it before restarting.'
        }
        $oldProcessId = $process.Id
        Stop-Process -Id $oldProcessId -Force
        Wait-Process -Id $oldProcessId -Timeout 5 -ErrorAction SilentlyContinue
        $health = $null
    }
    if (-not $health -or $health.app -ne 'taiwan-revenue-monitor') {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $connection = $client.ConnectAsync('127.0.0.1', 8088)
            try { $connection.Wait(1000) | Out-Null } catch { }
            if ($client.Connected) {
                throw 'Port 8088 is in use by an older server or another program. Close that server first, then run start.bat again.'
            }
        } finally { $client.Dispose() }

        $python = $null
        foreach ($command in @('py', 'python')) {
            if (Get-Command $command -ErrorAction SilentlyContinue) {
                $arguments = if ($command -eq 'py') { @('-3', '-c') } else { @('-c') }
                try {
                    $candidate = & $command @arguments 'import sys; print(sys.executable)' 2>$null
                } catch { continue }
                if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath $candidate)) {
                    $python = $candidate
                    break
                }
            }
        }
        if (-not $python) { throw 'Python 3 was not found. Install Python 3 and run start.bat again.' }
        $env:HOST = '127.0.0.1'
        $env:PORT = '8088'
        $env:PYTHONIOENCODING = 'utf-8'
        $started = Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList '-u', ('"{0}"' -f $serverFile) -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $PSScriptRoot 'server.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'server.err.log') -PassThru
        $deadline = (Get-Date).AddSeconds(30)
        do {
            if ($started.HasExited) { throw 'Server failed to start. See server.err.log for details.' }
            $health = Read-Health
            if ($health -and $health.app -eq 'taiwan-revenue-monitor' -and $health.serverVersion -eq $version) { break }
            Start-Sleep -Milliseconds 300
        } while ((Get-Date) -lt $deadline)
        if (-not $health -or $health.app -ne 'taiwan-revenue-monitor' -or $health.serverVersion -ne $version) {
            throw 'Server did not become ready. See server.err.log for details.'
        }
    }
    Write-Host "Website ready: $url"
    if (-not $NoBrowser) { Start-Process $url }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host $_.InvocationInfo.PositionMessage
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

