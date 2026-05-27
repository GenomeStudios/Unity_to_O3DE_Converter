"""
=============================================================================
HEADLESS Qt APP FIXTURE
=============================================================================

Test code that touches PySide6 widgets needs a ``QApplication``
running. This module provides a singleton helper that:

  1. Sets ``QT_QPA_PLATFORM=offscreen`` before importing PySide6
     (the off-screen plugin doesn't need a display server).
  2. Sets ``U2O_SKIP_CLOSE_PROMPT=1`` so MainWindow close-event
     prompts never fire during tests (otherwise tests flood the
     user's machine with "save before close?" dialogs).
  3. Returns the QApplication instance, creating it on first call.

Stdout is reconfigured to UTF-8 so Catppuccin glyphs (↻ ✎ ★ ⚠) print
under the Windows cp1252 console default.

Usage::

    from tests.fixtures.qt_app import get_qt_app

    app = get_qt_app()
"""

import os
import sys


def get_qt_app():
    """Idempotent: returns a singleton QApplication. Configures
    environment + stdout on first call."""
    os.environ.setdefault("U2O_SKIP_CLOSE_PROMPT", "1")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # cp1252 → UTF-8 for unicode glyph printing in test output.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv if sys.argv else ["test"])
    return app
