[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$NoBrowser,
    [switch]$SkipFrontendInstall
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPython = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
$frontendDirectory = Join-Path $projectRoot "frontend"
$dashboardUrl = "http://localhost:5173"

function Stop-ValidatedListener {
    param(
        [int]$Port,
        [string]$ExpectedCommand,
        [string]$Label
    )

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) {
        Write-Host "$Label is not listening on port $Port."
        return
    }

    foreach ($processId in ($listeners.OwningProcess | Sort-Object -Unique)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
        if (-not $process -or $process.CommandLine -notmatch $ExpectedCommand) {
            $command = if ($process) { $process.CommandLine } else { "<unavailable>" }
            Write-Warning "Refusing to stop PID $processId on port $Port; command was: $command"
            continue
        }
        Stop-Process -Id $processId -Force
        Write-Host "Stopped $Label (PID $processId, port $Port)." -ForegroundColor Green
    }
}

if ($Stop) {
    Write-Host "Stopping Streamline services..." -ForegroundColor Cyan
    Stop-ValidatedListener -Port 5173 -ExpectedCommand "(?i)(vite|npm.*run dev)" -Label "frontend"
    Stop-ValidatedListener -Port 8756 -ExpectedCommand "codirector\.api\.server" -Label "backend"
    Start-Sleep -Milliseconds 500
    Stop-ValidatedListener -Port 4097 -ExpectedCommand "(?i)opencode.*serve.*4097" -Label "OpenCode server"
    Write-Host "Stop request complete. Existing launcher terminals can now be closed." -ForegroundColor Cyan
    exit 0
}

if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Backend virtual environment not found: $backendPython"
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDirectory "package.json"))) {
    throw "Frontend package.json not found in: $frontendDirectory"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found on PATH. Install Node.js 20 or newer."
}

function Test-ListeningPort {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host "Starting Streamline from $projectRoot" -ForegroundColor Cyan

if (Test-ListeningPort -Port 8756) {
    Write-Host "Backend already listening on port 8756; leaving it running." -ForegroundColor Yellow
}
else {
    $backendCommand = "& '$backendPython' -u -m codirector.api.server"
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-Command", $backendCommand) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Normal
    Write-Host "Backend terminal started." -ForegroundColor Green
}

if (Test-ListeningPort -Port 5173) {
    Write-Host "Frontend already listening on port 5173; leaving it running." -ForegroundColor Yellow
}
else {
    $nodeModules = Join-Path $frontendDirectory "node_modules"
    if ((-not $SkipFrontendInstall) -and (-not (Test-Path -LiteralPath $nodeModules))) {
        $frontendCommand = "npm install; if (`$LASTEXITCODE -eq 0) { npm run dev }"
    }
    else {
        $frontendCommand = "npm run dev"
    }
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-Command", $frontendCommand) `
        -WorkingDirectory $frontendDirectory `
        -WindowStyle Normal
    Write-Host "Frontend terminal started." -ForegroundColor Green
}

Write-Host "Waiting for backend and frontend..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    $backendReady = Test-ListeningPort -Port 8756
    $frontendReady = Test-ListeningPort -Port 5173
    if ($backendReady -and $frontendReady) {
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not (Test-ListeningPort -Port 8756)) {
    Write-Warning "Backend did not become ready on port 8756. Check the backend terminal."
}
if (-not (Test-ListeningPort -Port 5173)) {
    Write-Warning "Frontend did not become ready on port 5173. Check the frontend terminal."
}

if ((Test-ListeningPort -Port 8756) -and (Test-ListeningPort -Port 5173)) {
    Write-Host "Streamline is ready: $dashboardUrl" -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $dashboardUrl
    }
}

Write-Host "Close the backend and frontend terminals, or press Ctrl+C in each, to stop the app."
