import asyncio
import glob
import os
import subprocess

from backend.agents.detection_agent import DetectionAgent
from backend.agents.download_agent import DownloadAgent
from backend.agents.install_agent import InstallAgent
from backend.agents.configure_agent import ConfigureAgent
from backend.agents.validate_agent import ValidationAgent
from backend.agents.environment_agent import EnvironmentAgent
from backend.core.task_manager import task_manager
from backend.utils.platform_utils import is_windows

_LOCAL = os.environ.get("LOCALAPPDATA", "")
_PROG  = r"C:\Program Files"
_PROG86 = r"C:\Program Files (x86)"
_HOME  = os.path.expanduser("~")

# Executables to launch after a software is installed.
# CLI-only tools (python, git, node, java…) are intentionally omitted.
# Static paths per software (no glob — evaluated lazily in _launch_candidates).
_LAUNCH_STATIC: dict[str, list[str]] = {
    "vscode":    ["code"],
    "postman":   [os.path.join(_LOCAL, "Programs", "Postman", "Postman.exe")],
    "docker":    [os.path.join(_PROG, "Docker", "Docker", "Docker Desktop.exe")],
    "vlc":       [
        os.path.join(_PROG,   "VideoLAN", "VLC", "vlc.exe"),
        os.path.join(_PROG86, "VideoLAN", "VLC", "vlc.exe"),
    ],
    "rufus":     [
        os.path.join(_PROG,   "Rufus", "rufus.exe"),
        os.path.join(_PROG86, "Rufus", "rufus.exe"),
        os.path.join(_LOCAL,  "Programs", "Rufus", "rufus.exe"),
    ],
    "7zip":      [
        os.path.join(_PROG,   "7-Zip", "7zFM.exe"),
        os.path.join(_PROG86, "7-Zip", "7zFM.exe"),
    ],
    "notepadpp": [
        os.path.join(_PROG,   "Notepad++", "notepad++.exe"),
        os.path.join(_PROG86, "Notepad++", "notepad++.exe"),
    ],
    "mysql":     [
        os.path.join(_PROG,   "MySQL", "MySQL Workbench 8.0", "MySQLWorkbench.exe"),
        os.path.join(_PROG86, "MySQL", "MySQL Workbench 8.0", "MySQLWorkbench.exe"),
    ],
    "wiztree":   [
        os.path.join(_PROG,   "WizTree", "WizTree64.exe"),
        os.path.join(_PROG86, "WizTree", "WizTree.exe"),
        os.path.join(_PROG,   "WizTree", "WizTree.exe"),
    ],
    "windsurf":  [
        os.path.join(_LOCAL, "Programs", "Windsurf", "Windsurf.exe"),
        os.path.join(_PROG,  "Windsurf", "Windsurf.exe"),
    ],
    "greenshot": [
        os.path.join(_PROG,   "Greenshot", "Greenshot.exe"),
        os.path.join(_PROG86, "Greenshot", "Greenshot.exe"),
    ],
    "everything": [
        os.path.join(_PROG,   "Everything", "Everything.exe"),
        os.path.join(_PROG86, "Everything", "Everything.exe"),
    ],
    "lm": [
        os.path.join(_LOCAL, "Programs", "lm-studio", "LM Studio.exe"),
        os.path.join(_LOCAL, "LM-Studio", "LM Studio.exe"),
    ],
}


def _launch_candidates(software: str) -> list[str]:
    """Return all candidate exe paths for *software*, including portable globs."""
    paths = list(_LAUNCH_STATIC.get(software, []))
    if software == "rufus":
        # Rufus is often a portable exe — scan at call-time so we catch it
        # even if it was downloaded after the server started.
        paths += glob.glob(os.path.join(_HOME, "Downloads", "rufus*.exe"))
        paths += glob.glob(os.path.join(_HOME, "Desktop",   "rufus*.exe"))
    return paths


def _launch(software: str) -> None:
    """Try to open the GUI for *software* after installation. Best-effort."""
    if not is_windows():
        return
    import shutil as _shutil
    import time
    try:
        # Wait up to 30 seconds for the executable to exist (for background installers)
        for _ in range(15):
            for exe in _launch_candidates(software):
                if not exe:
                    continue
                if os.path.sep not in exe:
                    resolved = _shutil.which(exe)
                    if resolved:
                        if resolved.lower().endswith((".cmd", ".bat")):
                            subprocess.Popen(resolved, shell=True, creationflags=subprocess.DETACHED_PROCESS)
                        else:
                            subprocess.Popen([resolved], creationflags=subprocess.DETACHED_PROCESS)
                        return
                elif os.path.isfile(exe):
                    subprocess.Popen([exe], creationflags=subprocess.DETACHED_PROCESS)
                    return
            time.sleep(2)
    except Exception:
        pass

# Friendly display names for every software and preset the orchestrator knows
# about. Imported by ``backend.server`` for response-text generation so both
# places share one source of truth.
PRETTY = {
    # individual tools
    "python":       "Python",
    "nodejs":       "Node.js",
    "git":          "Git",
    "vscode":       "VS Code",
    "docker":       "Docker",
    "java":         "Java",
    "mysql":        "MySQL",
    "postgresql":   "PostgreSQL",
    "mongodb":      "MongoDB",
    "redis":        "Redis",
    "postman":      "Postman",
    "lm":           "LM Studio",
    "oracle":       "Oracle VirtualBox",
    # Additional catalog tools
    "everything":   "Everything",
    "wiztree":      "WizTree",
    "windsurf":     "Windsurf",
    "greenshot":    "Greenshot",
    "githubdesktop":"GitHub Desktop",
    "dbeaver":      "DBeaver",
    "dotnet":       ".NET",
    "notion":       "Notion",
    "powertoys":    "PowerToys",
    "rufus":        "Rufus",
    "7zip":         "7-Zip",
    "notepadpp":    "Notepad++",
    "vlc":          "VLC Media Player",
    # presets
    "python_basic": "Python basics",
    "python_ml":    "Python ML",
    "web_dev":      "web dev",
    "full_stack":   "full stack",
    "data_science": "data science",
}

PRESET_CONFIGS = {
    "python_basic":  {
        "software": ["python", "vscode", "git"],
        "pip_packages": [],
    },
    "python_ml":     {
        "software": ["python", "vscode", "git"],
        "pip_packages": ["tensorflow==2.15.0", "torch", "scikit-learn", "jupyter"],
    },
    "web_dev":       {
        "software": ["nodejs", "vscode", "git"],
        "pip_packages": [],
    },
    "data_science":  {
        "software": ["python", "vscode", "git"],
        "pip_packages": ["jupyter", "pandas", "numpy", "matplotlib"],
    },
    "full_stack":    {
        "software": ["python", "nodejs", "git", "vscode", "docker",
                     "java", "mysql", "postgresql", "mongodb",
                     "redis", "postman"],
        "pip_packages": [],
    },
    "java":          {
        "software": ["java", "vscode", "git"],
        "pip_packages": [],
    },
}


class Orchestrator:
    """Coordinates all agents: detect → download → install → configure → validate → environment."""

    async def run(self, preset_name: str, task_id: str, progress_callback):
        """Run the full 6-stage pipeline."""
        config = PRESET_CONFIGS.get(preset_name, {"software": [preset_name], "pip_packages": []})
        software_list = config["software"]
        pip_packages = config["pip_packages"]

        def _cb(step: str, status: str, pct: int, msg: str):
            # Overall task status stays "running" for intermediate steps so the
            # WebSocket doesn't close prematurely on individual step completion.
            if status in ("failed", "cancelled"):
                task_status = status
            elif step == "complete":
                task_status = "done"
            else:
                task_status = "running"
            # Encode "step:step_status" so the WS can report per-step state.
            task_manager.update_task(task_id, task_status, pct, f"{step}:{status}")
            progress_callback(step, status, pct, msg)

        # ── Stage 1: Detection & System Specs ─────────────────────────────────
        _cb("detection", "running", 5, "Resolving package...")
        detection_result = await asyncio.to_thread(DetectionAgent().run, {})
        installed = detection_result.get("installed", {})
        free_gb = detection_result.get("free_disk_gb", 0)
        is_admin = detection_result.get("is_admin", False)
        
        to_install = []
        failed_installs = []
        
        from backend.utils import repo_sync
        from backend.utils.platform_utils import is_windows
        
        for software in software_list:
            if installed.get(software, False):
                continue
                
            info = repo_sync.get_download_info(software)
            if not info:
                failed_installs.append(software)
                continue
                
            required_gb = info.get("size_mb", 0) / 1024.0
            if is_windows() and not is_admin:
                failed_installs.append(software)
                continue
                
            if free_gb < required_gb:
                failed_installs.append(software)
                continue
                
            to_install.append(software)

        if failed_installs:
            _cb("detection", "failed", 15, f"Validation failed for: {failed_installs}")
            task_manager.set_final_message(task_id, f"Pre-install validation failed for {', '.join(failed_installs)}")
            return
            
        _cb("detection", "done", 15, f"Need to install: {to_install if to_install else 'nothing — all present'}")

        # ── Stage 2: Download ─────────────────────────────────────────────────
        downloader = DownloadAgent()
        installer_paths = {}

        if to_install:
            _cb("download", "running", 20, "Downloading...")
            total_items = len(to_install)

            for i, software in enumerate(to_install):
                base_pct = 20 + int((i / total_items) * 20)

                def make_dl_cb(b, n, sw):
                    def cb(pct):
                        overall = b + int((pct / 100) * (20 // n))
                        _cb("download", "running", overall, f"{sw}: {pct:.0f}%")
                    return cb

                try:
                    filepath = await asyncio.to_thread(
                        downloader.download, software, make_dl_cb(base_pct, total_items, software)
                    )
                    installer_paths[software] = filepath
                except Exception as e:
                    _cb("download", "failed", base_pct, f"{software}: download failed — {e}")
                    task_manager.set_final_message(task_id, f"Download failed for {software}: {e}")
                    return

            _cb("download", "done", 40, "Downloads complete.")
        else:
            _cb("download", "done", 40, "Nothing to download — all tools present.")

        # ── Stage 3: Install ──────────────────────────────────────────────────
        if installer_paths:
            _cb("install", "running", 42, "Installing silently...")
            total_installs = len(installer_paths)
            inst_agent = InstallAgent()

            for i, (software, filepath) in enumerate(installer_paths.items()):
                pct = 42 + int((i / total_installs) * 18)
                _cb("install", "running", pct, f"Installing {software} silently...")
                
                # Auto-retry logic
                result = await asyncio.to_thread(inst_agent.install, software, filepath)
                if not result["success"]:
                    if os.path.exists(filepath):
                        _cb("install", "running", pct, f"Retry: Installing {software} silently...")
                        result = await asyncio.to_thread(inst_agent.install, software, filepath)
                    
                if result.get("success"):
                    _cb("install", "running", pct + int(18 / total_installs),
                        f"{software} installed ✓")
                else:
                    err = result.get('error', {})
                    if isinstance(err, str):
                        err = {"reason": "Execution Error", "details": err, "suggestion": "Check system permissions."}
                    _cb("install", "failed", pct, f"{software} failed: {err.get('reason', 'Unknown error')}")
                    
                    error_msg = (
                        f"Installation failed.\n"
                        f"Reason: {err.get('reason', 'Installer exited with unknown code')}\n"
                        f"Details: {err.get('details', 'Unknown error')}\n"
                        f"Suggestion: {err.get('suggestion', 'Check logs or retry.')}"
                    )
                    task_manager.set_final_message(task_id, error_msg)
                    task_manager.update_task(task_id, "failed", pct, "failed")
                    return

            _cb("install", "done", 60, "Installation complete.")
        else:
            _cb("install", "done", 60, "Nothing to install.")


        # ── Stage 4: Configure ────────────────────────────────────────────────
        _cb("configure", "running", 62, "Finalizing setup...")
        configure_result = await asyncio.to_thread(
            ConfigureAgent().run, {"pip_packages": pip_packages, "software_list": software_list}
        )
        pip_ok = [k for k, v in configure_result.get("pip_results", {}).items() if v.get("success")]
        pip_fail = [k for k, v in configure_result.get("pip_results", {}).items() if not v.get("success")]
        configure_msg = "PATH updated"
        if pip_ok:
            configure_msg += f", installed: {pip_ok}"
        if pip_fail:
            configure_msg += f", failed: {pip_fail}"
        _cb("configure", "done", 75, configure_msg)

        # ── Stage 5: Validate ─────────────────────────────────────────────────
        _cb("validate", "running", 77, f"Verifying {software_list}…")
        validate_result = await asyncio.to_thread(
            ValidationAgent().run, {"expected_software": software_list}
        )
        validation = validate_result.get("validation", {})
        all_ok = all(validation.values()) if validation else True
        passed = [k for k, v in validation.items() if v]
        failed = [k for k, v in validation.items() if not v]
        validate_msg = f"✓ {passed}" if all_ok else f"✓ {passed}  ✗ {failed}"
        
        if not all_ok:
            _cb("validate", "failed", 90, validate_msg)
            task_manager.set_final_message(task_id, f"⚠️ Validation failed. Missing: {', '.join(failed)}")
            task_manager.update_task(task_id, "failed", 90, "failed")
            return

        _cb("validate", "done", 90, validate_msg)

        # ── Stage 6: Environment ──────────────────────────────────────────────
        _cb("environment", "running", 92, "Setting up project folder and venv…")
        env_result = await asyncio.to_thread(EnvironmentAgent().run, {})
        env_msg = (
            f"venv ready at {env_result.get('project_root', '~')}"
            if env_result.get("venv_created")
            else "Environment step done (venv optional)"
        )
        _cb("environment", "done", 100, env_msg)

        # ── Build final user-facing message ───────────────────────────────────
        final_msg = "Installation complete."

        # ── Stage 7: Launch installed apps ───────────────────────────────────
        launchable = [s for s in software_list if s in _LAUNCH_STATIC]
        if launchable:
            _cb("launch", "running", 100, f"Opening {launchable}…")
            for sw in launchable:
                await asyncio.to_thread(_launch, sw)
            _cb("launch", "done", 100, "Apps launched.")

        # Persist to its own column FIRST, then mark status=done — the WS
        # reader calls get_task() which returns both in one row.
        task_manager.set_final_message(task_id, final_msg)
        task_manager.update_task(task_id, "done", 100, "complete")
        progress_callback("complete", "done", 100, "All done!")
