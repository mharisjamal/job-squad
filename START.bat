@echo off
title JobSquad
cd /d %~dp0

rem Prefer the Windows Python launcher, fall back to python on PATH.
where py >nul 2>nul
if %errorlevel%==0 (
    py run.py
) else (
    python run.py
)

if errorlevel 1 (
    echo.
    echo JobSquad exited with an error. Read the messages above.
    pause
)
