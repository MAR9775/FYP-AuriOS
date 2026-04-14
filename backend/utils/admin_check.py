"""Admin / elevation helpers.

These are Windows concepts — on non-Windows hosts (e.g. the Linux Docker
backend container) they are no-ops so the install flow is not blocked.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

from backend.utils.platform_utils import is_windows


def is_admin() -> bool:
    """Return True if the current process has administrator privileges.

    On non-Windows hosts this returns True because the concept does not
    apply and we don't want the install flow gated behind it.
    """
    if not is_windows():
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Relaunch the current Python script with admin privileges via UAC.

    No-op on non-Windows hosts.
    """
    if not is_windows():
        return
    script = sys.argv[0]
    params = " ".join(sys.argv[1:])
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', None, 1
    )
    if ret <= 32:
        raise PermissionError("User declined UAC prompt or elevation failed.")


def run_as_admin(executable: str, args: str = "") -> subprocess.CompletedProcess:
    """Run a specific executable with admin privileges via ShellExecute.

    No-op on non-Windows hosts.
    """
    if not is_windows():
        return None  # type: ignore[return-value]
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", executable, args, None, 1
    )
    if ret <= 32:
        raise PermissionError(f"Failed to run {executable} as admin. Code: {ret}")
    return ret
