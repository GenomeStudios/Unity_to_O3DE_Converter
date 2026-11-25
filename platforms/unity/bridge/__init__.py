"""
=============================================================================
UNITY BRIDGE PACKAGE
=============================================================================

Headless Unity runs for the Unity source platform. See ``unity_bridge`` for
the truth dump and ``README.md`` for what the bridge needs on the machine.
"""

from platforms.unity.bridge.unity_bridge import (   # noqa: F401
    BRIDGE_VERSION,
    TruthRequest,
    TruthResult,
    check_requirements,
    find_unity_editor,
    find_unity_project_root,
    fingerprint,
    install_bridge,
    project_is_open,
    read_editor_version,
    run_truth_dump,
)
