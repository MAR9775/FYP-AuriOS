import os
import time
import requests
from backend.agents.base_agent import BaseAgent
from backend.utils.platform_utils import is_simulated_host
from backend.utils import repo_sync

class DownloadAgent(BaseAgent):
    """Downloads software installers from the AuriOS GitHub repository."""

    def download(self, software_name: str, progress_callback=None) -> str:
        """Download installer for given software. Returns local filepath."""
        info = repo_sync.get_download_info(software_name.lower())
        if not info:
            raise ValueError(
                f"Sorry, '{software_name}' is not available in the AuriOS repository yet."
            )
        filename = info["filename"]
        url = info["url"]

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

                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    raise RuntimeError(f"Download URL returned an HTML page. The link might be broken or require authentication.")

                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                last_pct = -1

                part_path = dest_path + ".part"
                with open(part_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total and progress_callback:
                                pct = int((downloaded / total) * 100)
                                if pct > last_pct:
                                    progress_callback(pct)
                                    last_pct = pct
                
                # Download complete, rename to final path
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(part_path, dest_path)

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
                # Exponential backoff: 2s, 4s
                time.sleep(2 ** attempt)
