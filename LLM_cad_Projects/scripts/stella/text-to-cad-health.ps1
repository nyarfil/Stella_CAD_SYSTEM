# Print text-to-cad / cadgen readiness as JSON. No server.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Tree = Join-Path $RepoRoot "text-to-cad"
$Py = Join-Path $Tree ".venv\Scripts\python.exe"
$Cli = Join-Path $Tree ".venv\Scripts\cadgen.exe"

$result = [ordered]@{
    ok         = $false
    workdir    = $Tree
    python     = $Py
    cli        = $Cli
    cadgen     = $null
    python_ver = $null
    error      = $null
}

if (-not (Test-Path (Join-Path $Tree "skills\cad\SKILL.md"))) {
    $result.error = "text-to-cad tree missing"
    $result | ConvertTo-Json -Compress
    exit 1
}
if (-not (Test-Path $Py)) {
    $result.error = "venv missing; run scripts\stella\setup-text-to-cad.ps1"
    $result | ConvertTo-Json -Compress
    exit 1
}

$out = & $Py -c "import sys,cadgen; print(sys.version.split()[0]); print(getattr(cadgen,'__version__','?'))" 2>&1
if ($LASTEXITCODE -ne 0) {
    $result.error = "cadgen import failed: $out"
    $result | ConvertTo-Json -Compress
    exit 1
}
$lines = @(($out | Out-String).Trim() -split "`r?`n") | Where-Object { $_ }
$result.python_ver = $lines[0]
$result.cadgen = $lines[-1]
if (-not (Test-Path $Cli)) {
    $result.error = "cadgen.exe missing"
    $result | ConvertTo-Json -Compress
    exit 1
}
$result.ok = $true
$result | ConvertTo-Json -Compress
exit 0
