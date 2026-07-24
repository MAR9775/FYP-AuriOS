import os
import subprocess
import time
import shutil
from backend.agents.base_agent import BaseAgent
from backend.utils.platform_utils import is_simulated_host

SILENT_FLAGS = {
    ".exe": ["/S"],
    ".msi": ["/qn", "/norestart"],
}

# Per-installer silent flags — keyed by exact filename
CUSTOM_FLAGS = {
    # Python — standard quiet install
    "python-3.11.7-amd64.exe":                  ["/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0"],
    # Git — Inno Setup
    "Git-2.43.0-64-bit.exe":                    ["/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-", "/CLOSEAPPLICATIONS"],
    # VS Code — Inno Setup
    "VSCodeSetup-x64-1.85.0.exe":               ["/VERYSILENT", "/MERGETASKS=!runcode,addcontextmenufiles,addcontextmenufolders,addtopath"],
    # Node.js MSI
    "node-v20.10.0-x64.msi":                    ["/quiet", "/norestart"],
    # VLC — NSIS
    "vlc-3.0.20-win64.exe":                     ["/S", "/L=1033"],
    # Windsurf — Squirrel, no flags needed
    "WindsurfSetup.exe":                         [],
    # WizTree — NSIS
    "WizTree-Setup.exe":                         ["/S"],
    # PostgreSQL — BitRock InstallBuilder (uses -- prefix, NOT /S)
    "postgresql-16.1-1-windows-x64.exe":         ["--mode", "unattended", "--unattendedmodeui", "none",
                                                   "--disable-components", "stackbuilder"],
    # MySQL — MSI (already handled by .msi default but explicit for clarity)
    "mysql-9.5.0-winx64.msi":                   ["/qn", "/norestart", "INSTALLDIR=C:\\MySQL"],
    # Redis — MSI
    "Redis-x64-3.0.504.msi":                    ["/qn", "/norestart"],
    # MongoDB — MSI
    "mongodb-windows-x86_64-7.0.4-signed.msi":  ["/qn", "/norestart"],
    # Java Corretto — MSI
    "amazon-corretto-17-x64-windows-jdk.msi":   ["/qn", "/norestart", "ADDLOCAL=FeatureMain,FeatureEnvironment,FeatureJarFileRunWith,FeatureJavaHome"],
}

WINGET_IDS = {
    "python":     "Python.Python.3.11",
    "nodejs":     "OpenJS.NodeJS",
    "git":        "Git.Git",
    "vscode":     "Microsoft.VisualStudioCode",
    "docker":     "Docker.DockerDesktop",
    "java":       "Oracle.JDK.17",
    "mysql":      "Oracle.MySQL",
    "postgresql": "PostgreSQL.PostgreSQL.17",
    "mongodb":    "MongoDB.Server",
    "redis":      "Redis.Redis",
    "postman":    "Postman.Postman",
    "vlc":        "VideoLAN.VLC",
    "rufus":      "Rufus.Rufus",
    "7zip":       "7zip.7zip",
    "notepadpp":  "Notepad++.Notepad++",
    "oracle":     "Oracle.VirtualBox",
}

class InstallAgent(BaseAgent):
    """Executes silent software installations."""

    def _parse_error(self, code: int, stderr: str) -> dict:
        reason = f"Installer exited with code {code}"
        details = stderr.strip() if stderr else "Unknown error"
        suggestion = "Check logs or retry."
        
        if code == 1603:
            details = "Permission issue or existing installation conflict"
            suggestion = "Retry as administrator or uninstall previous version"
        elif code == 1618:
            details = "Another installation is already running"
            suggestion = "Wait for other installations to finish and retry"
            
        return {"reason": reason, "details": details, "suggestion": suggestion}

    def install(self, software_name: str, installer_path: str) -> dict:
        """Run silent installation — local repo installer first, winget as fallback."""
        if is_simulated_host():
            time.sleep(1.0)
            return {"success": True, "error": None}

        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        import tempfile

        # ── 1. Local installer from GitHub repo (primary) ─────────────────────
        if os.path.exists(installer_path):
            filename = os.path.basename(installer_path)
            ext = os.path.splitext(filename)[1].lower()
            flags = CUSTOM_FLAGS.get(filename, SILENT_FLAGS.get(ext, ["/S"]))

            if ext == ".msi":
                cmd = ["msiexec.exe", "/i", installer_path] + flags
            else:
                cmd = [installer_path] + flags

            for attempt in range(1, 4):
                try:
                    with tempfile.TemporaryFile(mode="w+") as temp_out:
                        result = subprocess.run(
                            cmd, timeout=600,
                            stdout=temp_out, stderr=subprocess.STDOUT,
                            text=True, creationflags=no_window
                        )
                        temp_out.seek(0)
                        out_text = temp_out.read()

                    if result.returncode in [0, 3010]:
                        return {"success": True, "error": None}

                    if result.returncode == 1620:
                        try:
                            os.remove(installer_path)
                        except Exception:
                            pass
                        return {"success": False, "error": {
                            "reason": "Corrupted Installer",
                            "details": "Error 1620: Invalid MSI package",
                            "suggestion": "The downloaded installer was corrupted and has been deleted. Please try again to re-download."
                        }}

                    if attempt < 3:
                        time.sleep(2 ** attempt)
                        continue

                    self.logger.warning(f"Local installer failed for {software_name} (code {result.returncode}), trying winget...")
                    break  # fall through to winget

                except subprocess.TimeoutExpired:
                    if attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    self.logger.warning(f"Local installer timed out for {software_name}, trying winget...")
                    break

                except Exception as e:
                    err_str = str(e)
                    if "1392" in err_str or "193" in err_str or "225" in err_str:
                        try:
                            os.remove(installer_path)
                        except Exception:
                            pass
                        return {"success": False, "error": {
                            "reason": "Corrupted Installer",
                            "details": err_str,
                            "suggestion": "The installer file was corrupted and has been deleted. Please try again to re-download."
                        }}
                    if attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    self.logger.warning(f"Local installer error for {software_name}: {e}, trying winget...")
                    break
        else:
            self.logger.info(f"No local installer found for {software_name}, trying winget...")

        # ── 2. Winget fallback ────────────────────────────────────────────────
        winget_id = WINGET_IDS.get(software_name)
        if winget_id and shutil.which("winget"):
            self.logger.info(f"Attempting to install {software_name} via winget ({winget_id})...")
            cmd = [
                "winget", "install", "--id", winget_id,
                "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements"
            ]
            try:
                with tempfile.TemporaryFile(mode="w+") as temp_out:
                    result = subprocess.run(cmd, timeout=600, stdout=temp_out, stderr=subprocess.STDOUT, text=True, creationflags=no_window)
                    temp_out.seek(0)
                    out_text = temp_out.read()
                if result.returncode in [0, 3010]:
                    return {"success": True, "error": None}
                self.logger.warning(f"Winget failed for {software_name}: {out_text}")
            except Exception as e:
                self.logger.warning(f"Winget error for {software_name}: {e}")

        # ── 3. Choco last resort ──────────────────────────────────────────────
        if shutil.which("choco"):
            self.logger.info(f"Attempting to install {software_name} via choco...")
            try:
                with tempfile.TemporaryFile(mode="w+") as temp_out:
                    result = subprocess.run(
                        ["choco", "install", software_name, "-y"],
                        timeout=600, stdout=temp_out, stderr=subprocess.STDOUT,
                        text=True, creationflags=no_window
                    )
                    temp_out.seek(0)
                    out_text = temp_out.read()
                if result.returncode in [0, 3010]:
                    return {"success": True, "error": None}
                self.logger.warning(f"Choco failed for {software_name}: {out_text}")
            except Exception as e:
                self.logger.warning(f"Choco error for {software_name}: {e}")

        return {"success": False, "error": {
            "reason": "All install methods failed",
            "details": f"Local installer, winget, and choco all failed for {software_name}.",
            "suggestion": "Check your internet connection and try again, or install manually."
        }}
