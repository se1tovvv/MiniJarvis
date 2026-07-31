@echo off
REM ============================================================
REM  MiniJarvis PC Agent launcher (auto-restarts if it crashes)
REM  Put this next to pc_agent.py, then add a shortcut to it in
REM  the Startup folder so it runs on every login.
REM ============================================================
title MiniJarvis PC Agent
cd /d "%~dp0"
:loop
echo [%date% %time%] starting pc_agent.py ...
python pc_agent.py
echo [%date% %time%] agent stopped, restarting in 3s (Ctrl+C twice to quit) ...
timeout /t 3 /nobreak >nul
goto loop
