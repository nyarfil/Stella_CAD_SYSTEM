# Recreate AI-CAD harness junctions (tools / .claude / .opencode -> .shared).
# Git does not store Windows junctions reliably; setup always repairs them.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AiCad = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "ai-cad-labs"))
$Shared = Join-Path $AiCad ".shared"
if (-not (Test-Path (Join-Path $Shared "tools"))) {
    Write-Error "ai-cad-labs/.shared/tools missing under $RepoRoot"
}

function Test-AiCadPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $root = $AiCad.TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    return $full.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar,
            [System.StringComparison]::OrdinalIgnoreCase)
}

function Ensure-Junction([string]$Link, [string]$Target) {
    $linkFull = [System.IO.Path]::GetFullPath($Link)
    $targetItem = Get-Item -LiteralPath $Target -Force -ErrorAction Stop
    $targetFull = [System.IO.Path]::GetFullPath($targetItem.FullName)
    if (-not (Test-AiCadPath $linkFull) -or -not (Test-AiCadPath $targetFull)) {
        throw "Refusing junction outside ai-cad-labs: $linkFull -> $targetFull"
    }
    if (-not $targetItem.PSIsContainer) {
        throw "Junction target is not a directory: $targetFull"
    }

    $parent = Split-Path -Parent $linkFull
    $parentItem = Get-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue
    if ($parentItem -and -not $parentItem.PSIsContainer) {
        throw "Junction parent is not a directory: $parent"
    }
    if (-not $parentItem) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }

    # Get-Item can see a dangling junction even when Test-Path returns false.
    $item = Get-Item -LiteralPath $linkFull -Force -ErrorAction SilentlyContinue
    if ($item) {
        if ($item.LinkType -notin @("Junction", "SymbolicLink")) {
            throw "Refusing to replace a real file or directory: $linkFull"
        }
        $current = @($item.Target)[0]
        if ($current) {
            $currentFull = if ([System.IO.Path]::IsPathRooted($current)) {
                [System.IO.Path]::GetFullPath($current)
            } else {
                [System.IO.Path]::GetFullPath((Join-Path $parent $current))
            }
            if ($currentFull.Equals($targetFull, [System.StringComparison]::OrdinalIgnoreCase)) {
                return
            }
        }

        # DirectoryInfo.Delete() removes only the reparse point and never traverses
        # the old target, including when that target is missing.
        $item.Delete()
        if (Get-Item -LiteralPath $linkFull -Force -ErrorAction SilentlyContinue) {
            throw "Failed to remove stale junction: $linkFull"
        }
    }

    New-Item -ItemType Junction -Path $linkFull -Target $targetFull | Out-Null
    $created = Get-Item -LiteralPath $linkFull -Force -ErrorAction Stop
    if ($created.LinkType -ne "Junction") {
        throw "Failed to create junction: $linkFull"
    }
}

Ensure-Junction (Join-Path $AiCad "tools") (Join-Path $Shared "tools")
Ensure-Junction (Join-Path $AiCad ".claude\agents") (Join-Path $Shared "agents")
Ensure-Junction (Join-Path $AiCad ".claude\skills") (Join-Path $Shared "skills")
Ensure-Junction (Join-Path $AiCad ".opencode\agents") (Join-Path $Shared "agents")
Ensure-Junction (Join-Path $AiCad ".opencode\skills") (Join-Path $Shared "skills")

Write-Host "aicad junctions ok under $AiCad"
