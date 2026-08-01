@echo off
chcp 65001 > nul
title TouHou

echo Starting TouHou...
tasklist /FI "IMAGENAME eq touhou.exe" 2>NUL | find /I "touhou.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    start "" "touhou.exe"
    exit /b 0
)

start "" "touhou.exe"
exit /b 0
