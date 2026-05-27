---
name: dependency-banner-plan
description: Design + locked decisions for F-1 — startup banner that warns the user when converter dependencies are missing, links to Config, and supports persistent dismissal keyed by the missing-deps signature.
metadata:
  type: project
---

# F-1 Dependency Banner — Plan

## Goal

On app launch, check the converter's dependency list (per `DEPENDENCIES`
in `main_app.py`). If any are missing, show a banner across the top of
the main window with:

- A descriptive message that names what's missing and severity.
- An **Open Config** action that jumps to the Config tab.
- A **Dismiss** action that hides the banner for the current launch
  AND persists the dismissal — the banner won't reappear on subsequent
  launches *unless the missing-deps set changes*.

Goal is to make missing-dep failure modes loud instead of buried.

## Resolved Decisions (Q&A history)

**Q1 — Where does the banner sit?**
A: **Above the QTabWidget**, inside `MainWindow`'s central layout. Visible
regardless of which tab is active. (Considered: Project tab only —
rejected because the banner needs to nag from the moment the app opens,
not only when the user happens to be on Project.)

**Q2 — Is dismiss scoped per-installation or per-project?**
A: **Per-installation**, persisted to the global `converter_settings.json`.
Dependencies are tool-level concerns, not project-level. Reusing the
file already managed by ProjectManager keeps configuration in one place.

**Q3 — How is the dismissal keyed?**
A: **By a stable signature of the missing-deps set**. Signature is the
sorted comma-joined list of missing pypi_names. Examples:
- Nothing missing → no banner, no signature stored.
- `Pillow` missing → signature `"Pillow"` → dismissed.
- Later `PyYAML` also goes missing → signature `"Pillow,PyYAML"` →
  doesn't match the previously dismissed `"Pillow"` → banner re-arms.

This means: if the user installs Pillow but loses PyYAML, the banner
reappears with the new context (correct behaviour — they probably want
to know).

**Q4 — Severity levels?**
A: **Two-tier**, driven by `is_hard` in the `DEPENDENCIES` list:
- Any missing `is_hard=True` → **error** style (red banner, "Critical:
  converter cannot run — install required dependencies.")
- Only `is_hard=False` missing → **warning** style (yellow banner,
  "Optional dependencies missing — some features unavailable.")

**Q5 — Re-check trigger?**
A: **Launch only.** Once the banner state is computed at startup, it
sticks for the session. User can re-probe via the Config tab's existing
Refresh button. If a Refresh discovers the missing set has changed, the
banner does NOT update mid-session — by design, to keep banner state
predictable. Banner update on user-driven refresh is a future polish if
it ends up being missed.

## Design

### Dependency-status API (`main_app.py` extraction)

Existing helpers `_probe_dependency` and `DEPENDENCIES` stay in
`main_app.py`. Add one new module-level function:

```python
def check_dependencies() -> list[dict]:
    """Return [{import_name, pypi_name, role, is_hard, installed, version}, …].
    Drives both the Config-tab refresh and the startup banner."""
```

`ConfigTab._refresh_dep_status` refactors to consume this list rather
than re-implementing the probe loop. Banner consumes the filtered
`[r for r in check_dependencies() if not r["installed"]]`.

### Dismissal persistence

Stored in `converter_settings.json` under a new top-level section:

```json
{
  "dependencies": {
    "dismissed_signature": "Pillow"
  },
  …
}
```

Read/write helpers go in `project_manager.py` (it already owns the
global settings file):

```python
def get_dismissed_dependency_signature() -> str | None: ...
def set_dismissed_dependency_signature(signature: str | None) -> None: ...
```

`signature_for(missing: list[dict]) -> str` lives in `main_app.py`
next to `check_dependencies()`:

```python
def signature_for(missing: list[dict]) -> str:
    return ",".join(sorted(m["pypi_name"] for m in missing))
```

### DismissibleBanner widget

```python
class DismissibleBanner(QFrame):
    """A coloured banner with: icon-label + message + secondary action +
    Dismiss. Hidden by default. Emit `open_config_clicked` so MainWindow
    can route the secondary action."""

    dismissed         = Signal()
    open_config_clicked = Signal()

    def show_state(self, severity: str, message: str) -> None: ...
    def clear(self) -> None: ...
```

Styling:
- `severity="error"` → red background + red border, secondary action
  reads "Open Config →"
- `severity="warning"` → yellow background + yellow border, same action
- Banner uses QSS via `setObjectName("dep_banner_error" | "dep_banner_warn")`
  with rules added to `THEME_QSS`. Catppuccin Mocha palette:
  red `#f38ba8`, yellow `#f9e2af`, base `#11111b`.

### MainWindow wiring

```python
# In MainWindow.__init__:
central = QWidget()
v = QVBoxLayout(central)
v.setContentsMargins(0, 0, 0, 0)
v.setSpacing(0)
self._banner = DismissibleBanner()
self._banner.open_config_clicked.connect(self._goto_config)
self._banner.dismissed.connect(self._on_banner_dismissed)
v.addWidget(self._banner)
v.addWidget(self._tabs, 1)
self.setCentralWidget(central)

self._evaluate_dep_banner()
```

`_evaluate_dep_banner` runs `check_dependencies()`, computes signature,
compares against the persisted dismissed signature, sets banner state.

## Implementation Plan

### I.1 — `check_dependencies()` extraction
**Done when:**
- `check_dependencies()` and `signature_for()` exist at module scope
  in `main_app.py`.
- `ConfigTab._refresh_dep_status` is refactored to consume
  `check_dependencies()` (same end-state, less duplication).
- `py -c "import main_app; print(len(main_app.check_dependencies()))"` prints `3`.

### I.2 — Dismiss persistence helpers
**Done when:**
- `get_dismissed_dependency_signature` and
  `set_dismissed_dependency_signature` exist in `project_manager.py`.
- Round-trip: setting a signature and re-reading it returns the same
  string; setting None clears the key from the global file.
- Project manager smoke test grows two assertions and still passes.

### I.3 — `DismissibleBanner` widget
**Done when:**
- Class lives in `main_app.py`, hidden by default.
- `show_state(severity, message)` updates colour + text + emits visible.
- Dismiss button emits `dismissed`. Open-config button emits
  `open_config_clicked`.
- QSS rules added to `THEME_QSS` for `dep_banner_error` and
  `dep_banner_warn`.

### I.4 — MainWindow wiring + evaluation
**Done when:**
- Central widget reshaped from "QTabWidget alone" to "VBox of banner +
  QTabWidget".
- `_evaluate_dep_banner` runs once at end of `__init__`, computes
  signature, compares against dismissed signature, shows or hides.
- `_goto_config` switches to the Config tab (programmatically clicks the
  corner button so the visual state stays consistent).
- `_on_banner_dismissed` writes signature, hides banner.

### I.5 — User verification (T-series)

| ID | Proof |
|---|---|
| T-1 | All deps installed → app launches, no banner |
| T-2 | Simulate missing optional (rename PIL site-packages or pip uninstall Pillow) → banner shows yellow, names Pillow, action buttons present |
| T-3 | Click Dismiss → banner hides; relaunch → still hidden; `converter_settings.json` shows `dependencies.dismissed_signature` |
| T-4 | After dismiss, simulate PyYAML ALSO missing → relaunch → banner re-arms with new severity (red, since PyYAML is `is_hard=True`) |
| T-5 | Click Open Config → tab switches to Config, corner button highlights |

T-1, T-2, T-3, T-5 are quick PySide6 GUI proofs. T-4 needs the user to
uninstall PyYAML briefly — describe the rollback in the working doc so
they can reverse it cleanly.

## Out of scope (deliberately)

- **Mid-session re-evaluation.** Banner state is captured at launch
  only.
- **Install-in-place button.** "Open Config" jumps to the Config tab
  which has the existing install command — clicking pip install from
  inside the app is a separate piece of work.
- **Multiple banner stacking.** v1 banner shows one message per launch.
  If future features need their own banners, generalise the widget then.
- **Per-project dismissal.** Always global.
