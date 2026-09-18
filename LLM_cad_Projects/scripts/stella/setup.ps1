# Stella CAD — Windows setup
# Python 3.12 + uv sync (locked) for agentcad-for-windows.
# Usage: powershell -File scripts\stella\setup.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AgentCad = Join-Path $RepoRoot "agentcad-for-windows"
if (-not (Test-Path (Join-Path $AgentCad "pyproject.toml"))) {
    Write-Error "agentcad-for-windows not found under $RepoRoot"
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$PythonDir = Join-Path $RepoRoot ".python"
$env:UV_PYTHON_INSTALL_DIR = $PythonDir

Write-Host "Stella setup"
Write-Host "  repo     $RepoRoot"
Write-Host "  agentcad $AgentCad"
Write-Host "  python   $PythonDir  (outside C:\\Users — AppContainer cannot see the user profile)"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not on PATH. Install https://docs.astral.sh/uv/ then re-run."
}

Write-Host "uv $(uv --version)"
uv python install 3.12

$cfg = Join-Path $AgentCad ".venv\pyvenv.cfg"
if (Test-Path $cfg) {
    $homeLine = Get-Content -LiteralPath $cfg | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
    if ($homeLine -match '\\Users\\|AppData\\Roaming\\uv\\python') {
        Write-Host "recreating venv; previous home was under the user profile: $homeLine"
        Remove-Item -LiteralPath (Join-Path $AgentCad ".venv") -Recurse -Force
    }
}

Push-Location $AgentCad
try {
    uv sync --locked --python 3.12
} finally {
    Pop-Location
}

Write-Host "--- font patch (corrupt Windows fonts crash build123d import) ---"
& (Join-Path $AgentCad ".venv\Scripts\python.exe") (Join-Path $PSScriptRoot "windows_font_patch.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "font patch failed"
}

Write-Host "--- versions ---"
& (Join-Path $AgentCad ".venv\Scripts\python.exe") -c "import sys, build123d; print('python', sys.version.split()[0]); print('executable', sys.executable); print('build123d', getattr(build123d, '__version__', '?'))"
if ($LASTEXITCODE -ne 0) {
    Write-Error "build123d import failed"
}

Write-Host "--- Stella bridge (repo-root venv) ---"
Push-Location $RepoRoot
try {
    uv sync --python 3.12
} finally {
    Pop-Location
}

Write-Host "setup ok. PYTHONIOENCODING=utf-8 for this session."
Write-Host "Start the server with: powershell -File scripts\stella\serve.ps1"
