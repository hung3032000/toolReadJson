$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidFile = Join-Path (Join-Path $repoRoot "tmp") "toolreadjson-web.pid"

if (-not (Test-Path $pidFile)) {
    Write-Output "PID file not found. Backend is likely not running."
    exit 0
}

$rawPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
if (-not $rawPid) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Output "PID file was empty and has been removed."
    exit 0
}

try {
    $proc = Get-Process -Id ([int]$rawPid) -ErrorAction Stop
    Stop-Process -Id $proc.Id -Force
    Write-Output "Stopped backend PID $($proc.Id)."
}
catch {
    Write-Output "Process $rawPid is not running anymore."
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
