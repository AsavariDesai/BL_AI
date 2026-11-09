"""Runs the BL-AI backend (run_server.py's Uvicorn server) as a native
Windows Service via pywin32 — starts on boot, restartable from
services.msc / `sc.exe`, logs start/stop to the Windows Event Log.

One-time install (elevated PowerShell, from backend/, venv active):
    python windows_service.py install
    python windows_service.py start

Common commands: stop | restart | remove | status
See deploy/windows/install-service.ps1 for the scripted version, which also
sets the service to auto-restart on failure.
"""
from __future__ import annotations

import os
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil


class BLAIService(win32serviceutil.ServiceFramework):
    _svc_name_ = "BLAIBackend"
    _svc_display_name_ = "BL-AI Backend"
    _svc_description_ = (
        "BL-AI document extraction API — FastAPI served by Uvicorn, "
        "local OCR/KIE, no cloud."
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = None
        self.server_thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.server is not None:
            self.server.should_exit = True
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        # Windows starts services with C:\Windows\System32 as cwd — chdir
        # back to backend/ so app/.env and the default data/ dir resolve the
        # same as a manual run.
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        from run_server import make_server

        self.server = make_server()
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.server_thread.start()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        self.server_thread.join(timeout=30)
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, ""),
        )


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(BLAIService)
