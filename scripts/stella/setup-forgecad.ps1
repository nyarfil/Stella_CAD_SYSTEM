# Stella CAD — ForgeCAD Windows setup
# Local npm pin. Do not use the global `forgecad` on PATH as the Stella copy.
# Usage: powershell -File scripts\stella\setup-forgecad.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Tree = Join-Path $RepoRoot "forgecad"
if (-not (Test-Path (Join-Path $Tree "package.json"))) {
    Write-Error "forgecad/package.json missing under $RepoRoot"
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "node is not on PATH. Install Node.js 20+ then re-run."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm is not on PATH."
}

$nodeVer = (node -v).Trim()
Write-Host "Stella ForgeCAD setup"
Write-Host "  repo $RepoRoot"
Write-Host "  tree $Tree"
Write-Host "  node $nodeVer"

Push-Location $Tree
try {
    npm install --no-fund --no-audit
} finally {
    Pop-Location
}

$cli = Join-Path $Tree "node_modules\forgecad\dist-cli\forgecad.js"
if (-not (Test-Path $cli)) {
    Write-Error "forgecad CLI missing after npm install: $cli"
}

Write-Host "--- version ---"
& node $cli --version
if ($LASTEXITCODE -ne 0) {
    Write-Error "forgecad --version failed"
}

Write-Host "setup-forgecad ok."
Write-Host "CLI:    node `"$cli`""
Write-Host "Health: powershell -File scripts\stella\forgecad-health.ps1"
