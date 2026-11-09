#Requires -Version 5.1
<#
.SYNOPSIS
  Backs up the BL-AI data directory (SQLite DB + uploaded PDFs) to a
  timestamped zip. Safe to run while the service is up  -  the database is
  copied through SQLite's own online backup API, not a raw file copy, so a
  concurrent writer can't produce a torn copy.

.EXAMPLE
  .\deploy\windows\backup.ps1
  .\deploy\windows\backup.ps1 -Destination D:\bl-ai-backups -Keep 30
#>
[CmdletBinding()]
param(
    [string]$Destination,
    [int]$Keep = 14
)

$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$backend = Join-Path $root 'backend'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { $venvPython = 'python' }

# Resolve the data dir the same way app.config does (BL_DATA_DIR override,
# else <repo>\data) by just asking it.
Push-Location $backend
try {
    $dataDir = (& $venvPython -c "import app.config as c; print(c.DATA_DIR)").Trim()
} finally {
    Pop-Location
}

if (-not $Destination) { $Destination = Join-Path $root 'backups' }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stageDir = Join-Path $env:TEMP "bl-ai-backup-$stamp"
New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

try {
    $dbPath = Join-Path $dataDir 'bl.db'
    $dbCopy = Join-Path $stageDir 'bl.db'
    if (Test-Path $dbPath) {
        Write-Host "Backing up database (online, consistent snapshot)..." -ForegroundColor Cyan
        & $venvPython -c @"
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
"@ $dbPath $dbCopy
        if ($LASTEXITCODE -ne 0) { throw "database backup failed" }
    } else {
        Write-Warning "No database found at $dbPath  -  skipping."
    }

    $uploadsSrc = Join-Path $dataDir 'uploads'
    if (Test-Path $uploadsSrc) {
        Write-Host "Copying uploads..." -ForegroundColor Cyan
        Copy-Item $uploadsSrc (Join-Path $stageDir 'uploads') -Recurse
    }

    $zipPath = Join-Path $Destination "bl-ai-backup-$stamp.zip"
    Write-Host "Compressing to $zipPath..." -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $stageDir '*') -DestinationPath $zipPath
} finally {
    Remove-Item $stageDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Backup complete: $zipPath" -ForegroundColor Green

if ($Keep -gt 0) {
    $old = Get-ChildItem $Destination -Filter 'bl-ai-backup-*.zip' |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep
    foreach ($f in $old) {
        Write-Host "Pruning old backup: $($f.Name)"
        Remove-Item $f.FullName -Force
    }
}
