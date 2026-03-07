import os
import subprocess
import shutil

INSTALL_DIR = "/tmp/aurios_installs"  # Temporary installation base directory


def install_software(repo_url: str, software_name: str) -> str:
    """
    Downloads and installs software from a GitHub repository URL.
    Clones the repo, looks for an install.sh script, and runs it.

    Args:
        repo_url: The URL of the GitHub repository (e.g., 'https://github.com/user/project.git').
        software_name: The descriptive name of the software being installed.

    Returns:
        A SUCCESS or FAILURE string indicating the outcome.
    """
    target_path = os.path.join(INSTALL_DIR, software_name)

    # 1. Clean up old installation
    if os.path.exists(target_path):
        try:
            shutil.rmtree(target_path)
        except OSError as e:
            return f"FAILURE: Could not clean old install directory: {e}"

    # 2. Git Clone
    try:
        result = subprocess.run(
            ['git', 'clone', repo_url, target_path],
            capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as e:
        return f"FAILURE: Git clone failed. Error: {e.stderr}"
    except FileNotFoundError:
        return "FAILURE: 'git' command not found. Please ensure Git is installed."

    # 3. Look for and run installer script
    installer_script = os.path.join(target_path, "install.sh")
    if not os.path.exists(installer_script):
        return (
            f"SUCCESS: Repository cloned to {target_path}. "
            f"No 'install.sh' found. Requires manual configuration."
        )

    try:
        subprocess.run(
            ['bash', installer_script],
            cwd=target_path,
            capture_output=True, text=True, check=True
        )
        return (
            f"SUCCESS: Software '{software_name}' installed to {target_path}. "
            f"Proceed to configuration."
        )
    except subprocess.CalledProcessError as e:
        return f"FAILURE: Installation script failed. Error: {e.stderr}"


install_tools = [install_software]