import os
import pytest
import subprocess
from unittest.mock import MagicMock
from src.agents.configure_agent import run_configuration, DEFAULT_INSTALL_BASE

# NOTE: Since the agent code relies on os.name == 'nt', these tests must
# be run on a Windows CI runner (which is now configured in ci.yml).

def test_configuration_success(mocker):
    """Tests the happy path where path modification succeeds."""
    software_name = "test_tool"
    test_path = os.path.join(DEFAULT_INSTALL_BASE, software_name)

    # 1. Mock subprocess.run for setx command
    mock_run = mocker.patch('subprocess.run')
    # Simulate success (return code 0)
    mock_run.return_value = MagicMock(returncode=0, stdout="SUCCESS", stderr="")
    
    # 2. Mock os.path.isdir to simulate finding the installed software folder
    mocker.patch('os.path.isdir', return_value=True) 
    
    # 3. Mock os.name to ensure Windows logic is executed during the test
    mocker.patch('os.name', 'nt')

    # 4. Execute the function
    result = run_configuration(software_name)

    # 5. Assertions (Verification)
    assert "SUCCESS" in result
    assert "configured" in result
    
    # Verify that the correct setx command was attempted
    expected_command = f'setx PATH "%PATH%;{test_path}"'
    
    # We check if subprocess.run was called with the expected command list (shell=True means it's a single string command)
    mock_run.assert_called_once_with(
        expected_command, 
        shell=True, 
        check=True, 
        capture_output=True, 
        text=True
    )

def test_configuration_setx_failure(mocker):
    """Tests the failure path when setx fails for a non-permission reason."""
    software_name = "fail_tool"
    test_path = os.path.join(DEFAULT_INSTALL_BASE, software_name)

    # 1. Mock subprocess.run to simulate failure (e.g., path too long, error code 1)
    mocker.patch('subprocess.run', side_effect=subprocess.CalledProcessError(
        returncode=1, cmd=['setx'], stderr=b"ERROR: Path variable too long."
    ))
    
    # 2. Mock os.path.isdir
    mocker.patch('os.path.isdir', return_value=True) 
    
    # 3. Mock os.name
    mocker.patch('os.name', 'nt')

    # 4. Execute the function
    result = run_configuration(software_name)

    # 5. Assertion
    assert "FAILURE" in result
    assert "Configuration failed" in result
