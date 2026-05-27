"""Unit tests for ``project_manager.detect_externally_modified``.

Compares `output_files[i].mtime` against the entry's `last_emitted`
to detect in-engine edits between emissions. F-9.I.6b verification."""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from project_manager import detect_externally_modified, _utc_now_iso


def test_empty_state_index_returns_empty_buckets():
    out = detect_externally_modified({})
    for bucket in ("materials", "meshes", "textures", "prefabs"):
        assert out[bucket] == set()
    out = detect_externally_modified(None)
    assert out["materials"] == set()


def test_clean_entries_not_flagged():
    """File mtime predates last_emitted → not externally modified."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "a.material"
        f.write_text("{}", encoding="utf-8")
        past = time.time() - 5
        os.utime(f, (past, past))
        state = {
            "materials": {
                "guid-a": {"output_files": [str(f)],
                            "last_emitted": _utc_now_iso()},
            },
        }
        out = detect_externally_modified(state)
        assert out["materials"] == set()


def test_externally_modified_file_is_flagged():
    """File mtime newer than last_emitted + tolerance → flagged."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "b.material"
        f.write_text("{}", encoding="utf-8")
        future = time.time() + 10
        os.utime(f, (future, future))
        state = {
            "materials": {
                "guid-b": {"output_files": [str(f)],
                            "last_emitted": _utc_now_iso()},
            },
        }
        out = detect_externally_modified(state)
        assert out["materials"] == {"guid-b"}


def test_missing_file_not_flagged_as_external_mod():
    """Output file missing entirely is a DIRTY case, not external-mod.
    The detector silently skips entries with no stat-able file."""
    state = {
        "materials": {
            "guid-x": {"output_files": ["/this/does/not/exist.material"],
                        "last_emitted": _utc_now_iso()},
        },
    }
    out = detect_externally_modified(state)
    assert out["materials"] == set()


def test_no_last_emitted_skipped():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "c.material"
        f.write_text("{}", encoding="utf-8")
        future = time.time() + 10
        os.utime(f, (future, future))
        state = {
            "materials": {
                "guid-c": {"output_files": [str(f)]},  # no last_emitted
            },
        }
        out = detect_externally_modified(state)
        assert out["materials"] == set()


def test_tolerance_absorbs_fs_rounding():
    """File mtime within 1s of last_emitted shouldn't trip the
    detector (FS subsecond rounding + write-then-record gap).

    Uses a FIXED past epoch (not wall-clock now) so the test isn't
    sensitive to wall-clock vs ISO-string drift —
    ``_utc_now_iso`` truncates to whole seconds, which would
    otherwise add up to ~1s of additional offset and trip a 0.5s
    "within tolerance" check at the boundary."""
    import datetime
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "d.material"
        f.write_text("{}", encoding="utf-8")
        target_epoch = 1700000000.0   # Tue Nov 14 2023 22:13:20 UTC
        emitted_iso = datetime.datetime.fromtimestamp(
            target_epoch, datetime.timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # mtime 0.5s past the recorded last_emitted — well within the
        # detector's 1.0s tolerance.
        os.utime(f, (target_epoch + 0.5, target_epoch + 0.5))
        state = {
            "materials": {
                "guid-d": {"output_files": [str(f)],
                            "last_emitted": emitted_iso},
            },
        }
        out = detect_externally_modified(state)
        assert out["materials"] == set(), \
            f"0.5s past should be within 1.0s tolerance: {out}"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
