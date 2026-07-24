"""
test_detection.py — Unit tests for DetectionAgent.

Tests the agent's ability to correctly identify installed software
using mocked system calls (shutil.which, subprocess.run, winreg).
All tests run on any OS — Windows-specific calls are fully mocked.

Run: pytest tests/unit/test_detection.py -v
"""

import pytest
from unittest.mock import patch, MagicMock


class TestProbeFunction:
    """Tests for the module-level _probe() helper."""

    @patch("backend.agents.detection_agent.subprocess.run")
    @patch("backend.agents.detection_agent.shutil.which", return_value="/usr/bin/python")
    def test_probe_returns_true_on_zero_exit(self, mock_which, mock_run):
        """Tool found on PATH + exit code 0 → True."""
        mock_run.return_value = MagicMock(returncode=0)
        from backend.agents.detection_agent import _probe
        assert _probe(["python", "--version"]) is True

    @patch("backend.agents.detection_agent.shutil.which", return_value=None)
    def test_probe_returns_false_when_not_on_path(self, mock_which):
        """Tool not on PATH → False (subprocess never called)."""
        from backend.agents.detection_agent import _probe
        assert _probe(["python", "--version"]) is False

    @patch("backend.agents.detection_agent.subprocess.run", side_effect=FileNotFoundError)
    @patch("backend.agents.detection_agent.shutil.which", return_value="/usr/bin/python")
    def test_probe_handles_file_not_found(self, mock_which, mock_run):
        """FileNotFoundError during subprocess → False (no crash)."""
        from backend.agents.detection_agent import _probe
        assert _probe(["python", "--version"]) is False

    @patch("backend.agents.detection_agent.subprocess.run",
           side_effect=__import__("subprocess").TimeoutExpired(cmd="git", timeout=10))
    @patch("backend.agents.detection_agent.shutil.which", return_value="/usr/bin/git")
    def test_probe_handles_timeout(self, mock_which, mock_run):
        """Subprocess timeout → False (tool exists but is hung)."""
        from backend.agents.detection_agent import _probe
        assert _probe(["git", "--version"]) is False

    @patch("backend.agents.detection_agent.subprocess.run")
    @patch("backend.agents.detection_agent.shutil.which", return_value="/usr/bin/docker")
    def test_probe_returns_false_on_nonzero_exit(self, mock_which, mock_run):
        """Non-zero exit code → False (binary exists but broken)."""
        mock_run.return_value = MagicMock(returncode=1)
        from backend.agents.detection_agent import _probe
        assert _probe(["docker", "--version"]) is False


class TestDetectionAgentRun:
    """Tests for DetectionAgent.run() end-to-end with mocked OS calls."""

    @patch("backend.agents.detection_agent._platform_free_disk_gb", return_value=120.5)
    @patch("backend.agents.detection_agent._platform_is_admin", return_value=True)
    @patch("backend.agents.detection_agent._check_registry", return_value=False)
    @patch("backend.agents.detection_agent._check_paths", return_value=False)
    @patch("backend.agents.detection_agent._probe")
    def test_detects_python_and_git_on_path(self, mock_probe, mock_paths,
                                             mock_reg, mock_admin, mock_disk):
        """When python and git return exit 0, both should be True in result."""
        def probe_side_effect(cmd):
            return cmd[0] in ("python", "git")
        mock_probe.side_effect = probe_side_effect

        from backend.agents.detection_agent import DetectionAgent
        result = DetectionAgent().run({})

        assert result["installed"]["python"] is True
        assert result["installed"]["git"] is True
        assert result["installed"]["docker"] is False
        assert result["is_admin"] is True
        assert result["free_disk_gb"] == 120.5

    @patch("backend.agents.detection_agent._platform_free_disk_gb", return_value=0.3)
    @patch("backend.agents.detection_agent._platform_is_admin", return_value=False)
    @patch("backend.agents.detection_agent._check_registry", return_value=False)
    @patch("backend.agents.detection_agent._check_paths", return_value=False)
    @patch("backend.agents.detection_agent.os.path.isfile", return_value=False)
    @patch("backend.agents.detection_agent.shutil.which", return_value=None)
    @patch("backend.agents.detection_agent._probe", return_value=False)
    def test_nothing_installed_low_disk_no_admin(self, mock_probe, mock_which,
                                                  mock_isfile, mock_paths,
                                                  mock_reg, mock_admin, mock_disk):
        """Edge case: no tools, no admin, critically low disk."""
        from backend.agents.detection_agent import DetectionAgent
        result = DetectionAgent().run({})

        assert all(v is False for v in result["installed"].values())
        assert result["is_admin"] is False
        assert result["free_disk_gb"] < 1.0

    @patch("backend.agents.detection_agent._platform_free_disk_gb", return_value=50.0)
    @patch("backend.agents.detection_agent._platform_is_admin", return_value=True)
    @patch("backend.agents.detection_agent._check_registry", return_value=False)
    @patch("backend.agents.detection_agent._check_paths")
    @patch("backend.agents.detection_agent._probe", return_value=False)
    def test_vscode_detected_via_file_path_fallback(self, mock_probe, mock_paths,
                                                     mock_reg, mock_admin, mock_disk):
        """VS Code not on PATH but found at known file path → True."""
        def paths_side_effect(slug):
            return slug == "vscode"
        mock_paths.side_effect = paths_side_effect

        from backend.agents.detection_agent import DetectionAgent
        result = DetectionAgent().run({})

        assert result["installed"]["vscode"] is True

    @patch("backend.agents.detection_agent._platform_free_disk_gb", return_value=50.0)
    @patch("backend.agents.detection_agent._platform_is_admin", return_value=True)
    @patch("backend.agents.detection_agent._check_registry")
    @patch("backend.agents.detection_agent._check_paths", return_value=False)
    @patch("backend.agents.detection_agent._probe", return_value=False)
    def test_registry_fallback_for_gui_apps(self, mock_probe, mock_paths,
                                             mock_reg, mock_admin, mock_disk):
        """GUI app found via registry when not on PATH or file paths."""
        def reg_side_effect(slug):
            return slug == "vlc"
        mock_reg.side_effect = reg_side_effect

        from backend.agents.detection_agent import DetectionAgent
        result = DetectionAgent().run({})

        assert result["installed"]["vlc"] is True

    @patch("backend.agents.detection_agent._platform_free_disk_gb", return_value=50.0)
    @patch("backend.agents.detection_agent._platform_is_admin", return_value=True)
    @patch("backend.agents.detection_agent._check_registry", return_value=False)
    @patch("backend.agents.detection_agent._check_paths", return_value=False)
    @patch("backend.agents.detection_agent._probe", return_value=False)
    @patch("backend.agents.detection_agent.shutil.which", return_value="/usr/bin/python3")
    def test_python3_fallback_on_linux(self, mock_which, mock_probe, mock_paths,
                                       mock_reg, mock_admin, mock_disk):
        """On Linux, `python3` on PATH should count as python=True."""
        from backend.agents.detection_agent import DetectionAgent
        result = DetectionAgent().run({})

        assert result["installed"]["python"] is True

    def test_result_has_required_keys(self):
        """run() must always return installed, is_admin, free_disk_gb."""
        with patch("backend.agents.detection_agent._probe", return_value=False), \
             patch("backend.agents.detection_agent._check_paths", return_value=False), \
             patch("backend.agents.detection_agent._check_registry", return_value=False), \
             patch("backend.agents.detection_agent._platform_is_admin", return_value=False), \
             patch("backend.agents.detection_agent._platform_free_disk_gb", return_value=10.0):
            from backend.agents.detection_agent import DetectionAgent
            result = DetectionAgent().run({})
            assert "installed" in result
            assert "is_admin" in result
            assert "free_disk_gb" in result
            assert isinstance(result["installed"], dict)
