# Print AI-CAD readiness as JSON. Does not start a server (AI-CAD has none).

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AiCad = Join-Path $RepoRoot "ai-cad-labs"
$Py = Join-Path $AiCad ".venv\Scripts\python.exe"
$CairoBin = "C:\Program Files\GTK3-Runtime Win64\bin"

$result = [ordered]@{
    ok          = $false
    workdir     = $AiCad
    python      = $Py
    cadquery    = $null
    cairo_bin   = $null
    cairo_ok    = $false
    tools_link  = $null
    error       = $null
}

if (-not (Test-Path (Join-Path $AiCad "pyproject.toml"))) {
    $result.error = "ai-cad-labs missing"
    $result | ConvertTo-Json -Compress
    exit 1
}

$tools = Join-Path $AiCad "tools"
if (Test-Path $tools) {
    $item = Get-Item -LiteralPath $tools -Force
    $result.tools_link = @{ type = "$($item.LinkType)"; target = @($item.Target)[0] }
}

if (Test-Path $CairoBin) {
    $result.cairo_bin = $CairoBin
    $result.cairo_ok = $true
    $env:PATH = "$CairoBin;" + $env:PATH
}

if (-not (Test-Path $Py)) {
    $result.error = "venv missing; run scripts\stella\setup-aicad.ps1"
    $result | ConvertTo-Json -Compress
    exit 1
}

$out = & $Py -c "import cadquery; print(cadquery.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    $result.error = "cadquery import failed: $out"
    $result | ConvertTo-Json -Compress
    exit 1
}
$result.cadquery = ($out | Out-String).Trim()
$result.ok = $true
$result | ConvertTo-Json -Compress
exit 0
