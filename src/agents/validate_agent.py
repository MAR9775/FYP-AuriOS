import os
import subprocess
import time

def run_validation(software_name: str, software_type: str) -> str:
    """
    Validates the software installation by checking accessibility and running a test.
    """
    # Determine the correct command to locate the executable based on OS
    if os.name == 'nt':
        locate_command = ['where.exe', software_name]
        app_launch_command = ['start', '""', software_name] # Use 'start' for opening apps
    else:
        locate_command = ['which', software_name]
        app_launch_command = ['open', '-a', software_name]

    # 1. Check for Executable (ReAct Thought/Action)
    print(f"Thought: Checking if '{software_name}' executable is accessible via PATH using {'where.exe' if os.name == 'nt' else 'which'}.")
    try:
        # Locate the executable path
        result = subprocess.run(locate_command, 
                                capture_output=True, text=True, check=True)
        executable_path = result.stdout.strip().split('\n')[0] # Windows 'where' might return multiple paths
        print(f"Observation: Executable found at {executable_path}")
    except subprocess.CalledProcessError:
        return f"FAILURE: Validation failed. Executable '{software_name}' not found in PATH."
    except FileNotFoundError:
        return "FAILURE: Validation failed. Executing command not found (OS dependency issue)."
        
    # 2. Run Type-Specific Validation (ReAct Action)
    if software_type.lower() == 'coding':
        print("Thought: Running 'Hello World' test for coding software.")
        
        # Create a temporary test file
        test_file_name = f"aurios_test_{int(time.time())}.py"
        test_script_path = os.path.join(os.environ.get('TEMP', '/tmp'), test_file_name) # Use TEMP on Windows
        
        try:
            with open(test_script_path, "w") as f:
                f.write(f"print('Hello World! {software_name} validation successful.')\n")
            
            # Execute the test script using the located executable (e.g., C:\Python\python.exe C:\Temp\test.py)
            execution_result = subprocess.run([executable_path, test_script_path], 
                                              capture_output=True, text=True, check=True)
            
            # 3. Report Success with Output (ReAct Observation)
            output = execution_result.stdout.strip()
            return f"SUCCESS: Validation passed. Test output:\n---{output}---"
            
        except subprocess.CalledProcessError as e:
            return f"FAILURE: Test script failed to execute. Error: {e.stderr}"
        finally:
            if os.path.exists(test_script_path):
                os.remove(test_script_path)
                
    elif software_type.lower() == 'app':
        # Simple attempt to launch the application (using 'start' on Windows)
        print("Thought: Attempting to launch the application for manual verification.")
        
        try:
            # Popen is used to launch an external process non-blockingly
            # shell=True is sometimes needed for 'start' command syntax
            subprocess.Popen(app_launch_command, shell=True) 
            return "SUCCESS: Application launch command sent. Please verify manually."
        except Exception as e:
            return f"FAILURE: Could not execute application launch command: {e}"
            
    else:
        return f"FAILURE: Invalid software type specified: {software_type}. Must be 'coding' or 'app'."
