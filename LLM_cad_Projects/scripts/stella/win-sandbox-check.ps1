# Run the Windows AppContainer battery N times.
# Isolation must stay on. A skip is a red result under AGENTCAD_EXPECT_SANDBOX=active.
# Usage: powershell -File scripts\stella\win-sandbox-check.ps1
#        powershell -File scripts\stella\win-sandbox-check.ps1 -Times 5

param(
    [int]$Times = 5
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AgentCad = Join-Path $RepoRoot "agentcad-for-windows"

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:AGENTCAD_EXPECT_SANDBOX = "active"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RepoRoot ".python"
if (Test-Path Env:AGENTCAD_NO_SANDBOX) {
    Remove-Item Env:AGENTCAD_NO_SANDBOX
}

Write-Host "win-sandbox-check: $Times run(s), AGENTCAD_EXPECT_SANDBOX=active"
$failed = 0
for ($i = 1; $i -le $Times; $i++) {
    Write-Host "=== run $i / $Times ==="
    Push-Location $AgentCad
    try {
        uv run pytest -q tests/test_sandbox_windows.py --tb=short
        if ($LASTEXITCODE -ne 0) {
            $failed += 1
            Write-Host "run $i FAILED (exit $LASTEXITCODE)"
        } else {
            Write-Host "run $i ok"
        }
    } finally {
        Pop-Location
    }
}

if ($failed -gt 0) {
    Write-Error "$failed / $Times runs failed"
    exit 1
}
Write-Host "$Times / $Times green"
exit 0
