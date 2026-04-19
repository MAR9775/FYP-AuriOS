"""DetectionAgent — checks which software is installed on the host.

Cross-platform: probes are done via ``shutil.which`` followed by a version
call. Admin status and free disk come from ``backend.utils`` helpers so the
same code works on Windows (real install target) and Linux (Docker demo).
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from typing import Any, Dict, List

from backend.agents.base_agent import BaseAgent
from backend.utils.admin_check import is_admin as _platform_is_admin
from backend.utils.platform_utils import free_disk_gb as _platform_free_disk_gb
from backend.utils.platform_utils import is_windows

# Commands used to probe each tool. A zero exit-code means installed.
_PROBE_COMMANDS: Dict[str, list[str]] = {
    "python":     ["python", "--version"],
    "nodejs":     ["node", "--version"],
    "git":        ["git", "--version"],
    "vscode":     ["code", "--version"],
    "docker":     ["docker", "--version"],
    "java":       ["java", "-version"],
    "mysql":      ["mysql", "--version"],
    "postgresql": ["psql", "--version"],
    "mongodb":    ["mongod", "--version"],
    "redis":      ["redis-server", "--version"],
}

# Postman on Windows lives under %LOCALAPPDATA%\Programs\Postman\Postman.exe.
# On non-Windows hosts we fall back to ``shutil.which("postman")``.
_POSTMAN_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Programs", "Postman", "Postman.exe",
)

_LOCAL = os.environ.get("LOCALAPPDATA", "")
_PROG  = r"C:\Program Files"
_PROG86 = r"C:\Program Files (x86)"
_HOME  = os.path.expanduser("~")

# Known file-system paths for GUI apps that have no CLI command on PATH.
# Each slug maps to a list of candidate paths (first match wins).
_WIN_PATHS: Dict[str, List[str]] = {
    "vlc": [
        os.path.join(_PROG,   "VideoLAN", "VLC", "vlc.exe"),
        os.path.join(_PROG86, "VideoLAN", "VLC", "vlc.exe"),
    ],
    "rufus": [
        os.path.join(_PROG,   "Rufus", "rufus.exe"),
        os.path.join(_PROG86, "Rufus", "rufus.exe"),
        os.path.join(_LOCAL,  "Programs", "Rufus", "rufus.exe"),
        # Portable rufus paths resolved lazily in _check_paths()
    ],
    "7zip": [
        os.path.join(_PROG,   "7-Zip", "7z.exe"),
        os.path.join(_PROG86, "7-Zip", "7z.exe"),
    ],
    "notepadpp": [
        os.path.join(_PROG,   "Notepad++", "notepad++.exe"),
        os.path.join(_PROG86, "Notepad++", "notepad++.exe"),
    ],
}

# Registry display-name substrings for each slug (case-insensitive match).
_REGISTRY_NAMES: Dict[str, str] = {
    "rufus":     "rufus",
    "vlc":       "vlc media player",
    "7zip":      "7-zip",
    "notepadpp": "notepad++",
    "docker":    "docker desktop",
    "postman":   "postman",
}


def _probe(cmd: list[str]) -> bool:
    """Return True if *cmd* exits with code 0 (tool is on PATH)."""
    if shutil.which(cmd[0]) is None:
        return False
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _check_paths(slug: str) -> bool:
    """Return True if any known install path for *slug* exists on disk."""
    candidates = list(_WIN_PATHS.get(slug, []))
    # Rufus is often a portable exe — resolve globs at call-time
    if slug == "rufus":
        candidates += glob.glob(os.path.join(_HOME, "Downloads", "rufus*.exe"))
        candidates += glob.glob(os.path.join(_HOME, "Desktop",   "rufus*.exe"))
    for path in candidates:
        if path and os.path.isfile(path):
            return True
    return False


def _check_registry(slug: str) -> bool:
    """Return True if a registry uninstall entry matches *slug*."""
    if not is_windows():
        return False
    pattern = _REGISTRY_NAMES.get(slug)
    if not pattern:
        return False
    try:
        import winreg
        import re as _re
        rx = _re.compile(pattern, _re.IGNORECASE)
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for path in (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            ):
                try:
                    with winreg.OpenKey(root, path) as key:
                        count = winreg.QueryInfoKey(key)[0]
                        for i in range(count):
                            try:
                                sub = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, sub) as sk:
                                    try:
                                        name = winreg.QueryValueEx(sk, "DisplayName")[0]
                                        if rx.search(str(name)):
                                            return True
                                    except FileNotFoundError:
                                        pass
                            except OSError:
                                pass
                except OSError:
                    pass
    except ImportError:
        pass
    return False


def _is_installed_gui(slug: str) -> bool:
    """Combined path + registry check for GUI-only apps."""
    return _check_paths(slug) or _check_registry(slug)


class DetectionAgent(BaseAgent):
    """Detect installed development tools and gather basic system info."""

    # ------------------------------------------------------------------
    # ReAct overrides
    # ------------------------------------------------------------------

    def reason(self, context: Dict[str, Any]) -> str:
        thought = (
            "Scanning PATH for CLI tools, checking known GUI app paths, "
            "and querying the Windows registry. "
            "Will also query admin status and free disk space."
        )
        self.logger.debug("[REASON] %s", thought)
        return thought

    def act(self, action: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info("[ACT] DetectionAgent probing installed software…")

        installed: Dict[str, bool] = {}
        for name, cmd in _PROBE_COMMANDS.items():
            result = _probe(cmd)
            installed[name] = result
            self.logger.debug("  %-12s → %s", name, result)

        # python3 also counts as python on Linux
        if not installed["python"] and shutil.which("python3") is not None:
            installed["python"] = True

        # Postman — file-system check on Windows, PATH lookup elsewhere
        if is_windows():
            installed["postman"] = os.path.isfile(_POSTMAN_PATH) or _check_registry("postman")
        else:
            installed["postman"] = shutil.which("postman") is not None
        self.logger.debug("  %-12s → %s", "postman", installed["postman"])

        # GUI-only apps: check known install paths + Windows registry
        for slug in ("rufus", "vlc", "7zip", "notepadpp"):
            installed[slug] = _is_installed_gui(slug)
            self.logger.debug("  %-12s → %s", slug, installed[slug])

        return {
            "installed": installed,
            "is_admin": _platform_is_admin(),
            "free_disk_gb": _platform_free_disk_gb(),
        }

    def observe(self, result: Dict[str, Any]) -> Dict[str, Any]:
        installed = result.get("installed", {})
        found = [k for k, v in installed.items() if v]
        missing = [k for k, v in installed.items() if not v]
        self.logger.info(
            "[OBSERVE] found=%s  missing=%s  is_admin=%s  free_disk_gb=%.1f",
            found, missing, result.get("is_admin"), result.get("free_disk_gb"),
        )
        return result

    # ------------------------------------------------------------------
    # Convenience entry point (returns flat dict for easy testing)
    # ------------------------------------------------------------------

    def run(self, task: Dict[str, Any] = None) -> Dict[str, Any]:  # type: ignore[override]
        if task is None:
            task = {}
        self.reason(task)
        raw = self.act({"task": task})
        return self.observe(raw)
