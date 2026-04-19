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
    for exe in _launch_candidates(software):
        if not exe:
            continue
        if os.path.sep not in exe:
            if _shutil.which(exe):
                subprocess.Popen([exe], creationflags=subprocess.DETACHED_PROCESS)
                return
        elif os.path.isfile(exe):
            subprocess.Popen([exe], creationflags=subprocess.DETACHED_PROCESS)
            return

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
        "pip_packages": ["tensorflow==2.15.0", "jupyter"],
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

        # ── Stage 1: Detection ────────────────────────────────────────────────
        _cb("detection", "running", 5, "Scanning installed software…")
        detection_result = await asyncio.to_thread(DetectionAgent().run, {})
        installed = detection_result.get("installed", {})
        to_install = [s for s in software_list if not installed.get(s, False)]
        _cb("detection", "done", 15, f"Need to install: {to_install if to_install else 'nothing — all present'}")

        # ── Stage 2: Download ─────────────────────────────────────────────────
        downloader = DownloadAgent()
        installer_paths = {}   # software_name → local filepath

        if to_install:
            _cb("download", "running", 20, f"Downloading {to_install}…")
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
                    _cb("download", "running", base_pct, f"{software}: download failed — {e}")

            _cb("download", "done", 40, "Downloads complete.")
        else:
            _cb("download", "done", 40, "Nothing to download — all tools present.")

        # ── Stage 3: Install ──────────────────────────────────────────────────
        if installer_paths:
            _cb("install", "running", 42, f"Installing {list(installer_paths)}…")
            total_installs = len(installer_paths)
            inst_agent = InstallAgent()
            failed_installs = []

            for i, (software, filepath) in enumerate(installer_paths.items()):
                pct = 42 + int((i / total_installs) * 18)
                _cb("install", "running", pct, f"Installing {software}…")
                result = await asyncio.to_thread(inst_agent.install, filepath)
                if result["success"]:
                    _cb("install", "running", pct + int(18 / total_installs),
                        f"{software} installed ✓")
                else:
                    _cb("install", "running", pct, f"{software} failed: {result['error']}")
                    failed_installs.append(software)

            if failed_installs:
                _cb("install", "failed", 60, f"Installation failed for: {failed_installs}")
                task_manager.set_final_message(task_id, f"⚠️ Installation failed for {', '.join(failed_installs)}")
                task_manager.update_task(task_id, "failed", 60, "failed")
                return

            _cb("install", "done", 60, "Installation complete.")
        else:
            _cb("install", "done", 60, "Nothing to install.")

        # ── Stage 4: Configure ────────────────────────────────────────────────
        _cb("configure", "running", 62, f"Configuring PATH and pip packages {pip_packages}…")
        configure_result = await asyncio.to_thread(
            ConfigureAgent().run, {"pip_packages": pip_packages}
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
        installed_names = [PRETTY.get(s, s) for s in software_list]
        if len(installed_names) == 1:
            final_msg = (
                f"✅ {installed_names[0]} has been installed, configured, and validated!"
            )
        elif len(installed_names) == 2:
            final_msg = (
                f"✅ {installed_names[0]} and {installed_names[1]} are installed and ready!"
            )
        else:
            final_msg = (
                f"✅ {', '.join(installed_names[:-1])}, and {installed_names[-1]} "
                f"are installed and ready!"
            )
        if pip_packages:
            final_msg += f" Extra packages: {', '.join(pip_packages)}."

        # ── Stage 7: Launch installed apps ───────────────────────────────────
        launchable = [s for s in software_list if s in _LAUNCH_EXE]
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
