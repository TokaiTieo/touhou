@echo off
chcp 65001 > nul
title Stop touhou

echo ================================================
echo   Stop touhou Server
echo ================================================
echo.

tasklist /FI "IMAGENAME eq touhou.exe" 2>NUL | find /I /N "touhou.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Stopping server...
    taskkill /F /IM touhou.exe > nul 2>&1
    echo [INFO] Server stopped
) else (
    echo [INFO] Server is not running
)

echo.
pause