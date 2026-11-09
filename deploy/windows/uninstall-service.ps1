#Requires -Version 5.1
<#
.SYNOPSIS
  Stops and removes the BLAIBackend Windows Service. Does not touch
  installed files or the data directory.

.EXAMPLE
  .\deploy\windows\uninstall-service.ps1
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

if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) {
    Write-Host "Stopping service..." -ForegroundColor Cyan
    Stop-Service -Name $serviceName -ErrorAction SilentlyContinue
    Push-Location $backend
    try {
        & $venvPython $serviceScript remove
    } finally {
        Pop-Location
    }
    Write-Host "Removed." -ForegroundColor Green
} else {
    Write-Host "Service '$serviceName' is not installed  -  nothing to do."
}
