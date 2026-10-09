@echo off
title Course Learning Agent
cd /d "%~dp0"
python -X utf8 scripts\launch.py %*
if errorlevel 1 pause
