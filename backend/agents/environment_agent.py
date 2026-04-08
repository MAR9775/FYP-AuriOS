"""EnvironmentAgent — creates a Python venv and project structure."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from backend.agents.base_agent import BaseAgent

_DEFAULT_PROJECT_ROOT = Path.home() / "AuriOS_Projects" / "my_project"

_PROJECT_SUBDIRS: List[str] = [
    "src",
    "tests",
    "data",
    "notebooks",
    "docs",
]


class EnvironmentAgent(BaseAgent):
    """Set up a development environment: venv + folder structure."""

    # ------------------------------------------------------------------
    # ReAct overrides
    # ------------------------------------------------------------------

    def reason(self, context: Dict[str, Any]) -> str:
        project_path = context.get("project_path", str(_DEFAULT_PROJECT_ROOT))
        thought = (
            f"Will create Python venv at '{project_path}/project_env', "
            f"scaffold subdirs {_PROJECT_SUBDIRS}."
        )
        self.logger.debug("[REASON] %s", thought)
        return thought

    def act(self, action: Dict[str, Any]) -> Dict[str, Any]:
        task = action.get("task", {})
        project_root = Path(task.get("project_path", str(_DEFAULT_PROJECT_ROOT)))

        results: Dict[str, Any] = {
            "project_root": str(project_root),
            "venv_created": False,
            "venv_error": None,
            "dirs_created": [],
        }

        # --- 1. Create project folder and subdirectories ---
        for subdir in [""] + _PROJECT_SUBDIRS:
            target = project_root / subdir if subdir else project_root
            try:
                target.mkdir(parents=True, exist_ok=True)
                if subdir:
                    results["dirs_created"].append(str(target))
                    self.logger.debug("[ACT] Created directory: %s", target)
            except Exception as exc:
                self.logger.warning("[ACT] Could not create %s: %s", target, exc)

        # --- 2. Create Python virtual environment ---
        venv_path = project_root / "project_env"
        self.logger.info("[ACT] Creating venv at %s", venv_path)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            if proc.returncode == 0:
                results["venv_created"] = True
                self.logger.info("[ACT] venv created successfully.")
            else:
                err = proc.stderr.decode(errors="replace").strip()
                results["venv_error"] = err
                self.logger.error("[ACT] venv creation failed: %s", err)
        except Exception as exc:
            results["venv_error"] = str(exc)
            self.logger.error("[ACT] venv creation exception: %s", exc)

        return results

    def observe(self, result: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info(
            "[OBSERVE] project=%s  venv=%s",
            result.get("project_root"),
            result.get("venv_created"),
        )
        return result

    # ------------------------------------------------------------------
    # Convenience entry point
    # ------------------------------------------------------------------

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        self.reason(task)
        raw = self.act({"task": task})
        return self.observe(raw)
