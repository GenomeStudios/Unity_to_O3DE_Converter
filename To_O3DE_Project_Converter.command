#!/usr/bin/env bash
# =============================================================================
# To-O3DE Project Converter — macOS launcher
# =============================================================================
# Double-click in Finder to launch (macOS opens .command files in Terminal).
# Mirrors the .bat (Windows) and .sh (Linux) siblings — same Python lookup,
# same arg forwarding, same crash-pause behaviour.
#
# First-time setup (one line):
#     chmod +x To_O3DE_Project_Converter.command
#
# If Finder refuses to launch the first time, right-click → Open → confirm
# the unsigned-script prompt (Gatekeeper). After that double-clicks work.
# =============================================================================

set -u

# Resolve the script's own directory (handles symlinks, relative invocation).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || {
    echo "Failed to enter script directory: $SCRIPT_DIR" >&2
    exit 1
}

# Pick the most specific Python 3.10+ available. macOS systems typically
# have Homebrew (python3.13, etc.) and/or the Xcode CLT python3 (currently
# 3.9 on some installs — too old). Look most-specific first.
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
Install via Homebrew:  brew install python@3.13
Or download from:      https://www.python.org/downloads/macos/"
    echo "$msg" >&2
    # No-TTY launch (rare for .command; happens if user runs via 'open'):
    # surface graphically via osascript.
    if [ ! -t 1 ] && command -v osascript >/dev/null 2>&1; then
        osascript -e "display alert \"To-O3DE Project Converter\" message \"$msg\""
    else
        read -rp "Press Enter to close..."
    fi
    exit 1
fi

# Forward any args (e.g. `--tab=scene`).
"$PYTHON" main_app.py "$@"
exit_code=$?

# Hold the Terminal window open if the app crashed so the user can read
# the traceback before macOS closes it.
if [ "$exit_code" -ne 0 ] && [ -t 1 ]; then
    echo
    echo "Launch failed with exit code $exit_code."
    read -rp "Press Enter to close..."
fi

exit "$exit_code"
