"""
=============================================================================
COMPONENT PROCESSOR AUTO-DISCOVERY

Scans this package directory for ComponentProcessor subclasses, sorts them
by WEIGHT (ascending, stable — file discovery order wins on ties), and
returns an ordered list of instantiated processors ready for use.

Usage:
    from platforms.unity.components import load_component_processors, build_dispatch_table

    processors    = load_component_processors(log_fn)
    dispatch      = build_dispatch_table(processors)
=============================================================================
"""

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .base import ComponentProcessor


# =============================================================================
# LOADER
# =============================================================================

def load_component_processors(
        log: Optional[Callable[[str], None]] = None
) -> List[ComponentProcessor]:
    """
    Discover and instantiate all ComponentProcessor subclasses found in this
    package directory.  Returns a list sorted by WEIGHT ascending.
    Equal-weight processors preserve file discovery order (stable sort).
    """
    processors: List[ComponentProcessor] = []
    pkg_dir = Path(__file__).parent

    log and log("[Registry] Scanning components/ for processors...")

    for _, module_name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if module_name == 'base':
            continue

        try:
            module = importlib.import_module(f'.{module_name}', package=__package__)
        except Exception as exc:
            log and log(f"  [Registry] ✗ Failed to import '{module_name}': {exc}")
            continue

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, ComponentProcessor)
                    and obj is not ComponentProcessor
                    and obj.__module__ == module.__name__):
                instance = obj()
                processors.append(instance)
                log and log(
                    f"  [Registry] ✓ {name:<32} "
                    f"weight={instance.WEIGHT:<6} "
                    f"handles={instance.HANDLES}"
                )

    # Stable sort — equal weights keep discovery order (first-come, first-served)
    processors.sort(key=lambda p: p.WEIGHT)

    log and log(f"[Registry] {len(processors)} processor(s) loaded.\n")
    return processors


# =============================================================================
# DISPATCH TABLE
# =============================================================================

def build_dispatch_table(
        processors: List[ComponentProcessor]
) -> Dict[str, ComponentProcessor]:
    """
    Build {unity_type_name: processor} lookup from a loaded processor list.
    Later entries in the list win on duplicate HANDLES entries (last write wins).
    """
    table: Dict[str, ComponentProcessor] = {}
    for proc in processors:
        for unity_type in proc.HANDLES:
            table[unity_type] = proc
    return table
