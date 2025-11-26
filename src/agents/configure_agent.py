import os
import subprocess

# In a real environment, you'd dynamically determine the install path
DEFAULT_INSTALL_BASE = "C:\\AurIOS_Installs" # Windows-friendly path

def _add_to_path_windows(path_to_add: str) -> bool:
    """
    Helper function to permanently add a path to the System PATH (Windows).
    This function assumes it is being run with ADMINISTRATOR PRIVILEGES.
    """
    
    try:
        # Action: Use 'setx' command to permanently set the System PATH for the current USER
        # This command requires elevation, which is guaranteed by the application launch.
        
        print(f"Thought: Using setx to permanently add {path_to_add} to user PATH.")
        
        # We append the new path to the existing %PATH% environment variable
        command = f'setx PATH "%PATH%;{path_to_add}"'
        
        # Run command without shell=True for better security and checking, 
        # but sometimes 'setx' requires it for variable expansion. Let's use check=True.
        subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
            
        print(f"Observation: setx command executed successfully.")
        return True
        
    except subprocess.CalledProcessError as e:
        # If this fails, it's a structural error (e.g., setx syntax, very long PATH) 
        # not a permission error, as permissions are guaranteed.
        error_message = e.stderr or e.stdout
        print(f"FAILURE: setx command failed (non-permission error). Output: {error_message.strip()}")
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
    
    # Check for Windows OS before running Windows-specific command
    if os.name == 'nt': 
        success = _add_to_path_windows(install_path)
    else:
        # This will only be hit if someone tries to run the Windows-only code on Linux/macOS.
        return f"FAILURE: Configuration logic only supports Windows ('nt') OS. Detected OS: {os.name}"
        
    # 3. Report Status
    if success:
        return f"SUCCESS: Software '{software_name}' configured. Path added. Requires log out/restart to take full effect."
    else:
        return f"FAILURE: Configuration failed while trying to set system path for '{software_name}'."
