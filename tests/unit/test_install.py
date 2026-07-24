"""
test_install.py — Unit tests for InstallAgent.

Tests the install() method: winget/choco fallback chain, custom silent
flags, exit code handling, timeout, file-not-found, and simulation mode.
All subprocess calls are mocked — no real installations occur.

Run: pytest tests/unit/test_install.py -v
"""

import os
import pytest
import subprocess
from unittest.mock import patch, MagicMock


@pytest.fixture
def agent():
    """Fresh InstallAgent instance for each test."""
    from backend.agents.install_agent import InstallAgent
    return InstallAgent()


class TestSimulationMode:
    """When AURIOS_SIMULATE_INSTALL=1, nothing should actually run."""

    @patch.dict(os.environ, {"AURIOS_SIMULATE_INSTALL": "1"})
    def test_simulation_returns_success(self, agent):
        """In simulation mode, install() returns success without calling subprocess."""
        with patch("subprocess.run") as mock_run:
            result = agent.install("python", "C:\\downloads\\python-3.12.exe")
            assert result["success"] is True
            assert result["error"] is None
            mock_run.assert_not_called()


class TestLocalInstallerFallback:
    """Tests for the local .exe/.msi installer path (when winget/choco unavailable)."""

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)  # No winget/choco
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_exe_exit_code_0_is_success(self, mock_run, mock_exists, mock_which, mock_sim):
        """Exit code 0 from local .exe → success."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("git", "C:\\downloads\\Git-2.43.0-64-bit.exe")
        assert result["success"] is True
        assert result["error"] is None

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_exit_code_3010_is_success(self, mock_run, mock_exists, mock_which, mock_sim):
        """Exit code 3010 (reboot required) should still be treated as success."""
        mock_run.return_value = MagicMock(returncode=3010, stdout="", stderr="")
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("nodejs", "C:\\downloads\\node-v20.10.0-x64.msi")
        assert result["success"] is True

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_exit_code_1_is_failure(self, mock_run, mock_exists, mock_which, mock_sim):
        """Non-zero exit code (not 3010) → failure with parsed error."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Something broke")
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("git", "C:\\downloads\\git-setup.exe")
        assert result["success"] is False
        assert result["error"] is not None
        assert "reason" in result["error"]

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_exit_code_1603_permission_error(self, mock_run, mock_exists, mock_which, mock_sim):
        """Exit code 1603 should produce a permission-specific error message."""
        mock_run.return_value = MagicMock(returncode=1603, stdout="", stderr="")
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("vscode", "C:\\downloads\\VSCodeSetup.exe")
        assert result["success"] is False
        assert "permission" in result["error"]["details"].lower()

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=600))
    def test_timeout_after_10_minutes(self, mock_run, mock_exists, mock_which, mock_sim):
        """10-minute timeout should be caught and reported cleanly."""
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("python", "C:\\downloads\\python-setup.exe")
        assert result["success"] is False
        assert "timeout" in result["error"]["reason"].lower()

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=False)
    def test_missing_installer_file(self, mock_exists, mock_which, mock_sim):
        """Non-existent installer file → failure with 'File not found'."""
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("git", "C:\\downloads\\nonexistent.exe")
        assert result["success"] is False
        assert "not found" in result["error"]["reason"].lower()

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_msi_uses_msiexec(self, mock_run, mock_exists, mock_which, mock_sim):
        """MSI files should be installed via msiexec /i."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        from backend.agents.install_agent import InstallAgent
        InstallAgent().install("nodejs", "C:\\downloads\\node-v20.10.0-x64.msi")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "msiexec.exe"
        assert "/i" in cmd

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_custom_flags_for_python(self, mock_run, mock_exists, mock_which, mock_sim):
        """Python installer should use custom flags: /quiet InstallAllUsers=1 PrependPath=1."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        from backend.agents.install_agent import InstallAgent
        InstallAgent().install("python", "C:\\downloads\\python-3.11.7-amd64.exe")
        cmd = mock_run.call_args[0][0]
        assert "/quiet" in cmd
        assert "PrependPath=1" in cmd


class TestCustomFlagLookup:
    """Verify CUSTOM_FLAGS and SILENT_FLAGS dictionaries."""

    def test_python_has_custom_flags(self):
        from backend.agents.install_agent import CUSTOM_FLAGS
        assert "python-3.11.7-amd64.exe" in CUSTOM_FLAGS
        flags = CUSTOM_FLAGS["python-3.11.7-amd64.exe"]
        assert "/quiet" in flags

    def test_git_has_custom_flags(self):
        from backend.agents.install_agent import CUSTOM_FLAGS
        assert "Git-2.43.0-64-bit.exe" in CUSTOM_FLAGS
        flags = CUSTOM_FLAGS["Git-2.43.0-64-bit.exe"]
        assert "/VERYSILENT" in flags

    def test_default_exe_flags_exist(self):
        from backend.agents.install_agent import SILENT_FLAGS
        assert ".exe" in SILENT_FLAGS
        assert ".msi" in SILENT_FLAGS
