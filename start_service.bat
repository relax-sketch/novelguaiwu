@echo off
setlocal

rem Always run from the project directory.
cd /d "%~dp0"

set "SERVICE_URL=http://127.0.0.1:8765/"
set "UV_EXE=%APPDATA%\Python\Python312\Scripts\uv.exe"
if not exist "%UV_EXE%" set "UV_EXE=uv"

rem Reuse the running service when it is already available.
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%SERVICE_URL%'; if ($r.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto open_page

if not exist "runtime" mkdir "runtime"
echo Starting the library service in the background...
start "" /b "%UV_EXE%" run python -m library.app --db runtime\library.sqlite3 serve >"runtime\service.log" 2>&1

rem Wait up to 20 seconds, then open the management page.
for /l %%I in (1,1,20) do (
    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%SERVICE_URL%'; if ($r.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 goto open_page
    ping 127.0.0.1 -n 2 >nul
)

echo.
echo Service startup failed. See runtime\service.log
pause
exit /b 1

:open_page
start "" "%SERVICE_URL%"
endlocal
exit /b 0
