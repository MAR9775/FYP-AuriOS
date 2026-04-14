"""DetectionAgent — checks which software is installed on the host.

Cross-platform: probes are done via ``shutil.which`` followed by a version
call. Admin status and free disk come from ``backend.utils`` helpers so the
same code works on Windows (real install target) and Linux (Docker demo).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict

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


class DetectionAgent(BaseAgent):
    """Detect installed development tools and gather basic system info."""

    # ------------------------------------------------------------------
    # ReAct overrides
    # ------------------------------------------------------------------

    def reason(self, context: Dict[str, Any]) -> str:
        thought = (
            "Scanning PATH for CLI tools and checking Postman. "
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
            installed["postman"] = os.path.isfile(_POSTMAN_PATH)
        else:
            installed["postman"] = shutil.which("postman") is not None
        self.logger.debug("  %-12s → %s", "postman", installed["postman"])

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
