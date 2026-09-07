@echo off
cd /d "%~dp0"
:loop
venv\Scripts\python sync_agent.py
echo Sync agent exited. Restarting in 10 seconds...
timeout /t 10 /nobreak >nul
goto loop
