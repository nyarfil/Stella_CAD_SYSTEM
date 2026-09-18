# Stella CAD — text-to-cad (cadgen) Windows setup
# Separate venv. Do not mix with AgentCAD 3.12 or AI-CAD CadQuery.
# Usage: powershell -File scripts\stella\setup-text-to-cad.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Tree = Join-Path $RepoRoot "text-to-cad"
$Req = Join-Path $Tree "skills\cad\requirements.txt"
if (-not (Test-Path $Req)) {
    Write-Error "text-to-cad/skills/cad/requirements.txt missing under $RepoRoot"
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$PythonDir = Join-Path $RepoRoot ".python"
$env:UV_PYTHON_INSTALL_DIR = $PythonDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not on PATH. Install https://docs.astral.sh/uv/ then re-run."
}

Write-Host "Stella text-to-cad setup"
Write-Host "  repo  $RepoRoot"
Write-Host "  tree  $Tree"
Write-Host "  python $PythonDir"

Write-Host "uv $(uv --version)"
uv python install 3.13

$venv = Join-Path $Tree ".venv"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    uv venv --python 3.13 $venv
}

Write-Host "--- cadgen from skills/cad/requirements.txt ---"
uv pip install --python $py -r $Req

$fontPy = Join-Path $venv "Lib\site-packages\build123d\text.py"
Write-Host "--- font patch ---"
& $py (Join-Path $PSScriptRoot "windows_font_patch.py") $fontPy
if ($LASTEXITCODE -ne 0) {
    Write-Error "font patch failed"
}

Write-Host "--- import ---"
& $py -c "import sys, cadgen, build123d; print('python', sys.version.split()[0]); print('executable', sys.executable); print('cadgen', getattr(cadgen, '__version__', '?')); print('build123d', getattr(build123d, '__version__', '?'))"
if ($LASTEXITCODE -ne 0) {
    Write-Error "cadgen/build123d import failed"
}

$cadgen = Join-Path $venv "Scripts\cadgen.exe"
if (-not (Test-Path $cadgen)) {
    Write-Error "cadgen.exe missing: $cadgen"
}

Write-Host "setup-text-to-cad ok."
Write-Host "CLI:    $cadgen"
Write-Host "Health: powershell -File scripts\stella\text-to-cad-health.ps1"
Write-Host "Skills: text-to-cad\skills\  (do not copy into .cursor\skills)"
Write-Host "Note:   playwright chromium is not installed here; snapshots need: $py -m playwright install chromium"
