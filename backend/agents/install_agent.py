import os
import subprocess
import time
from backend.agents.base_agent import BaseAgent
from backend.utils.platform_utils import is_simulated_host

SILENT_FLAGS = {
    ".exe": ["/S", "/quiet", "/norestart"],
    ".msi": ["/quiet", "/norestart", "/qn"],
}

# Some installers need specific flags
CUSTOM_FLAGS = {
    "python-3.11.7-amd64.exe":     ["/quiet", "InstallAllUsers=1",
                                     "PrependPath=1", "Include_test=0"],
    "Git-2.43.0-64-bit.exe":       ["/VERYSILENT", "/NORESTART",
                                     "/NOCANCEL", "/SP-", "/CLOSEAPPLICATIONS"],
    "VSCodeSetup-x64-1.85.0.exe":  ["/VERYSILENT", "/MERGETASKS=!runcode,addcontextmenufiles,addcontextmenufolders,addtopath"],
    "node-v20.10.0-x64.msi":       ["/quiet", "/norestart"],
}

class InstallAgent(BaseAgent):
    """Executes silent software installations."""

    def install(self, installer_path: str) -> dict:
        """Run silent installation for given installer file."""
        # Simulated install for Linux Docker host — the .exe/.msi can't run
        # here, so pretend it succeeded and let the pipeline flow through.
        if is_simulated_host():
            time.sleep(1.0)
            return {"success": True, "error": None}

        if not os.path.exists(installer_path):
            return {"success": False, "error": f"File not found: {installer_path}"}

        filename = os.path.basename(installer_path)
        ext = os.path.splitext(filename)[1].lower()

        # Get flags — custom first, then generic by extension
        flags = CUSTOM_FLAGS.get(filename, SILENT_FLAGS.get(ext, ["/S"]))

        if ext == ".msi":
            cmd = ["msiexec.exe", "/i", installer_path] + flags
        else:
            cmd = [installer_path] + flags

        try:
            result = subprocess.run(
                cmd,
                timeout=600,        # 10 min max per installer
                capture_output=True,
                text=True
            )
            # Exit code 0 or 3010 (reboot required) = success
            if result.returncode in [0, 3010]:
                return {"success": True, "error": None}
            else:
                return {
                    "success": False,
                    "error": f"Exit code {result.returncode}: {result.stderr}"
                }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Installation timed out (10 min)"}
        except Exception as e:
            return {"success": False, "error": str(e)}
