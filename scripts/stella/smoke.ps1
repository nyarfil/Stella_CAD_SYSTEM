# Box -> rebuild -> STEP, isolation must stay active.
# Usage: powershell -File scripts\stella\smoke.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
uv run python scripts\stella\smoke.py
exit $LASTEXITCODE
