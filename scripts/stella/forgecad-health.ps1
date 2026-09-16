# Print ForgeCAD readiness as JSON. No server.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Tree = Join-Path $RepoRoot "forgecad"
$Cli = Join-Path $Tree "node_modules\forgecad\dist-cli\forgecad.js"

$result = [ordered]@{
    ok      = $false
    workdir = $Tree
    cli     = $Cli
    version = $null
    error   = $null
}

if (-not (Test-Path (Join-Path $Tree "package.json"))) {
    $result.error = "forgecad tree missing"
    $result | ConvertTo-Json -Compress
    exit 1
}
if (-not (Test-Path $Cli)) {
    $result.error = "CLI missing; run scripts\stella\setup-forgecad.ps1"
    $result | ConvertTo-Json -Compress
    exit 1
}

$out = & node $Cli --version 2>&1
if ($LASTEXITCODE -ne 0) {
    $result.error = "forgecad --version failed: $out"
    $result | ConvertTo-Json -Compress
    exit 1
}
$result.version = ($out | Out-String).Trim()
$result.ok = $true
$result | ConvertTo-Json -Compress
exit 0
