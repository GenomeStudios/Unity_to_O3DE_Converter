@echo off
cd /d "%~dp0"
start "" pyw main_app.py --tab=scene
if %errorlevel% neq 0 (
    echo Launch failed - retrying with py to show error...
    py main_app.py --tab=scene
    pause
)
