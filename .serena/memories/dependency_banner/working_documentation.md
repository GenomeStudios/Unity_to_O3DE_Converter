---
name: dependency-banner-working-doc
description: Living status log for F-1 (dependency banner). Newest entries on top.
metadata:
  type: project
---

# F-1 Dependency Banner — Working Documentation

Newest entries on top. Linked plan: [[dependency-banner-plan]].

## 2026-05-26 — F-1 shipped ✓

### What landed
- **`check_dependencies()`** module-level function in `main_app.py`.
  Returns list of dicts: `{import_name, pypi_name, role, is_hard,
  installed, version}`. Calls `importlib.invalidate_caches()` first so
  packages installed mid-session can be detected on a probe. Shared by
  ConfigTab and the banner.
- **`signature_for(missing)`** — comma-joined sorted pypi_names. Stable
  key for dismiss persistence.
- **`ConfigTab._refresh_dep_status`** refactored to consume
  `check_dependencies()`; no behaviour change, ~30% less code.
- **`get_dismissed_dependency_signature()` /
  `set_dismissed_dependency_signature(sig|None)`** added to
  `project_manager.py`. Stored under `dependencies.dismissed_signature`
  in the global settings file. Setting to None removes the key (and the
  `dependencies` section if empty) so re-reads return None cleanly.
  Project manager smoke test grew assertion #9 and still passes.
- **`DismissibleBanner(QFrame)`** widget in `main_app.py`. Hidden by
  default. Two severity styles via objectName (`dep_banner_warn`,
  `dep_banner_error`). Three children: ⚠ icon + message + action button
  ("Open Config →") + small "Dismiss" button. Emits
  `open_config_clicked` and `dismissed` signals.
- **QSS rules** added to `THEME_QSS` for both banner severities and the
  action/dismiss buttons. Catppuccin palette: yellow `#f9e2af` with dark
  yellow-tinted background `#2b2718`, red `#f38ba8` with dark red-tinted
  background `#2b1a1d`.
- **`MainWindow`** reshaped:
  - Central widget is now a QWidget with a 0-margin/0-spacing VBox:
    [DismissibleBanner, QTabWidget].
  - `_evaluate_dep_banner()` runs once at end of `__init__`. Walks
    `check_dependencies()`, computes signature, compares against the
    persisted dismissed signature. If missing AND signature mismatch,
    shows the banner with the appropriate severity.
  - `_on_banner_dismissed()` writes the current missing-set signature
    to settings and hides the banner.
  - `_goto_config()` switches to the Config tab (used by the banner's
    Open Config button).

### Sanity gates passed
- `py project_manager.py` → smoke OK (9 invariants; new dismiss
  round-trip included).
- Programmatic banner verification:
  - [1] all installed → banner hidden ✓
  - [2] optional missing → banner shown, objectName `dep_banner_warn` ✓
  - [3] required missing → banner shown, objectName `dep_banner_error` ✓
  - [4] dismiss → banner hidden, signature persisted ✓
  - [5] same missing set re-evaluated → stays hidden ✓
  - [6] missing set changed (PyYAML→PyYAML+Pillow) → banner re-armed ✓
  - [7] cleanup left no orphan state ✓

### T-series status
- **T-1** (all deps installed → no banner) — ✓ programmatic.
- **T-2** (optional missing → yellow banner) — ✓ programmatic.
- **T-3** (dismiss persists across relaunch) — needs user verification
  with a real relaunch to confirm the global file is on the expected
  disk path. Programmatic side passes.
- **T-4** (missing set change re-arms) — ✓ programmatic.
- **T-5** (Open Config jumps tab) — `_goto_config` setCurrentIndex is
  trivial; visual verification on user run.

### How to simulate a missing dep without uninstalling
For visual QA the user can:

```powershell
# Temporarily move Pillow out of sys.path
py -c "import PIL; print(PIL.__path__[0])"
# Rename the printed folder to add a .disabled suffix, launch the app,
# verify the yellow banner appears, then rename it back.
```

Or, easier, just `pip uninstall Pillow -y` and re-install after.

### Behaviour notes / known quirks
- Banner state is captured **once** at launch. If the user installs a
  missing dep then hits ConfigTab Refresh, the banner does NOT update
  mid-session. This is by design (see plan Q5). A future polish would
  call `MainWindow._evaluate_dep_banner()` from the Config tab's refresh
  callback.
- Dismiss signature uses the missing-deps set, not the all-deps set.
  Installing Pillow after dismissing-with-Pillow-missing → banner stays
  hidden on next launch because the new set is empty (handled by the
  `not missing` early return in `_evaluate_dep_banner`).
- `_on_banner_dismissed` runs `check_dependencies()` again at dismiss
  time rather than reusing the launch-time result. This is the right
  behaviour if a missing dep was installed mid-session (the dismiss
  records the *current* state, not the stale state).

## 2026-05-26 — Plan locked; starting I.1

Plan landed with all 5 design Q's resolved. About to extract
`check_dependencies()` + `signature_for()` from ConfigTab so both the
Config refresh and the banner consume the same status snapshot.

## Pending / not yet shipped

- User-driven T-3 verification (relaunch cycle).
- Optional future polish: mid-session refresh from ConfigTab → banner.
- Optional future polish: install-in-place button inside Config tab
  (separate piece of work, deliberately out of scope per plan).
