"""ConfigureAgent — adds Python to PATH and installs pip packages."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, List

from backend.agents.base_agent import BaseAgent

_DEFAULT_PIP_PACKAGES: List[str] = []


class ConfigureAgent(BaseAgent):
    """Post-install configuration: PATH registration and pip installs."""

    # ------------------------------------------------------------------
    # ReAct overrides
    # ------------------------------------------------------------------

    def reason(self, context: Dict[str, Any]) -> str:
        packages = context.get("pip_packages", _DEFAULT_PIP_PACKAGES)
        thought = (
            f"Will add Python to Windows PATH via winreg "
            f"and install pip packages: {packages}."
        )
        self.logger.debug("[REASON] %s", thought)
        return thought

    def act(self, action: Dict[str, Any]) -> Dict[str, Any]:
        task = action.get("task", {})
        pip_packages: List[str] = task.get("pip_packages", _DEFAULT_PIP_PACKAGES)

        results: Dict[str, Any] = {
            "path_updated": False,
            "path_error": None,
            "pip_results": {},
        }

        # --- 1. Add Python to Windows PATH via winreg ---
        results["path_updated"], results["path_error"] = self._add_python_to_path()

        # --- 2. Install pip packages ---
        for package in pip_packages:
            ok, err = self._pip_install(package)
            results["pip_results"][package] = {"success": ok, "error": err}

        return results

    def observe(self, result: Dict[str, Any]) -> Dict[str, Any]:
        pip = result.get("pip_results", {})
        ok_pkgs = [k for k, v in pip.items() if v.get("success")]
        fail_pkgs = [k for k, v in pip.items() if not v.get("success")]
        self.logger.info(
            "[OBSERVE] path_updated=%s  pip_ok=%s  pip_fail=%s",
            result.get("path_updated"), ok_pkgs, fail_pkgs,
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_python_to_path(self) -> tuple[bool, str | None]:
        """Append Python's Scripts directory to the user PATH in the registry."""
        try:
            import winreg  # noqa: PLC0415  (Windows-only)

            python_exe = sys.executable  # e.g. C:\Python311\python.exe
            scripts_dir = str(
                __import__("pathlib").Path(python_exe).parent / "Scripts"
            )
            python_dir = str(__import__("pathlib").Path(python_exe).parent)

            key_path = r"Environment"
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
            ) as key:
                try:
                    current_path, _ = winreg.QueryValueEx(key, "PATH")
                except FileNotFoundError:
                    current_path = ""

                entries = [e for e in current_path.split(";") if e]
                new_entries = [d for d in (python_dir, scripts_dir) if d not in entries]

                if new_entries:
                    new_path = ";".join(entries + new_entries)
                    winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
                    self.logger.info("[ACT] Added to PATH: %s", new_entries)
                else:
                    self.logger.info("[ACT] Python already in PATH, no change needed.")

            return True, None
        except ImportError:
            self.logger.warning("[ACT] winreg not available (non-Windows host), skipping PATH update.")
            return False, "winreg unavailable"
        except Exception as exc:
            self.logger.error("[ACT] PATH update failed: %s", exc)
            return False, str(exc)

    def _pip_install(self, package: str) -> tuple[bool, str | None]:
        """Run `python -m pip install <package>`."""
        cmd = [sys.executable, "-m", "pip", "install", package]
        self.logger.info("[ACT] pip install %s", package)
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
            )
            if proc.returncode == 0:
                return True, None
            stderr = proc.stderr.decode(errors="replace").strip()
            return False, stderr
        except subprocess.TimeoutExpired:
            return False, "pip install timed out"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Convenience entry point
    # ------------------------------------------------------------------

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        self.reason(task)
        raw = self.act({"task": task})
        return self.observe(raw)
