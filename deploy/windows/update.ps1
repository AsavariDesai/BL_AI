#Requires -Version 5.1
<#
.SYNOPSIS
  Maintenance/upgrade: back up the data dir, pull latest code (if this is a
  git checkout), reinstall dependencies, rebuild the frontend, and restart
  the Windows Service.

.EXAMPLE
  .\deploy\windows\update.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipBackup,
    [switch]$SkipGitPull
)

$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsIdentity]::GetCurrent().Groups -contains 'S-1-5-32-544')
if (-not $isAdmin) {
    throw "Run this from an elevated (Administrator) PowerShell window (it restarts the service)."
}

$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$backend = Join-Path $root 'backend'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
$serviceName = 'BLAIBackend'
$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if (-not $SkipBackup) {
    Write-Host "`n[1/5] Backing up data..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'backup.ps1')
} else {
    Write-Host "`n[1/5] Skipping backup (-SkipBackup)" -ForegroundColor Yellow
}

if ($service -and $service.Status -eq 'Running') {
    Write-Host "`n[2/5] Stopping service..." -ForegroundColor Cyan
    Stop-Service -Name $serviceName
} else {
    Write-Host "`n[2/5] Service not running  -  nothing to stop." -ForegroundColor Yellow
}

if (-not $SkipGitPull) {
    Write-Host "`n[3/5] Pulling latest code..." -ForegroundColor Cyan
    Push-Location $root
    try {
        if (Test-Path (Join-Path $root '.git')) {
            git pull --ff-only
            if ($LASTEXITCODE -ne 0) { throw "git pull failed" }
        } else {
            Write-Host "  not a git checkout  -  skipping (deploy the new code yourself first)."
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[3/5] Skipping git pull (-SkipGitPull)" -ForegroundColor Yellow
}

Write-Host "`n[4/5] Reinstalling dependencies and rebuilding frontend..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $backend 'requirements.txt') -q
Push-Location $root
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}

if ($service) {
    Write-Host "`n[5/5] Starting service..." -ForegroundColor Cyan
    Start-Service -Name $serviceName
    Start-Sleep -Seconds 2
    Get-Service -Name $serviceName | Format-Table -AutoSize
} else {
    Write-Host "`n[5/5] Service '$serviceName' isn't installed  -  run install-service.ps1 or start run_server.py manually." -ForegroundColor Yellow
}

Write-Host "`nUpdate complete." -ForegroundColor Green
