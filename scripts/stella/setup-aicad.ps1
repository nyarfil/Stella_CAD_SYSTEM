# Stella CAD — AI-CAD (ai-cad-labs) Windows setup
# Separate from AgentCAD: Python 3.13 + CadQuery. Do not mix venvs.
# Usage: powershell -File scripts\stella\setup-aicad.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AiCad = Join-Path $RepoRoot "ai-cad-labs"
if (-not (Test-Path (Join-Path $AiCad "pyproject.toml"))) {
    Write-Error "ai-cad-labs not found under $RepoRoot"
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$PythonDir = Join-Path $RepoRoot ".python"
$env:UV_PYTHON_INSTALL_DIR = $PythonDir

$CairoBin = "C:\Program Files\GTK3-Runtime Win64\bin"
if (Test-Path $CairoBin) {
    $env:PATH = "$CairoBin;" + $env:PATH
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not on PATH. Install https://docs.astral.sh/uv/ then re-run."
}

Write-Host "Stella AI-CAD setup"
Write-Host "  repo   $RepoRoot"
Write-Host "  aicad  $AiCad"
Write-Host "  python $PythonDir"

& (Join-Path $PSScriptRoot "link-aicad.ps1")

Write-Host "uv $(uv --version)"
uv python install 3.13

Push-Location $AiCad
try {
    if (Test-Path "uv.lock") {
        uv sync --locked --python 3.13
    } else {
        uv sync --python 3.13
    }
} finally {
    Pop-Location
}

$py = Join-Path $AiCad ".venv\Scripts\python.exe"
Write-Host "--- cadquery import ---"
& $py -c "import sys, cadquery; print('python', sys.version.split()[0]); print('executable', sys.executable); print('cadquery', cadquery.__version__)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "cadquery import failed"
}

if (-not (Test-Path $CairoBin)) {
    Write-Host "cairo: GTK3-Runtime not at $CairoBin (renderer may fail; CadQuery import is ok)"
} else {
    Write-Host "cairo: $CairoBin"
}

Write-Host "setup-aicad ok."
Write-Host "Tools:  uv --directory ai-cad-labs run python -m tools.<name>"
Write-Host "Health: powershell -File scripts\stella\aicad-health.ps1"
Write-Host "Dashboard (only if asked): cd ai-cad-labs\frontend; npm install; npm run dev"
