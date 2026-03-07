import os
import subprocess
import time


def validate_software(software_name: str, software_type: str) -> str:
    """
    Validates that software is correctly installed and accessible.
    For coding tools (type='coding'), locates the executable and runs a Hello World test.
    For applications (type='app'), attempts to launch the program.

    Args:
        software_name: The name of the software to validate (e.g., 'python', 'git').
        software_type: Either 'coding' (runs a code test) or 'app' (opens the program).

    Returns:
        A SUCCESS or FAILURE string with validation details.
    """
    # Determine the correct command to locate the executable based on OS
    if os.name == 'nt':
        locate_command = ['where.exe', software_name]
        app_launch_command = ['start', '""', software_name]
    else:
        locate_command = ['which', software_name]
        app_launch_command = [software_name]

    # 1. Check for Executable
    try:
        result = subprocess.run(
            locate_command,
            capture_output=True, text=True, check=True
        )
        executable_path = result.stdout.strip().split('\n')[0]
    except subprocess.CalledProcessError:
        return f"FAILURE: Validation failed. Executable '{software_name}' not found in PATH."
    except FileNotFoundError:
        return "FAILURE: Validation failed. Locate command not found (OS dependency issue)."

    # 2. Run Type-Specific Validation
    if software_type.lower() == 'coding':
        test_file_name = f"aurios_test_{int(time.time())}.py"
        test_script_path = os.path.join(
            os.environ.get('TEMP', '/tmp'), test_file_name
        )

        try:
            with open(test_script_path, "w") as f:
                f.write(f"print('Hello World! {software_name} validation successful.')\n")

            execution_result = subprocess.run(
                [executable_path, test_script_path],
                capture_output=True, text=True, check=True
            )

            output = execution_result.stdout.strip()
            return f"SUCCESS: Validation passed. Test output:\n---{output}---"

        except subprocess.CalledProcessError as e:
            return f"FAILURE: Test script failed to execute. Error: {e.stderr}"
        finally:
            if os.path.exists(test_script_path):
                os.remove(test_script_path)

    elif software_type.lower() == 'app':
        try:
            subprocess.Popen(app_launch_command, shell=(os.name == 'nt'))
            return "SUCCESS: Application launch command sent. Please verify manually."
        except Exception as e:
            return f"FAILURE: Could not execute application launch command: {e}"

    else:
        return f"FAILURE: Invalid software type: '{software_type}'. Must be 'coding' or 'app'."


validate_tools = [validate_software]
