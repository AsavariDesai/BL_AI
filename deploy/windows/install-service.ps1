#Requires -Version 5.1
<#
.SYNOPSIS
  Installs the BL-AI backend as a native Windows Service ("BLAIBackend"),
  set to start automatically on boot and restart itself if it crashes.

.DESCRIPTION
  Must be run elevated (as Administrator). Run install.ps1 first.

.EXAMPLE
  .\deploy\windows\install-service.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsIdentity]::GetCurrent().Groups -contains 'S-1-5-32-544')
if (-not $isAdmin) {
    throw "Run this from an elevated (Administrator) PowerShell window."
}

$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$backend = Join-Path $root 'backend'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
$serviceScript = Join-Path $backend 'windows_service.py'
$serviceName = 'BLAIBackend'

if (-not (Test-Path $venvPython)) {
    throw "backend\.venv not found  -  run install.ps1 first."
}

Write-Host "Installing service '$serviceName'..." -ForegroundColor Cyan
Push-Location $backend
try {
    & $venvPython $serviceScript --startup auto install
    if ($LASTEXITCODE -ne 0) { throw "service install failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# Have the Service Control Manager itself restart the process on an
# unexpected crash (3 attempts, 1 minute apart, then give up for a day).
Write-Host "Configuring crash recovery..." -ForegroundColor Cyan
sc.exe failure $serviceName reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null

Write-Host "Starting service..." -ForegroundColor Cyan
Start-Service -Name $serviceName
Start-Sleep -Seconds 2
Get-Service -Name $serviceName | Format-Table -AutoSize

Write-Host "`nDone. Manage it with:" -ForegroundColor Green
Write-Host "  Get-Service $serviceName | Restart-Service"
Write-Host "  Stop-Service $serviceName"
Write-Host "  services.msc  (GUI)"
Write-Host "Logs: Event Viewer -> Windows Logs -> Application (source: $serviceName)"
