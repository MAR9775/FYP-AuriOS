import os
import time
import requests
from backend.agents.base_agent import BaseAgent
from backend.utils.platform_utils import is_simulated_host

BASE_URL = (
    "https://github.com/MAR9775/AuriOS-Software-Repository"
    "/releases/download/v1.0/"
)

FILENAME_MAP = {
    "python":     "python-3.11.7-amd64.exe",
    "nodejs":     "node-v20.10.0-x64.msi",
    "git":        "Git-2.43.0-64-bit.exe",
    "vscode":     "VSCodeSetup-x64-1.85.0.exe",
    "docker":     "Docker-Desktop-Installer.exe",
    "java":       "jdk-17_windows-x64_bin.exe",
    "mysql":      "mysql-installer-community-8.0.35.0.msi",
    "postgresql": "postgresql-16.1-1-windows-x64.exe",
    "mongodb":    "mongodb-windows-x86_64-7.0.4-signed.msi",
    "redis":      "Redis-x64-3.0.504.msi",
    "postman":    "Postman-win64-Setup.exe",
}

class DownloadAgent(BaseAgent):
    """Downloads software installers from the AuriOS GitHub repository."""

    def download(self, software_name: str, progress_callback=None) -> str:
        """Download installer for given software. Returns local filepath."""
        filename = FILENAME_MAP.get(software_name.lower())
        if not filename:
            raise ValueError(f"Unknown software: {software_name}")

        # ── Simulated download (non-Windows Docker host) ────────────────────
        # Windows .exe/.msi installers can't run inside a Linux container, so
        # instead of hitting the network we synthesize a stub file and tick
        # progress up to 100% so the UI flow exercises the full pipeline.
        if is_simulated_host():
            sim_dir = "/tmp/auri-simulated"
            os.makedirs(sim_dir, exist_ok=True)
            stub_path = os.path.join(sim_dir, f"{filename}.stub")
            with open(stub_path, "w") as f:
                f.write("simulated installer")
            for pct in (10, 30, 60, 90, 100):
                time.sleep(0.3)
                if progress_callback:
                    progress_callback(pct)
            return stub_path

        url = BASE_URL + filename
        os.makedirs("installers", exist_ok=True)
        dest_path = os.path.join("installers", filename)

        # Skip download if file already exists
        if os.path.exists(dest_path):
            if progress_callback:
                progress_callback(100)
            return dest_path

        for attempt in range(1, 4):
            try:
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()

                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total and progress_callback:
                                pct = (downloaded / total) * 100
                                progress_callback(round(pct, 1))

                if progress_callback:
                    progress_callback(100)
                return dest_path

            except Exception as e:
                if attempt == 3:
                    # Clean up partial file
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    raise RuntimeError(
                        f"Download failed after 3 attempts: {e}"
                    )
                time.sleep(5)
