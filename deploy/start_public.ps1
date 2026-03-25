param(
    [switch]$Restart,
    [string]$NginxRoot = "C:\Users\hung.pn\Downloads\nginx-1.29.4\nginx-1.29.4"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendScript = Join-Path $PSScriptRoot "start_web_prod.ps1"
$sampleConfPath = Join-Path $repoRoot "deploy\nginx\toolreadjson.windows.conf"
$nginxExe = Join-Path $NginxRoot "nginx.exe"
$nginxConfPath = Join-Path $NginxRoot "conf\nginx.conf"
$runDir = Join-Path $repoRoot "tmp"

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

function Invoke-Nginx {
    param(
        [string[]]$Arguments = @()
    )

    $cleanArguments = @($Arguments | Where-Object { $_ -ne $null -and "$_".Trim() -ne "" })
    $stdoutFile = Join-Path $runDir "start_public.nginx.stdout.log"
    $stderrFile = Join-Path $runDir "start_public.nginx.stderr.log"

    Remove-Item $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue

    $startParams = @{
        FilePath = $nginxExe
        WorkingDirectory = $NginxRoot
        RedirectStandardOutput = $stdoutFile
        RedirectStandardError = $stderrFile
        PassThru = $true
    }
    if ($cleanArguments.Count -gt 0) {
        $startParams.ArgumentList = $cleanArguments
        $startParams.Wait = $true
    }

    $process = Start-Process @startParams
    if ($cleanArguments.Count -eq 0) {
        Start-Sleep -Seconds 1
    }

    $output = @()
    if (Test-Path $stdoutFile) {
        $output += Get-Content $stdoutFile -ErrorAction SilentlyContinue
    }
    if (Test-Path $stderrFile) {
        $output += Get-Content $stderrFile -ErrorAction SilentlyContinue
    }

    return @{
        ExitCode = if ($cleanArguments.Count -gt 0 -or $process.HasExited) { $process.ExitCode } else { 0 }
        Output = $output
    }
}

function Get-LanIPv4 {
    $ips = @()

    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -and
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*"
            } |
            Select-Object -ExpandProperty IPAddress -Unique
    }
    catch {
        $ips = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
            ForEach-Object { $_.IPAddressToString } |
            Where-Object { $_ -notlike "127.*" -and $_ -notlike "169.254.*" } |
            Select-Object -Unique
    }

    $preferred = $ips | Where-Object {
        $_ -match '^10\.' -or
        $_ -match '^192\.168\.' -or
        $_ -match '^172\.(1[6-9]|2[0-9]|3[0-1])\.'
    } | Select-Object -First 1

    if ($preferred) {
        return $preferred
    }

    return ($ips | Select-Object -First 1)
}

function Wait-HttpHealthy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$Attempts = 25,
        [int]$DelaySeconds = 1
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 10
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
            Start-Sleep -Seconds $DelaySeconds
            continue
        }

        Start-Sleep -Seconds $DelaySeconds
    }

    return $false
}

function Get-NginxAccessHint {
    param(
        [string]$Details
    )

    if ($Details -match 'Access is denied') {
        return " Ensure the current user can write to '$NginxRoot\\logs' and manage '$NginxRoot\\logs\\nginx.pid'."
    }

    return ""
}

if (-not (Test-Path $backendScript)) {
    throw "Backend start script not found: $backendScript"
}

if (-not (Test-Path $nginxExe)) {
    throw "nginx.exe not found under '$NginxRoot'. Expected: $nginxExe"
}

if (-not (Test-Path $nginxConfPath)) {
    throw "nginx.conf not found under '$NginxRoot'. Expected: $nginxConfPath"
}

$backendArgs = @()
if ($Restart) {
    $backendArgs += "-Restart"
}

try {
    $backendOutput = & $backendScript @backendArgs 2>&1
}
catch {
    $details = ($_.Exception.Message | Out-String).Trim()
    throw "Backend start failed. $details"
}
$backendStatus = ((($backendOutput | Where-Object { $_ }) | Select-Object -Last 1) | Out-String).Trim()
if (-not $backendStatus) {
    $backendStatus = "backend command completed"
}

$nginxTest = Invoke-Nginx -Arguments @("-t")
$nginxTestStatus = $nginxTest.ExitCode
if ($nginxTestStatus -ne 0) {
    $details = ($nginxTest.Output | Out-String).Trim()
    $hint = Get-NginxAccessHint -Details $details
    throw "nginx config test failed for '$nginxConfPath'. Verify the active nginx config or copy the sample from '$sampleConfPath'.$hint Details: $details"
}

$nginxRunning = Get-Process nginx -ErrorAction SilentlyContinue | Select-Object -First 1
if ($nginxRunning) {
    $nginxCall = Invoke-Nginx -Arguments @("-s", "reload")
    $nginxStatus = $nginxCall.ExitCode
    if ($nginxStatus -ne 0) {
        $details = ($nginxCall.Output | Out-String).Trim()
        $hint = Get-NginxAccessHint -Details $details
        throw "nginx reload failed under '$NginxRoot'.$hint Details: $details"
    }
    $nginxMessage = "reloaded nginx on port 80"
}
else {
    $nginxCall = Invoke-Nginx
    $nginxStatus = $nginxCall.ExitCode
    if ($nginxStatus -ne 0) {
        $details = ($nginxCall.Output | Out-String).Trim()
        $hint = Get-NginxAccessHint -Details $details
        throw "nginx start failed under '$NginxRoot'.$hint Details: $details"
    }
    Start-Sleep -Seconds 2
    $nginxRunning = Get-Process nginx -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $nginxRunning) {
        throw "nginx did not stay running after start under '$NginxRoot'."
    }
    $nginxMessage = "started nginx on port 80"
}

$backendHealthy = Wait-HttpHealthy -Url "http://127.0.0.1:8000/healthz"
if (-not $backendHealthy) {
    throw "Backend health check failed at http://127.0.0.1:8000/healthz"
}

$localProxyHealthy = Wait-HttpHealthy -Url "http://127.0.0.1/healthz"
if (-not $localProxyHealthy) {
    throw "nginx local health check failed at http://127.0.0.1/healthz"
}

$lanIp = Get-LanIPv4

Write-Output "Mode: LAN only"
Write-Output "Backend: $backendStatus"
Write-Output "nginx: $nginxMessage (root: $NginxRoot)"
Write-Output "Local URL: http://127.0.0.1/"
if ($lanIp) {
    Write-Output "LAN URL: http://$lanIp/"
}
else {
    Write-Output "LAN URL: unable to detect a LAN IPv4 address automatically"
}
Write-Output "Note: use this only inside your local network. This script does not change firewall or any network policy."
