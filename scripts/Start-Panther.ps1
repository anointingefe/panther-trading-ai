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

if (-not $NoPull) {
    git fetch origin main
    git pull --ff-only origin main
}

$venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    py -3 -m venv (Join-Path $RepoPath ".venv")
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $RepoPath "requirements.txt")

$env:PANTHER_BROKER = $Broker
$env:PANTHER_HOST = "0.0.0.0"
$env:PANTHER_PORT = "$Port"

$serverArgs = @("-m", "panther_trading.api.server", "--host", "0.0.0.0", "--port", "$Port")
$server = Start-Process -FilePath $venvPython -ArgumentList $serverArgs -WorkingDirectory $RepoPath -PassThru

try {
    $healthy = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
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
        throw "PANTHER server did not become healthy on port $Port."
    }

    if ($StartDemoLoop) {
        $result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/demo-auto/start"
        Write-Host ("Demo loop: " + $result.demoAuto.message)
    }

    Write-Host "PANTHER is running at http://127.0.0.1:$Port"
    Write-Host "Broker mode: $Broker"
    Write-Host "Server PID: $($server.Id)"
    Write-Host "Live trading remains locked unless the backend guard is explicitly satisfied."
} catch {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
    throw
}
