import os
import subprocess

DEFAULT_INSTALL_BASE = "/tmp/aurios_installs"


def _add_to_path_linux(path_to_add: str) -> bool:
    """
    Adds a path to the current user's shell profile (~/.bashrc) on Linux.
    """
    bashrc_path = os.path.expanduser("~/.bashrc")
    export_line = f'\nexport PATH="$PATH:{path_to_add}"\n'

    try:
        # Check if already in bashrc
        if os.path.exists(bashrc_path):
            with open(bashrc_path, "r") as f:
                if path_to_add in f.read():
                    return True

        with open(bashrc_path, "a") as f:
            f.write(export_line)

        # Also set for current session
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + path_to_add
        return True

    except Exception as e:
        print(f"FAILURE: Could not modify PATH: {e}")
        return False


def _add_to_path_windows(path_to_add: str) -> bool:
    """
    Permanently adds a path to the System PATH on Windows using setx.
    """
    try:
        command = f'setx PATH "%PATH%;{path_to_add}"'
        subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        error_message = e.stderr or e.stdout
        print(f"FAILURE: setx command failed. Output: {error_message.strip()}")
        return False
    except Exception as e:
        print(f"FAILURE: Could not execute path modification: {e}")
        return False


def configure_software(software_name: str, install_path: str = None) -> str:
    """
    Configures environment variables and system paths for installed software.
    Adds the software's install directory to the system PATH.

    Args:
        software_name: The name of the software to configure.
        install_path: Optional path where the software was installed.

    Returns:
        A SUCCESS or FAILURE string indicating the outcome.
    """
    if not install_path:
        install_path = os.path.join(DEFAULT_INSTALL_BASE, software_name)

    # 1. Check if install path exists
    if not os.path.isdir(install_path):
        return f"FAILURE: Configuration aborted. Installation directory not found: {install_path}"

    # 2. Add to System PATH (platform-aware)
    if os.name == 'nt':
        success = _add_to_path_windows(install_path)
    else:
        success = _add_to_path_linux(install_path)

    # 3. Report Status
    if success:
        return (
            f"SUCCESS: Software '{software_name}' configured. "
            f"Path '{install_path}' added to system PATH."
        )
    else:
        return f"FAILURE: Configuration failed while trying to set system path for '{software_name}'."


configure_tools = [configure_software]
