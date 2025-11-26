import os
import subprocess

# In a real environment, you'd dynamically determine the install path
# or receive it from the Install Agent's result.
# For this prototype, we'll assume the path set by the Install Agent.
DEFAULT_INSTALL_BASE = "/tmp/aurios_installs" 
SHELL_CONFIG_FILE = os.path.expanduser("~/.bashrc") # Target config file for Linux/macOS

def _add_to_path_unix(path_to_add: str) -> bool:
    """Helper function to append a path to the shell config file (Unix/Linux)."""
    export_command = f'export PATH="$PATH:{path_to_add}"'
    
    try:
        # Check if the path is already set (basic check)
        with open(SHELL_CONFIG_FILE, 'r') as f:
            if path_to_add in f.read():
                print(f"Thought: Path {path_to_add} already configured. Skipping.")
                return True
                
        # Append the export command to the shell config
        with open(SHELL_CONFIG_FILE, 'a') as f:
            f.write(f"\n# Added by AurIOS Configure Agent\n{export_command}\n")
            
        print(f"Observation: Added export command to {SHELL_CONFIG_FILE}. User must source file.")
        
        # Note: For changes to take effect immediately, the user's current shell 
        # needs to be 'sourced' (e.g., source ~/.bashrc), which is hard to do 
        # from a subprocess. We'll simply report success.
        return True
        
    except Exception as e:
        print(f"FAILURE: Could not modify shell config: {e}")
        return False


def run_configuration(software_name: str, install_path: str = None) -> str:
    """
    Sets up system paths and performs necessary environmental configurations.
    """
    if not install_path:
        # Assume standard installation path if not explicitly provided
        install_path = os.path.join(DEFAULT_INSTALL_BASE, software_name)

    # 1. Check if install path exists (ReAct Thought)
    if not os.path.isdir(install_path):
        return f"FAILURE: Configuration aborted. Installation directory not found: {install_path}"

    # 2. Add to System PATH (ReAct Action)
    print(f"Thought: Attempting to add {install_path} to system PATH.")
    
    # Simple check for Unix-like system
    if os.name == 'posix':
        success = _add_to_path_unix(install_path)
    else:
        # Placeholder for Windows or other OS logic
        return f"FAILURE: Configuration logic for OS '{os.name}' is not yet implemented."
        
    # 3. Report Status (ReAct Observation)
    if success:
        return f"SUCCESS: Software '{software_name}' configured. Path added. Requires shell restart/sourcing."
    else:
        return f"FAILURE: Configuration failed while trying to set system path for '{software_name}'."
