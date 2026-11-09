#Requires -Version 5.1
<#
.SYNOPSIS
  First-time setup of BL-AI on a Windows Server (or any Windows machine):
  backend venv + deps, frontend build, data dirs, backend/.env.

.DESCRIPTION
  Run once per machine, from an elevated or non-elevated PowerShell  -  this
  script does not install a service or touch the firewall; see
  install-service.ps1 and open-firewall.ps1 for that.

.EXAMPLE
  cd C:\bl-ai
  .\deploy\windows\install.ps1
#>
[CmdletBinding()]
param(
    # Where uploads / the SQLite DB / model artifacts live. Defaults to
    # <repo>\data. Point this at a data drive that survives a VDI/VM image
    # refresh, e.g. D:\bl-ai-data.
    [string]$DataDir
)

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $root

function Assert-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "'$name' was not found on PATH. $hint"
    }
}

Write-Host "`n[1/6] Checking prerequisites..." -ForegroundColor Cyan
Assert-Command 'python' 'Install Python 3.11+ for Windows (python.org) and re-open this shell.'
Assert-Command 'node'   'Install Node.js 20 LTS for Windows (nodejs.org) and re-open this shell.'
Assert-Command 'npm'    'Comes with Node.js  -  reinstall Node.js if missing.'

$pyVersion = (python --version) 2>&1
Write-Host "  python: $pyVersion"
Write-Host "  node:   $(node --version)"

Write-Host "`n[2/6] Creating backend virtual environment..." -ForegroundColor Cyan
$venv = Join-Path $root 'backend\.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    python -m venv $venv
} else {
    Write-Host "  already exists  -  skipping"
}

Write-Host "`n[3/6] Installing backend dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install -r (Join-Path $root 'backend\requirements.txt') -q
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "`n[4/6] Installing frontend dependencies and building..." -ForegroundColor Cyan
Push-Location $root
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}

Write-Host "`n[5/6] Writing backend\.env..." -ForegroundColor Cyan
$envPath = Join-Path $root 'backend\.env'
if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $root 'backend\.env.example') $envPath
}
if ($DataDir) {
    if (Select-String -Path $envPath -Pattern '^BL_DATA_DIR=' -Quiet) {
        (Get-Content $envPath) -replace '^BL_DATA_DIR=.*', "BL_DATA_DIR=$DataDir" |
            Set-Content $envPath
    } else {
        Add-Content $envPath "BL_DATA_DIR=$DataDir"
    }
    Write-Host "  BL_DATA_DIR set to $DataDir"
}
# Production default: one process serves the built frontend + the API.
if (-not (Select-String -Path $envPath -Pattern '^SERVE_FRONTEND=' -Quiet)) {
    Add-Content $envPath 'SERVE_FRONTEND=1'
}

Write-Host "`n[6/6] Creating data directories..." -ForegroundColor Cyan
Push-Location (Join-Path $root 'backend')
try {
    # Importing app.config creates DATA_DIR/UPLOAD_DIR/MODEL_DIR as a side effect.
    & $venvPython -c "import app.config as c; print(c.DATA_DIR)"
} finally {
    Pop-Location
}

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Create the first admin user:"
Write-Host "       cd backend; ..\backend\.venv\Scripts\python.exe manage.py create-user admin"
Write-Host "  2. Try it out:  backend\.venv\Scripts\python.exe backend\run_server.py"
Write-Host "  3. Install as a Windows Service: .\deploy\windows\install-service.ps1"
Write-Host "  4. Open the firewall port:       .\deploy\windows\open-firewall.ps1"
