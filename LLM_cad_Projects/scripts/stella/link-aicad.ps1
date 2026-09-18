# Recreate AI-CAD harness junctions (tools / .claude / .opencode -> .shared).
# Git does not store Windows junctions reliably; setup always repairs them.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AiCad = Join-Path $RepoRoot "ai-cad-labs"
$Shared = Join-Path $AiCad ".shared"
if (-not (Test-Path (Join-Path $Shared "tools"))) {
    Write-Error "ai-cad-labs/.shared/tools missing under $RepoRoot"
}

function Ensure-Junction([string]$Link, [string]$Target) {
    $parent = Split-Path $Link
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (Test-Path $Link) {
        $item = Get-Item -LiteralPath $Link -Force
        $current = $null
        if ($item.LinkType -eq "Junction" -or $item.LinkType -eq "SymbolicLink") {
            $current = @($item.Target)[0]
        }
        $want = (Resolve-Path $Target).Path
        if ($current -and ((Resolve-Path $current).Path -eq $want)) {
            return
        }
        cmd /c "rmdir `"$Link`"" | Out-Null
        if (Test-Path $Link) {
            Remove-Item -LiteralPath $Link -Recurse -Force
        }
    }
    New-Item -ItemType Junction -Path $Link -Target $Target | Out-Null
}

Ensure-Junction (Join-Path $AiCad "tools") (Join-Path $Shared "tools")
Ensure-Junction (Join-Path $AiCad ".claude\agents") (Join-Path $Shared "agents")
Ensure-Junction (Join-Path $AiCad ".claude\skills") (Join-Path $Shared "skills")
Ensure-Junction (Join-Path $AiCad ".opencode\agents") (Join-Path $Shared "agents")
Ensure-Junction (Join-Path $AiCad ".opencode\skills") (Join-Path $Shared "skills")

Write-Host "aicad junctions ok under $AiCad"
