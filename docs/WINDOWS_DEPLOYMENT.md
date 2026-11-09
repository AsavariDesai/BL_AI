# Windows Server deployment

BL-AI has no Unix-specific code anywhere in it — storage paths use `pathlib`
(not hardcoded `/`), OCR runs on `onnxruntime`'s CPU build (a prebuilt wheel,
no compiler), and `app/auth.py` deliberately uses only the stdlib for
password hashing to avoid another compiled-extension install on Windows. This
doc covers the part that *was* missing: running it as a real, boot-persistent
service on Windows Server, with install/upgrade/backup scripts instead of
manual steps.

All scripts below live in [deploy/windows/](../deploy/windows/) and are
PowerShell (`.ps1`), run from the repo root unless noted.

## 1. Prerequisites

Install on the server, then open a new PowerShell window so `PATH` picks
them up:

- **Python 3.11+** for Windows — [python.org](https://www.python.org/downloads/windows/).
  During install, tick "Add python.exe to PATH".
- **Node.js 20 LTS** for Windows — [nodejs.org](https://nodejs.org/) (only
  needed to build the frontend; the built static files are what actually
  gets served in production).
- Nothing else. No Visual C++ Build Tools, no WSL, no Docker Desktop — every
  Python dependency ships a Windows wheel.

## 2. Install

```powershell
cd C:\bl-ai                      # wherever you deployed the repo
.\deploy\windows\install.ps1
```

This creates `backend\.venv`, installs backend + frontend dependencies,
builds the frontend (`frontend\dist`), copies `backend\.env.example` to
`backend\.env` (with `SERVE_FRONTEND=1`, so one process serves the UI and the
API on one port), and creates the data directories.

Point the data directory at a drive that survives a VM/VDI image refresh:

```powershell
.\deploy\windows\install.ps1 -DataDir D:\bl-ai-data
```

Then create the first admin login:

```powershell
cd backend
..\backend\.venv\Scripts\python.exe manage.py create-user admin
cd ..
```

Smoke-test it in the foreground before installing the service:

```powershell
backend\.venv\Scripts\python.exe backend\run_server.py
```

Visit `http://localhost:8000` — Ctrl+C to stop once it looks right.

## 3. Run it as a Windows Service

`backend\windows_service.py` wraps the same production server
(`run_server.py`) as a native Windows Service via `pywin32`, so it starts on
boot, is manageable from `services.msc`/`sc.exe`, and logs to the Windows
Event Log.

```powershell
# elevated PowerShell (Run as Administrator)
.\deploy\windows\install-service.ps1
```

This installs the service (`BLAIBackend`, startup type Automatic), tells the
Service Control Manager to restart it automatically if it ever crashes, and
starts it.

Day-to-day management:

```powershell
Get-Service BLAIBackend
Restart-Service BLAIBackend
Stop-Service BLAIBackend
```

or `services.msc` → "BL-AI Backend". Logs: Event Viewer → Windows Logs →
Application, source `BLAIBackend`.

To remove it: `.\deploy\windows\uninstall-service.ps1` (elevated). This only
removes the service registration — code and data are untouched.

## 4. Network access

Open the port in Windows Firewall (default 8000; pass `-Port` if you changed
`PORT` in `backend\.env` or if a reverse proxy means only its port needs to
be open instead):

```powershell
.\deploy\windows\open-firewall.ps1
```

### Optional: TLS / a real hostname in front of it

The app itself can be reached directly on its port, but for a production URL
with HTTPS, put a reverse proxy in front of it:

- **Caddy** (simplest — automatic HTTPS, one binary, no IIS): see
  [deploy/windows/Caddyfile.example](../deploy/windows/Caddyfile.example).
- **IIS**, if your org standardizes on it: install the *Application Request
  Routing* and *URL Rewrite* modules, add a reverse-proxy rule to
  `http://127.0.0.1:8000`, and terminate TLS in IIS as usual.

Whichever you use, once HTTPS is actually in front of the app, set
`COOKIE_SECURE=1` in `backend\.env` and restart the service — browsers
silently drop the session cookie over plain HTTP, so this must stay `0`
until TLS is really there.

## 5. Backup

```powershell
.\deploy\windows\backup.ps1
```

Zips the SQLite database and `data\uploads` into `backups\bl-ai-backup-
<timestamp>.zip`, keeping the last 14 by default (`-Keep`). The database is
copied through SQLite's own online-backup API (not a raw file copy), so this
is safe to run while the service is up — no torn copies from a concurrent
writer. `-Destination` points it at another drive/share for off-box backups.

Schedule it with Task Scheduler (daily, `Action: powershell.exe -File
C:\bl-ai\deploy\windows\backup.ps1`).

To restore: stop the service, replace `backend\data\bl.db` and
`data\uploads` (or your `BL_DATA_DIR`) with the unzipped backup, start the
service again.

## 6. Upgrading

```powershell
# elevated PowerShell
.\deploy\windows\update.ps1
```

Backs up the data dir, `git pull`s if this is a git checkout, reinstalls
Python/Node dependencies, rebuilds the frontend, and restarts the service.
Pass `-SkipGitPull` if you deploy new code some other way (robocopy, CI
artifact, etc.) and just want the dependency/build/restart steps.

## 7. Why one process, not several workers

`backend\app\service.py` runs OCR extraction through a single-worker thread
pool on purpose (contention control — see its comment), and the SQLite
database is a single file that doesn't benefit from multiple writers either.
`run_server.py` matches that with one Uvicorn worker process rather than a
Gunicorn-style multi-worker setup (Gunicorn itself doesn't run on Windows —
it needs `fork`). If OCR throughput ever becomes the bottleneck under real
load, the fix is raising that thread pool's `max_workers`, not adding Uvicorn
worker processes.

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Service won't start; Event Log shows an import error | `backend\.venv` wasn't built with `install.ps1`, or `requirements.txt` changed since — rerun `install.ps1` or `pip install -r requirements.txt`. |
| Browser can't reach the server from another machine | Firewall port not open (`open-firewall.ps1`), or `HOST` in `backend\.env` was narrowed from the default `0.0.0.0`. |
| Login works but the session doesn't stick | `COOKIE_SECURE=1` is set but the site isn't actually served over HTTPS yet — browsers drop the cookie silently. Set it back to `0` until TLS is in front of the app. |
| Upload/OCR is slow with several people uploading at once | Expected with the single-worker OCR pool by design — see §7. Not a Windows-specific issue. |
| Antivirus flags or slows down PDF processing | Add `data\uploads` and `data\tokcache` (or your `BL_DATA_DIR`) to the antivirus's scan exclusions — they hold user-uploaded PDFs and an OCR result cache, not executables. |
| `install-service.ps1` fails with `ImportError: DLL load failed` for `pywintypesXX` / `pythoncomXX` | Rare, on older pywin32 wheels. Run `backend\.venv\Scripts\python.exe backend\.venv\Scripts\pywin32_postinstall.py -install` once, then retry. |
