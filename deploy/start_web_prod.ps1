param(
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runDir = Join-Path $repoRoot "tmp"
$pidFile = Join-Path $runDir "toolreadjson-web.pid"
$stdoutLog = Join-Path $runDir "toolreadjson-web.stdout.log"
$stderrLog = Join-Path $runDir "toolreadjson-web.stderr.log"
$port = 8000

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

function Get-RunningProcess {
    if (-not (Test-Path $pidFile)) {
        return $null
    }

    $rawPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $rawPid) {
        return $null
    }

    try {
        return Get-Process -Id ([int]$rawPid) -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Get-ListenerProcess {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -First 1
        if (-not $conn) {
            return $null
        }
        return Get-Process -Id $conn.OwningProcess -ErrorAction Stop
    }
    catch {
        return $null
    }
}

$existing = Get-RunningProcess
$listener = Get-ListenerProcess

if ($listener -and -not $Restart) {
    Set-Content -Path $pidFile -Value $listener.Id -Encoding ascii
    Write-Output "Backend already listening on http://127.0.0.1:$port with PID $($listener.Id)."
    exit 0
}

if ($existing -and -not $Restart) {
    Write-Output "Backend already running with PID $($existing.Id)."
    exit 0
}

if ($existing -and $Restart) {
    Stop-Process -Id $existing.Id -Force
    Start-Sleep -Seconds 1
}

if ($listener -and $Restart -and (-not $existing -or $listener.Id -ne $existing.Id)) {
    throw "Port $port is already in use by PID $($listener.Id). Stop that process first, then run with -Restart again."
}

$pythonCandidates = @(
    (Join-Path $repoRoot ".venv\\Scripts\\python.exe"),
    (Join-Path $repoRoot "venv\\Scripts\\python.exe"),
    "python"
)

$pythonCmd = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "python") {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) {
            $pythonCmd = $command.Source
            break
        }
        continue
    }

    if (Test-Path $candidate) {
        $pythonCmd = $candidate
        break
    }
}

if (-not $pythonCmd) {
    throw "Cannot find Python interpreter. Activate venv or install Python first."
}

$arguments = @(
    "-m",
    "uvicorn",
    "app_web:app",
    "--host",
    "127.0.0.1",
    "--port",
    "$port",
    "--proxy-headers",
    "--forwarded-allow-ips=*"
)

$process = Start-Process `
    -FilePath $pythonCmd `
    -ArgumentList $arguments `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
if ($process.HasExited) {
    $stderr = ""
    if (Test-Path $stderrLog) {
        $stderr = (Get-Content $stderrLog -ErrorAction SilentlyContinue | Select-Object -Last 20) -join [Environment]::NewLine
    }
    throw "Backend exited right after start. $stderr"
}

Set-Content -Path $pidFile -Value $process.Id -Encoding ascii
Write-Output "Started backend with PID $($process.Id) on http://127.0.0.1:$port"
