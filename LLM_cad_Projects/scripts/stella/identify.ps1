# Identify Stella's TCP listener vs an unknown occupant. Never kill by scan.
# Dot-source from serve.ps1 and V:\mouse\.cursor\cad-boot.ps1.

function Get-TcpListenPids([int]$Port) {
    $pids = @()
    $lines = & netstat -ano -p tcp 2>$null | Select-String -Pattern ":$Port\s+.*LISTENING"
    foreach ($line in $lines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
        $procId = $parts[-1]
        if ($procId -match '^\d+$') { $pids += [int]$procId }
    }
    if ($pids.Count -eq 0) { return @() }
    return @($pids | Sort-Object -Unique)
}

function Get-ProcessCommandLine([int]$ProcId) {
    $row = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
    if (-not $row) { return "" }
    return [string]$row.CommandLine
}

function Test-StellaCommandLine([string]$Cmd, [string]$RepoRoot) {
    if (-not $Cmd) { return $false }
    $root = $RepoRoot.TrimEnd('\', '/')
    $normCmd = $Cmd.Replace('/', '\').ToLowerInvariant()
    $normRoot = $root.Replace('/', '\').ToLowerInvariant()
    return ($normCmd.Contains($normRoot) -and $normCmd.Contains('agentcad') -and $normCmd.Contains('serve'))
}

function Get-StellaListenPid([int]$Port, [string]$RepoRoot) {
    foreach ($procId in @(Get-TcpListenPids $Port)) {
        $cmd = Get-ProcessCommandLine $procId
        if (Test-StellaCommandLine $cmd $RepoRoot) { return $procId }
    }
    return $null
}

function Get-AgentCadHealth([int]$Port, [int]$TimeoutSec = 15) {
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec $TimeoutSec
        if ($h.status -eq "ok" -and $h.version) { return $h }
    } catch { }
    return $null
}

function Wait-AgentCadHealth {
    param(
        [int]$Port,
        [int]$WaitSeconds = 180,
        [int]$ProbeTimeoutSec = 15,
        [switch]$RequireKernel
    )
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        $h = Get-AgentCadHealth $Port $ProbeTimeoutSec
        if ($h -and ((-not $RequireKernel) -or ($h.kernel -eq "ready"))) { return $h }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    return $null
}

function Sync-StellaPidFile([int]$Port, [string]$PidFile, [string]$RepoRoot) {
    $procId = Get-StellaListenPid $Port $RepoRoot
    if ($null -eq $procId) { return $null }
    $dir = Split-Path $PidFile
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    "$procId" | Set-Content -Path $PidFile -Encoding ascii
    return $procId
}
