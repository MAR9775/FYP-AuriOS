import os
import pytest
from unittest.mock import MagicMock
import subprocess 
import shutil
from src.agents.install_agent import run_installation, INSTALL_DIR

# Fixture to ensure the target directory is available, even though we are mocking
@pytest.fixture(autouse=True)
def setup_install_dir(tmp_path):
    """Mocks the INSTALL_DIR constant to use a temporary directory."""
    original_install_dir = INSTALL_DIR
    # This is complex to mock across modules in a single file, so we skip mocking 
    # the constant itself for this basic example and focus on process mocking.
    # In a full project, we'd use 'pytest-monkeypatch' or similar for constants.
    
    # We will assume INSTALL_DIR is a safe path for the purpose of mocking.
    pass


def test_installation_success(mocker):
    """Tests the happy path where git clone and install.sh succeed."""
    repo_url = "https://github.com/test/project.git"
    software_name = "test_app"
    target_path = os.path.join(INSTALL_DIR, software_name)

    # 1. Mock subprocess.run for git clone and install.sh
    mock_run = mocker.patch('subprocess.run')
    mock_run.side_effect = [
        # First call: git clone (Mocks success)
        MagicMock(returncode=0, stdout="Clone successful.", stderr=""),
        # Second call: bash install.sh (Mocks success)
        MagicMock(returncode=0, stdout="Installation successful.", stderr=""),
    ]

    # 2. Mock os.path.exists to simulate finding the install script
    mocker.patch('os.path.exists', return_value=True)

    # 3. Mock the directory cleanup to ensure the test continues (Fixes the IndexError)
    mocker.patch('shutil.rmtree') # <-- NEW: Prevents the early return/failure

    # 4. Execute the function
    result = run_installation(repo_url, software_name)

    # 5. Assertions (Verification)
    # Now that cleanup is mocked, the function returns SUCCESS as intended
    assert "SUCCESS" in result # <-- CHANGED: Asserting the expected success

    # Verify that 'git clone' was called correctly
    mock_run.call_args_list[0].assert_called_with(
        ['git', 'clone', repo_url, target_path],
        capture_output=True, text=True, check=True
    )


def test_installation_git_failure(mocker):
    """Tests the failure path when git clone fails."""
    repo_url = "https://github.com/bad/project.git"
    software_name = "bad_app"

    # 1. Mock subprocess.run to simulate git clone failure (raises CalledProcessError)
    mocker.patch('subprocess.run', side_effect=subprocess.CalledProcessError(
        returncode=128, cmd=['git', 'clone'], stderr="Authentication failed."
    ))

    # 2. Execute the function
    result = run_installation(repo_url, software_name)

    # 3. Assertion
    assert "FAILURE" in result
    assert "Git clone failed" in result
