@echo off
taskkill /f /im python.exe >nul 2>&1
echo 診所追蹤系統已關閉
timeout /t 2 /nobreak >nul
