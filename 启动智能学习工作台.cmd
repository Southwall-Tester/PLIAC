@echo off
title PLIAC Student Workspace
cd /d "%~dp0"
python -X utf8 scripts\launch.py --student-workspace %*
if errorlevel 1 pause
