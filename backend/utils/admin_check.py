import ctypes
import sys
import subprocess
import os

def is_admin() -> bool:
    """Check if current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def relaunch_as_admin():
    """Relaunch the current Python script with admin privileges via UAC."""
    script = sys.argv[0]
    params = " ".join(sys.argv[1:])
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', None, 1
    )
    if ret <= 32:
        raise PermissionError("User declined UAC prompt or elevation failed.")

def run_as_admin(executable: str, args: str = "") -> subprocess.CompletedProcess:
    """Run a specific executable with admin privileges using ShellExecute."""
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", executable, args, None, 1
    )
    if ret <= 32:
        raise PermissionError(f"Failed to run {executable} as admin. Code: {ret}")
    return ret
