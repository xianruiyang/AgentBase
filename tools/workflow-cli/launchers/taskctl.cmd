@echo off
setlocal
where py.exe >nul 2>nul
if not errorlevel 1 (
  py.exe -3 -X utf8 "%~dp0src\taskctl.py" %*
) else (
  python.exe -X utf8 "%~dp0src\taskctl.py" %*
)
exit /b %errorlevel%
