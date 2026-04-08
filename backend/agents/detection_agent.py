"""DetectionAgent — checks which software is installed on the Windows host."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from typing import Any, Dict

from backend.agents.base_agent import BaseAgent

# Commands used to probe each tool.  A zero exit-code means installed.
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

# Postman is detected by its executable path rather than a CLI command.
_POSTMAN_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Programs", "Postman", "Postman.exe",
)


def _probe(cmd: list[str]) -> bool:
    """Return True if *cmd* exits with code 0 (tool is on PATH)."""
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
            "Scanning PATH for CLI tools and checking Postman.exe path. "
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

        # Postman — file-system check
        installed["postman"] = os.path.isfile(_POSTMAN_PATH)
        self.logger.debug("  %-12s → %s", "postman", installed["postman"])

        # Admin check
        try:
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_admin = False

        # Free disk on C:
        try:
            free_disk_gb = shutil.disk_usage("C:/").free / (1024 ** 3)
        except Exception:
            free_disk_gb = 0.0

        return {
            "installed": installed,
            "is_admin": is_admin,
            "free_disk_gb": round(free_disk_gb, 2),
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
