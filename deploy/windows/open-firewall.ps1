#Requires -Version 5.1
<#
.SYNOPSIS
  Opens an inbound Windows Firewall rule for the BL-AI port (default 8000).

.EXAMPLE
  .\deploy\windows\open-firewall.ps1
  .\deploy\windows\open-firewall.ps1 -Port 443   # if fronted by a reverse proxy on 443
#>
[CmdletBinding()]
param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsIdentity]::GetCurrent().Groups -contains 'S-1-5-32-544')
if (-not $isAdmin) {
    throw "Run this from an elevated (Administrator) PowerShell window."
}

$ruleName = "BL-AI (TCP $Port)"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "Rule '$ruleName' already exists  -  skipping."
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP `
        -LocalPort $Port -Action Allow | Out-Null
    Write-Host "Opened inbound TCP $Port." -ForegroundColor Green
}
