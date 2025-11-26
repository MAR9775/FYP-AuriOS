import os
import subprocess

# In a real environment, you'd dynamically determine the install path
DEFAULT_INSTALL_BASE = "C:\\AurIOS_Installs" # Windows-friendly path
# Note: On Windows, environment changes made via subprocess are NOT visible
# to the current running Python process, only to future processes.

def _add_to_path_windows(path_to_add: str) -> bool:
    """Helper function to permanently add a path to the System PATH (Windows)."""
    
    try:
        # Check current system PATH to see if the path is already set
        # This is complex and often skipped in simple path config checks.
        
        # Use 'setx' command to permanently set the System PATH for the current user
        # Note: This command is platform-specific and requires appropriate user permissions.
        # We assume the new path needs to be appended to the existing PATH variable.
        
        # Action: Call setx to modify the PATH variable.
        print(f"Thought: Using setx to permanently add {path_to_add} to user PATH.")
        
        # WARNING: setx can truncate the PATH variable if it's too long. 
        # For prototype, we'll try a basic approach:
        command = f'setx PATH "%PATH%;{path_to_add}"'
        subprocess.run(command, shell=True, check=True, capture_output=True)
            
        print(f"Observation: setx command executed successfully.")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"FAILURE: setx command failed. Error: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"FAILURE: Could not execute path modification: {e}")
        return False


def run_configuration(software_name: str, install_path: str = None) -> str:
    """
    Sets up system paths and performs necessary environmental configurations.
    """
    if not install_path:
        install_path = os.path.join(DEFAULT_INSTALL_BASE, software_name)

    # 1. Check if install path exists
    if not os.path.isdir(install_path):
        return f"FAILURE: Configuration aborted. Installation directory not found: {install_path}"

    # 2. Add to System PATH
    print(f"Thought: Attempting to add {install_path} to system PATH.")
    
    if os.name == 'nt': # 'nt' means Windows
        success = _add_to_path_windows(install_path)
    else:
        # Fails explicitly if run on a non-Windows machine, enforcing your target OS
        return f"FAILURE: Configuration logic only supports Windows ('nt') OS. Detected OS: {os.name}"
        
    # 3. Report Status
    if success:
        return f"SUCCESS: Software '{software_name}' configured. Path added. Requires log out/restart to take full effect."
    else:
        return f"FAILURE: Configuration failed while trying to set system path for '{software_name}'."
