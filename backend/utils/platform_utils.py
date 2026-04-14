"""Platform helpers — single source of truth for install-flow platform guards."""

from __future__ import annotations

import os
import platform


def is_windows() -> bool:
    """Return True if running on a Windows host."""
    return platform.system() == "Windows"


def is_simulated_host() -> bool:
    """Return True when install agents should run in simulation mode.

    On non-Windows hosts (e.g. the Linux Docker backend container) the Windows
    installers and registry tweaks cannot run, so we simulate each stage so the
    orchestrator, WebSocket, and progress panel still flow end-to-end.

    Set ``AURIOS_SIMULATE_INSTALL=1`` to force simulation during native testing.
    """
    if os.getenv("AURIOS_SIMULATE_INSTALL") == "1":
        return True
    return not is_windows()


def free_disk_gb() -> float:
    """Return free disk space in GB for the install target path, cross-platform."""
    import shutil

    path = "C:/" if is_windows() else "/"
    try:
        return round(shutil.disk_usage(path).free / (1024 ** 3), 1)
    except Exception:
        return 0.0
