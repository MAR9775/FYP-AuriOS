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

        software_list: List[str] = task.get("software_list", [])

        results: Dict[str, Any] = {
            "path_updated": False,
            "path_error": None,
            "pip_results": {},
        }

        # --- 1. Add tools to Windows PATH via winreg ---
        results["path_updated"], results["path_error"] = self._update_system_path(software_list)

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

    def _update_system_path(self, software_list: List[str]) -> tuple[bool, str | None]:
        """Append installed software directories to the user PATH in the registry."""
        try:
            import winreg  # noqa: PLC0415  (Windows-only)
            import os

            local_app_data = os.environ.get("LOCALAPPDATA", "")
            prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
            
            dirs_to_add = []

            # Python
            if "python" in software_list or not software_list:
                # Even if python isn't explicitly in software_list, we might want to add it,
                # but let's stick to adding it if requested.
                python_exe = sys.executable
                python_dir = str(__import__("pathlib").Path(python_exe).parent)
                scripts_dir = str(__import__("pathlib").Path(python_exe).parent / "Scripts")
                dirs_to_add.extend([python_dir, scripts_dir])

            # VS Code
            if "vscode" in software_list:
                dirs_to_add.append(os.path.join(local_app_data, "Programs", "Microsoft VS Code", "bin"))

            # Node.js
            if "nodejs" in software_list:
                dirs_to_add.append(os.path.join(prog_files, "nodejs"))

            # Git
            if "git" in software_list:
                dirs_to_add.append(os.path.join(prog_files, "Git", "cmd"))

            # Docker
            if "docker" in software_list:
                dirs_to_add.append(os.path.join(prog_files, "Docker", "Docker", "resources", "bin"))

            # Filter to directories that actually exist on disk right now
            valid_dirs = [d for d in dirs_to_add if os.path.isdir(d)]

            if not valid_dirs:
                return True, None

            key_path = r"Environment"
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
            ) as key:
                try:
                    current_path, _ = winreg.QueryValueEx(key, "PATH")
                except FileNotFoundError:
                    current_path = ""

                entries = [e.strip() for e in current_path.split(";") if e.strip()]
                lower_entries = [e.lower() for e in entries]
                
                new_entries = []
                for d in valid_dirs:
                    if d.lower() not in lower_entries:
                        new_entries.append(d)

                if new_entries:
                    new_path = ";".join(entries + new_entries)
                    winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
                    self.logger.info("[ACT] Added to PATH: %s", new_entries)
                    self._broadcast_setting_change()
                else:
                    self.logger.info("[ACT] Required directories already in PATH.")

            return True, None
        except ImportError:
            self.logger.info("[ACT] Skipping PATH update on non-Windows host.")
            return False, "winreg unavailable"
        except Exception as exc:
            self.logger.error("[ACT] PATH update failed: %s", exc)
            return False, str(exc)

    def _broadcast_setting_change(self):
        """Broadcast WM_SETTINGCHANGE so existing processes pick up the new PATH."""
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            result = ctypes.c_long()
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                "Environment",
                SMTO_ABORTIFHUNG,
                5000,
                ctypes.byref(result)
            )
            self.logger.info("[ACT] Broadcasted WM_SETTINGCHANGE to the system.")
        except Exception as exc:
            self.logger.error("[ACT] Failed to broadcast WM_SETTINGCHANGE: %s", exc)

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
