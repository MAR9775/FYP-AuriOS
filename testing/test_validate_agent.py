import os
import pytest
import subprocess
from unittest.mock import MagicMock
from src.agents.validate_agent import run_validation

# NOTE: Tests assume os.name == 'nt' for Windows environment, 
# which is enforced by the CI runner configuration.

@pytest.fixture(autouse=True)
def mock_os_name(mocker):
    """Ensure os.name is mocked to 'nt' (Windows) for all tests in this file."""
    mocker.patch('os.name', 'nt')

def test_validation_coding_success(mocker):
    """Tests the happy path where coding software validation succeeds."""
    software_name = "python"

    # 1. Mock subprocess.run for 'where.exe' (locates executable)
    mock_where = mocker.patch('subprocess.run')
    # First call (where.exe): Returns path to executable
    mock_where.side_effect = [
        MagicMock(returncode=0, stdout="C:\\Python\\python.exe\n", stderr=""),
        # Second call (python.exe test_script.py): Returns success output
        MagicMock(returncode=0, stdout="Hello World! python validation successful.", stderr=""),
    ]
    
    # 2. Mock file operations (open) used to create/delete the test script
    mocker.patch('builtins.open', mocker.mock_open())
    mocker.patch('os.remove') # Mock file cleanup

    # 3. Execute the function
    result = run_validation(software_name, software_type='coding')

    # 4. Assertions
    assert "SUCCESS" in result
    assert "Hello World!" in result
    
    # Verify that 'where.exe' was called correctly
    mock_where.call_args_list[0].assert_called_with(
        ['where.exe', software_name], capture_output=True, text=True, check=True
    )

def test_validation_app_success(mocker):
    """Tests the happy path where application launch succeeds."""
    software_name = "notepad.exe"
    
    # 1. Mock subprocess.run for 'where.exe'
    mocker.patch('subprocess.run', 
                 return_value=MagicMock(returncode=0, stdout=f"C:\\Windows\\{software_name}\n", stderr=""))

    # 2. Mock subprocess.Popen for 'start' (launches app)
    mock_popen = mocker.patch('subprocess.Popen')

    # 3. Execute the function
    result = run_validation(software_name, software_type='app')

    # 4. Assertions
    assert "SUCCESS" in result
    assert "Application launch command sent" in result
    
    # Verify that the Windows 'start' command was attempted
    mock_popen.assert_called_once_with(
        ['start', '""', software_name], shell=True
    )


def test_validation_executable_not_found(mocker):
    """Tests the path where the executable is not in the system PATH."""
    software_name = "nonexistent_exe"

    # Mock subprocess.run for 'where.exe' to simulate failure
    mocker.patch('subprocess.run', side_effect=subprocess.CalledProcessError(
        returncode=1, cmd=['where.exe'], stderr="Could not find files."
    ))

    # Execute the function
    result = run_validation(software_name, software_type='coding')

    # Assertion
    assert "FAILURE" in result
    assert "not found in PATH" in result
