@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py
if not defined PY (
  where python >nul 2>nul && set PY=python
)
if not defined PY (
  echo [ERROR] Python not found. Install Python 3 and tick ADD TO PATH.
  echo Then rerun this. Download: https://www.python.org/downloads/
  pause >nul
  exit /b 1
)
echo Using: %PY%
echo Ensure seu_xk.txt (account/password) is in this same folder.
%PY% -u tongxuan_grab.py
echo.
echo Script finished. Press any key to close...
pause >nul
