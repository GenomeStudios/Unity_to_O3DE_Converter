#!/usr/bin/env bash
# =============================================================================
# To-O3DE Project Converter — Linux launcher
# =============================================================================
# Mirrors To_O3DE_Project_Converter.bat for Linux/macOS hosts. Run from any
# location; the script cd's into its own directory so the Python imports
# resolve.
#
# First-time setup (one line):
#     chmod +x To_O3DE_Project_Converter.sh
#
# After that, double-click in a file manager OR run from a terminal:
#     ./To_O3DE_Project_Converter.sh
# =============================================================================

set -u

# Resolve the script's own directory (handles symlinks, relative invocation).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || {
    echo "Failed to enter script directory: $SCRIPT_DIR" >&2
    exit 1
}

# Pick the most specific Python 3.10+ available. PySide6 + the project's
# annotations require 3.10 minimum.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        version_ok="$("$candidate" -c 'import sys; print("yes" if sys.version_info >= (3,10) else "no")' 2>/dev/null)"
        if [ "$version_ok" = "yes" ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    msg="Python 3.10 or newer is required but was not found on PATH.
Install Python 3.10+ (sudo apt install python3.10 / brew install python@3.13)
and try again."
    echo "$msg" >&2
    # No-TTY launch (file manager): surface the error graphically if a
    # standard dialog tool is available.
    if [ ! -t 1 ]; then
        if command -v zenity >/dev/null 2>&1; then
            zenity --error --title "To-O3DE Project Converter" --text "$msg"
        elif command -v kdialog >/dev/null 2>&1; then
            kdialog --error "$msg"
        elif command -v osascript >/dev/null 2>&1; then
            osascript -e "display alert \"To-O3DE Project Converter\" message \"$msg\""
        fi
    else
        read -rp "Press Enter to close..."
    fi
    exit 1
fi

# Forward any args (e.g. `./To_O3DE_Project_Converter.sh --tab=scene`).
"$PYTHON" main_app.py "$@"
exit_code=$?

# If launched from a terminal and the app crashed, hold the window open
# so the user can read the traceback before it disappears.
if [ "$exit_code" -ne 0 ] && [ -t 1 ]; then
    echo
    echo "Launch failed with exit code $exit_code."
    read -rp "Press Enter to close..."
fi

exit "$exit_code"
