# Stella CAD — start AgentCAD on Windows.
# Isolation (AppContainer) is ON by default.
# Usage:
#   powershell -File scripts\stella\serve.ps1
#   powershell -File scripts\stella\serve.ps1 -NoSandbox
#   powershell -File scripts\stella\serve.ps1 -Port 8630

param(
    [switch]$NoSandbox,
    [int]$Port = 8630,
    [int]$WaitSeconds = 300
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AgentCad = Join-Path $RepoRoot "agentcad-for-windows"
$ProjectsDir = Join-Path $RepoRoot "projects"
$StateDir = Join-Path $RepoRoot ".stella"
$PidFile = Join-Path $StateDir "server.pid"
$AgentCadExe = Join-Path $AgentCad ".venv\Scripts\agentcad.exe"
$HealthUrl = "http://127.0.0.1:$Port/api/health"

if (-not (Test-Path $AgentCadExe)) {
    Write-Error "AgentCAD venv missing. Run: powershell -File scripts\stella\setup.ps1"
}

New-Item -ItemType Directory -Force -Path $ProjectsDir, $StateDir | Out-Null

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:AGENTCAD_PROJECTS_DIR = $ProjectsDir
$env:AGENTCAD_PORT = "$Port"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RepoRoot ".python"
if ($NoSandbox) {
    $env:AGENTCAD_NO_SANDBOX = "1"
    Write-Host "WARNING: AppContainer isolation is OFF (-NoSandbox)."
} elseif (Test-Path Env:AGENTCAD_NO_SANDBOX) {
    Remove-Item Env:AGENTCAD_NO_SANDBOX
}

function Get-Health {
    try {
        return Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
    } catch {
        return $null
    }
}

$existing = Get-Health
if ($existing -and $existing.kernel -eq "ready") {
    $sb = $existing.sandbox
    $confined = $sb.status -eq "active"
    if ($NoSandbox -or $confined) {
        Write-Host "already running: kernel=ready sandbox=$($sb.status) $HealthUrl"
        if (Test-Path $PidFile) {
            Write-Host "pid file $PidFile = $((Get-Content $PidFile -Raw).Trim())"
        }
        exit 0
    }
    Write-Error @"
port $Port is already serving AgentCAD with sandbox.status=$($sb.status) (wanted active).
This is not Stella's process (isolation off). Stop it, or start Stella on another port:
  powershell -File scripts\stella\serve.ps1 -Port 8640
  uv run python -m stella_cad.bridge serve --port 8640
"@
}

if (Test-Path $PidFile) {
    $oldPid = 0
    [void][int]::TryParse((Get-Content $PidFile -Raw).Trim(), [ref]$oldPid)
    if ($oldPid -gt 0) {
        $proc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            Remove-Item $PidFile -Force
        }
    }
}

Write-Host "starting AgentCAD"
Write-Host "  exe      $AgentCadExe"
Write-Host "  projects $ProjectsDir"
Write-Host "  port     $Port"
Write-Host "  sandbox  $(if ($NoSandbox) { 'off' } else { 'on (default)' })"

$outLog = Join-Path $StateDir "server.out.log"
$errLog = Join-Path $StateDir "server.err.log"
Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath $AgentCadExe `
    -ArgumentList @("serve", "--no-open", "--port", "$Port", "--projects-dir", $ProjectsDir) `
    -WorkingDirectory $AgentCad `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

$proc.Id | Set-Content -Path $PidFile -Encoding ascii
Write-Host "pid $($proc.Id) written to $PidFile"

$deadline = (Get-Date).AddSeconds($WaitSeconds)
do {
    if ($proc.HasExited) {
        Write-Host "server exited with code $($proc.ExitCode)"
        if (Test-Path $errLog) { Get-Content $errLog -Tail 40 }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        exit 1
    }
    $health = Get-Health
    if ($health -and $health.kernel -eq "ready") {
        $sb = $health.sandbox
        Write-Host "kernel ready"
        Write-Host "  version $($health.version)"
        Write-Host "  sandbox.status $($sb.status)"
        Write-Host "  sandbox.mechanism $($sb.mechanism)"
        Write-Host "  $HealthUrl"
        if (-not $NoSandbox -and $sb.status -ne "active") {
            Write-Host "WARNING: isolation is not active (status=$($sb.status)). See docs/windows/."
        }
        exit 0
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

Write-Host "timed out waiting for kernel: ready (${WaitSeconds}s)"
if (Test-Path $errLog) { Get-Content $errLog -Tail 40 }
exit 1
