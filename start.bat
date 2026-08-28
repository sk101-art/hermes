@echo off
REM ============================================================
REM  HERMES one-click launcher
REM  Starts all three components, each in its own terminal:
REM    1. Backend API   - FastAPI/Uvicorn on http://127.0.0.1:8765
REM    2. Daemon        - autonomous background runtime (30s poll)
REM    3. Frontend      - Vite dev server on http://127.0.0.1:5173
REM ============================================================
cd /d "%~dp0"

set "PY=C:\Program Files\Python311\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo  [1/3] Starting HERMES Backend API (port 8765)...
start "HERMES Backend API" cmd /k ""%PY%" -m app.api.server --port 8765"

REM Give the API a moment to bind the port before the daemon starts.
timeout /t 2 /nobreak >nul

echo  [2/3] Starting HERMES Background Daemon...
start "HERMES Daemon" cmd /k ""%PY%" -m app.runtime.runner"

echo  [3/3] Starting HERMES Frontend Dev Server (port 5173)...
pushd frontend
start "HERMES Frontend" cmd /k "npm run dev"
popd

echo.
echo  All components launched:
echo    Backend API : http://127.0.0.1:8765   (Swagger: /docs)
echo    Daemon      : continuous runtime loop (Ctrl+C in its window to stop)
echo    Frontend    : http://127.0.0.1:5173
echo.
echo  Close each terminal window to stop that component.
echo.
pause
