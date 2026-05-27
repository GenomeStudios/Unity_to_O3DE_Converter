@echo off
REM ============================================================================
REM To-O3DE Project Converter - Windows launcher
REM ============================================================================
REM Double-click in Explorer to launch. Mirrors the .sh (Linux) and .command
REM (macOS) siblings - same Python lookup, same arg forwarding, same crash-
REM pause behaviour.
REM ============================================================================

setlocal enableextensions
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM Pick the most specific Python 3.10+ available via the `py` launcher.
REM `py -X.Y` selects an exact installed version; `py -3` falls back to
REM whatever's tagged default. Each candidate is probed with a 1-line script
REM so we don't launch the GUI against a too-old interpreter.
REM ---------------------------------------------------------------------------
set "PY_LAUNCH="
for %%V in (-3.13 -3.12 -3.11 -3.10 -3) do (
    if not defined PY_LAUNCH (
        py %%V -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_LAUNCH=py %%V"
    )
)
if not defined PY_LAUNCH (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_LAUNCH=python"
    )
)

if not defined PY_LAUNCH (
    echo.
    echo Python 3.10 or newer is required but was not found.
    echo Install from https://www.python.org/downloads/ and try again.
    echo.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------------
REM Launch. Try the windowless variant first ("pyw" / -w flag): no console
REM window stays open behind the Qt GUI. If that exits non-zero almost
REM immediately, re-run with the console-visible interpreter so the user sees
REM the traceback before the window closes.
REM
REM The `py` launcher's pythonw equivalent is `pyw` plus the same version
REM flags. We compose it from the PY_LAUNCH we already picked.
REM ---------------------------------------------------------------------------
set "PYW_LAUNCH=%PY_LAUNCH:py=pyw%"

start "" %PYW_LAUNCH% main_app.py %*
if errorlevel 1 (
    echo.
    echo Windowless launch failed - retrying with console attached so the
    echo error is visible...
    %PY_LAUNCH% main_app.py %*
    echo.
    pause
)

endlocal
