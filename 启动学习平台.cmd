@echo off
title PLIAC Learning Platform
cd /d "%~dp0"
python -X utf8 scripts\run.py
if errorlevel 1 pause
