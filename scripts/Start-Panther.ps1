param(
    [string]$RepoPath = (Split-Path -Parent $PSScriptRoot),
    [int]$Port = 8090,
    [ValidateSet("simulated", "mt5")]
    [string]$Broker = "mt5",
    [switch]$NoPull,
    [switch]$StartDemoLoop
)

$ErrorActionPreference = "Stop"
Set-Location $RepoPath
$varDir = Join-Path $RepoPath "var"
$stdoutLog = Join-Path $varDir "panther-server.out.log"
$stderrLog = Join-Path $varDir "panther-server.err.log"
New-Item -ItemType Directory -Force -Path $varDir | Out-Null
Remove-Item $stdoutLog, $stderrLog -ErrorAction SilentlyContinue

if (-not $NoPull) {
    git fetch origin main
    git pull --ff-only origin main
}

$venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv (Join-Path $RepoPath ".venv")
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv (Join-Path $RepoPath ".venv")
    } else {
        throw "Python was not found. Install Python 3.11+ from python.org, then rerun this command."
    }
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $RepoPath "requirements.txt")

if ($Broker -eq "mt5") {
    Write-Host "Installing MetaTrader 5 Python bridge..."
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $RepoPath "requirements-mt5.txt")
    & $venvPython -c "import MetaTrader5; print('MetaTrader5 Python bridge ready')"
}

$env:PANTHER_BROKER = $Broker
$env:PANTHER_HOST = "0.0.0.0"
$env:PANTHER_PORT = "$Port"

$serverArgs = @("-m", "panther_trading.api.server", "--host", "0.0.0.0", "--port", "$Port")
$server = Start-Process `
    -FilePath $venvPython `
    -ArgumentList $serverArgs `
    -WorkingDirectory $RepoPath `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

try {
    $healthy = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($server.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            if ($health.status -eq "ok") {
                $healthy = $true
                break
            }
        } catch {
            # The server is still starting.
        }
    }
    if (-not $healthy) {
        Write-Host ""
        Write-Host "PANTHER server did not become healthy on port $Port." -ForegroundColor Red
        Write-Host "Server stdout log: $stdoutLog"
        Write-Host "Server stderr log: $stderrLog"
        if (Test-Path $stderrLog) {
            Write-Host ""
            Write-Host "Latest server error:" -ForegroundColor Yellow
            Get-Content $stderrLog -Tail 40
        }
        throw "PANTHER server startup failed."
    }

    if ($StartDemoLoop) {
        $result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/demo-auto/start"
        Write-Host ("Demo loop: " + $result.demoAuto.message)
    }

    Write-Host "PANTHER is running at http://127.0.0.1:$Port"
    Write-Host "Broker mode: $Broker"
    Write-Host "Server PID: $($server.Id)"
    Write-Host "Server logs: $stdoutLog / $stderrLog"
    Write-Host "Keep this window open while using the dashboard. Press Ctrl+C to stop PANTHER."
    Write-Host "Live trading remains locked unless the backend guard is explicitly satisfied."
    Wait-Process -Id $server.Id
} catch {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
    throw
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
}
