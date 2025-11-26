import os
import subprocess
import shutil

INSTALL_DIR = "/tmp/aurios_installs" # Temporary installation base directory

def run_installation(repo_url: str, software_name: str) -> str:
    """
    Clones a GitHub repository and attempts to run a common installation script (like 'install.sh').
    This function uses a simple approach for the prototype.
    """
    target_path = os.path.join(INSTALL_DIR, software_name)
    
    # 1. Clean up old installation (ReAct Thought/Action)
    if os.path.exists(target_path):
        try:
            print(f"Thought: Existing directory found at {target_path}. Deleting it.")
            shutil.rmtree(target_path)
        except OSError as e:
            return f"FAILURE: Could not clean old install directory: {e}"

    # 2. Git Clone (ReAct Thought/Action)
    print(f"Thought: Cloning repository {repo_url} into {target_path}.")
    try:
        # We use subprocess.run for better error handling than os.system
        result = subprocess.run(['git', 'clone', repo_url, target_path], 
                                capture_output=True, text=True, check=True)
        print(f"Observation: Git clone output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        return f"FAILURE: Git clone failed. Error: {e.stderr}"
    except FileNotFoundError:
        return "FAILURE: 'git' command not found. Please ensure Git is installed."

    # 3. Look for and Run Installer Script (ReAct Thought/Action)
    installer_script = os.path.join(target_path, "install.sh")
    if not os.path.exists(installer_script):
        # Fallback to general installation steps for a prototype
        return f"SUCCESS: Repository cloned to {target_path}. No 'install.sh' found. Requires manual configuration."

    print(f"Thought: Found installer script. Attempting to execute {installer_script}.")
    try:
        install_result = subprocess.run(['bash', installer_script], 
                                        cwd=target_path, 
                                        capture_output=True, text=True, check=True)
        print(f"Observation: Installation script output: {install_result.stdout}")
        return f"SUCCESS: Software '{software_name}' installed to {target_path}. Proceed to configuration."
    except subprocess.CalledProcessError as e:
        return f"FAILURE: Installation script failed. Error: {e.stderr}"
