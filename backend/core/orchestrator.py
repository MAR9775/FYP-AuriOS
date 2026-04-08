import asyncio
from backend.agents.detection_agent import DetectionAgent
from backend.agents.download_agent import DownloadAgent
from backend.agents.install_agent import InstallAgent
from backend.agents.configure_agent import ConfigureAgent
from backend.agents.validate_agent import ValidationAgent
from backend.agents.environment_agent import EnvironmentAgent
from backend.core.task_manager import task_manager

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
            task_manager.update_task(task_id, status, pct, step)
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

            for i, (software, filepath) in enumerate(installer_paths.items()):
                pct = 42 + int((i / total_installs) * 18)
                _cb("install", "running", pct, f"Installing {software}…")
                result = await asyncio.to_thread(inst_agent.install, filepath)
                if result["success"]:
                    _cb("install", "running", pct + int(18 / total_installs),
                        f"{software} installed ✓")
                else:
                    _cb("install", "running", pct, f"{software} failed: {result['error']}")

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
        _cb("validate", "done" if all_ok else "running", 90, validate_msg)

        # ── Stage 6: Environment ──────────────────────────────────────────────
        _cb("environment", "running", 92, "Setting up project folder and venv…")
        env_result = await asyncio.to_thread(EnvironmentAgent().run, {})
        env_msg = (
            f"venv ready at {env_result.get('project_root', '~')}"
            if env_result.get("venv_created")
            else "Environment step done (venv optional)"
        )
        _cb("environment", "done", 100, env_msg)

        task_manager.update_task(task_id, "done", 100, "complete")
        progress_callback("complete", "done", 100, "All done!")
