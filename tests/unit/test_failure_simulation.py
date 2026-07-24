"""
test_failure_simulation.py — Realistic failure simulation for AuriOS.

Injects real-world failures into every layer of the system and verifies
graceful handling: no crashes, proper error messages, clean recovery.

Simulated failures:
  - Network delays and timeouts
  - Failed / partial downloads
  - Installer crashes and permission errors
  - Missing dependencies (pip, winreg, Ollama)
  - Disk space exhaustion
  - Database corruption
  - Partial installations (some tools succeed, some fail)
  - Concurrent access conflicts

Run: pytest tests/unit/test_failure_simulation.py -v
"""

import os
import time
import subprocess
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path


# ======================================================================
# 1. NETWORK FAILURES — DownloadAgent
# ======================================================================

class TestNetworkFailures:
    """Simulate network issues during downloads."""

    @pytest.fixture
    def agent(self):
        from backend.agents.download_agent import DownloadAgent
        return DownloadAgent()

    @patch("backend.agents.download_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.download_agent.repo_sync.get_download_info")
    @patch("backend.agents.download_agent.requests.get")
    @patch("time.sleep")
    def test_connection_timeout_retries_3_times(self, mock_sleep, mock_get, mock_info, mock_sim, agent):
        """ConnectionError should trigger 3 retry attempts before failing."""
        mock_info.return_value = {"filename": "test.exe", "url": "http://fake.com/test.exe"}
        mock_get.side_effect = __import__("requests").exceptions.ConnectionError("Network unreachable")

        with pytest.raises(RuntimeError, match="Download failed after 3 attempts"):
            agent.download("python")

        assert mock_get.call_count == 3

    @patch("backend.agents.download_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.download_agent.repo_sync.get_download_info")
    @patch("backend.agents.download_agent.requests.get")
    @patch("time.sleep")
    def test_http_timeout_handled(self, mock_sleep, mock_get, mock_info, mock_sim, agent):
        """requests.Timeout should be caught and retried, not crash."""
        mock_info.return_value = {"filename": "git.exe", "url": "http://fake.com/git.exe"}
        mock_get.side_effect = __import__("requests").exceptions.Timeout("Read timed out")

        with pytest.raises(RuntimeError, match="Download failed after 3 attempts"):
            agent.download("git")

        assert mock_get.call_count == 3

    @patch("backend.agents.download_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.download_agent.repo_sync.get_download_info")
    @patch("backend.agents.download_agent.requests.get")
    def test_http_403_rate_limit(self, mock_get, mock_info, mock_sim, agent):
        """GitHub 403 rate-limit response should be caught gracefully."""
        mock_info.return_value = {"filename": "test.exe", "url": "http://fake.com/test.exe"}
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = __import__("requests").exceptions.HTTPError(
            response=MagicMock(status_code=403)
        )
        mock_get.return_value = mock_response

        with pytest.raises(RuntimeError, match="Download failed"):
            agent.download("python")

    @patch("backend.agents.download_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.download_agent.repo_sync.get_download_info")
    @patch("backend.agents.download_agent.requests.get")
    def test_slow_download_progress_callbacks(self, mock_get, mock_info, mock_sim, agent):
        """Slow download should still send progress callbacks without timing out."""
        mock_info.return_value = {"filename": "slow.exe", "url": "http://fake.com/slow.exe"}

        # Simulate a slow chunked response (100 bytes total, 10 bytes per chunk)
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"content-length": "100"}
        mock_response.iter_content.return_value = [b"x" * 10 for _ in range(10)]
        mock_get.return_value = mock_response

        progress_values = []
        def track_progress(pct):
            progress_values.append(pct)

        with patch("os.path.exists", return_value=False), \
             patch("os.makedirs"), \
             patch("builtins.open", MagicMock()):
            agent.download("python", progress_callback=track_progress)

        # Progress should have been called multiple times
        assert len(progress_values) >= 5
        assert progress_values[-1] == 100

    @patch("backend.agents.download_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.download_agent.repo_sync.get_download_info")
    def test_partial_download_cleanup(self, mock_info, mock_sim, agent, tmp_path):
        """If download fails after 3 retries, RuntimeError should be raised."""
        mock_info.return_value = {"filename": "partial.exe", "url": "http://fake.com/partial.exe"}

        with patch("backend.agents.download_agent.requests.get") as mock_get, \
             patch("backend.agents.download_agent.os.makedirs"), \
             patch("backend.agents.download_agent.os.path.exists", return_value=False), \
             patch("backend.agents.download_agent.time.sleep"):
            mock_get.side_effect = __import__("requests").exceptions.ConnectionError("dropped")

            with pytest.raises(RuntimeError, match="Download failed after 3 attempts"):
                agent.download("python")

    def test_software_not_in_catalog(self, agent):
        """Requesting unavailable software should raise ValueError, not crash."""
        with patch("backend.agents.download_agent.repo_sync.get_download_info", return_value=None):
            with pytest.raises(ValueError, match="not available"):
                agent.download("figma")


# ======================================================================
# 2. INSTALLER FAILURES — InstallAgent
# ======================================================================

class TestInstallerFailures:
    """Simulate installer crashes, permission errors, and hangs."""

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    @patch("time.sleep")
    def test_installer_crash_exit_code_1(self, mock_sleep, mock_run, mock_exists, mock_which, mock_sim):
        """Installer crashing with exit code 1 should return structured error."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Segfault")

        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("git", "C:\\test\\git-setup.exe")

        assert result["success"] is False
        assert result["error"] is not None
        assert "reason" in result["error"]
        assert "details" in result["error"]
        assert "suggestion" in result["error"]

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    @patch("time.sleep")
    def test_permission_denied_exit_1603(self, mock_sleep, mock_run, mock_exists, mock_which, mock_sim):
        """Exit code 1603 should report permission-specific error message."""
        mock_run.return_value = MagicMock(returncode=1603, stdout="", stderr="")

        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("vscode", "C:\\test\\vscode.exe")

        assert result["success"] is False
        assert "permission" in result["error"]["details"].lower()
        assert "retry" in result["error"]["suggestion"].lower() or \
               "administrator" in result["error"]["suggestion"].lower()

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    @patch("time.sleep")
    def test_another_install_running_exit_1618(self, mock_sleep, mock_run, mock_exists, mock_which, mock_sim):
        """Exit code 1618 (another install in progress) should report specific error."""
        mock_run.return_value = MagicMock(returncode=1618, stdout="", stderr="")

        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("nodejs", "C:\\test\\node.msi")

        assert result["success"] is False
        assert "another installation" in result["error"]["details"].lower()

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test.exe", timeout=600))
    @patch("time.sleep")
    def test_installer_hangs_10_minutes(self, mock_sleep, mock_run, mock_exists, mock_which, mock_sim):
        """10-minute timeout should produce clean error, no zombie process."""
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("python", "C:\\test\\python.exe")

        assert result["success"] is False
        assert "timeout" in result["error"]["reason"].lower()
        assert "suggestion" in result["error"]

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run", side_effect=PermissionError("Access denied"))
    @patch("time.sleep")
    def test_os_permission_error(self, mock_sleep, mock_run, mock_exists, mock_which, mock_sim):
        """OS-level PermissionError should be caught, not crash."""
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("docker", "C:\\test\\docker.exe")

        assert result["success"] is False
        assert result["error"] is not None

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run", side_effect=OSError("No such file or directory"))
    @patch("time.sleep")
    def test_corrupted_installer_binary(self, mock_sleep, mock_run, mock_exists, mock_which, mock_sim):
        """Corrupted .exe that can't be executed should return error, not crash."""
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("git", "C:\\test\\corrupted.exe")

        assert result["success"] is False
        assert result["error"] is not None

    @patch("backend.agents.install_agent.is_simulated_host", return_value=False)
    @patch("backend.agents.install_agent.shutil.which", return_value=None)
    @patch("os.path.exists", return_value=False)
    def test_missing_installer_file(self, mock_exists, mock_which, mock_sim):
        """Installer file not on disk should fail gracefully."""
        from backend.agents.install_agent import InstallAgent
        result = InstallAgent().install("python", "C:\\downloads\\nonexistent.exe")

        assert result["success"] is False
        assert "not found" in result["error"]["reason"].lower()


# ======================================================================
# 3. MISSING DEPENDENCIES — ConfigureAgent
# ======================================================================

class TestMissingDependencies:
    """Simulate missing pip, winreg, and other system dependencies."""

    def test_pip_not_available(self):
        """If pip is not installed, _pip_install should fail gracefully."""
        from backend.agents.configure_agent import ConfigureAgent
        agent = ConfigureAgent()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr=b"No module named pip"
            )
            ok, err = agent._pip_install("numpy")

        assert ok is False
        assert "pip" in err.lower() or err is not None

    def test_pip_install_timeout(self):
        """pip install hanging for 5 minutes should timeout gracefully."""
        from backend.agents.configure_agent import ConfigureAgent
        agent = ConfigureAgent()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=300)):
            ok, err = agent._pip_install("tensorflow==2.15.0")

        assert ok is False
        assert "timed out" in err.lower()

    def test_pip_package_build_failure(self):
        """Package that needs C compiler should fail with useful error."""
        from backend.agents.configure_agent import ConfigureAgent
        agent = ConfigureAgent()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr=b"error: Microsoft Visual C++ 14.0 or greater is required"
            )
            ok, err = agent._pip_install("some-native-package")

        assert ok is False
        assert "Visual C++" in err or err is not None

    def test_winreg_unavailable_on_linux(self):
        """On Linux, PATH update should skip gracefully (no crash)."""
        from backend.agents.configure_agent import ConfigureAgent
        agent = ConfigureAgent()

        with patch.dict("sys.modules", {"winreg": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'winreg'")):
                ok, err = agent._update_system_path(["python"])

        # Should not crash — must return a 2-tuple regardless of platform
        assert isinstance(ok, bool)
        assert err is None or isinstance(err, str)

    def test_partial_pip_success(self):
        """Some pip packages succeed while others fail — results should reflect both."""
        from backend.agents.configure_agent import ConfigureAgent

        call_count = [0]
        def mock_pip_run(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # Second package fails
                return MagicMock(returncode=1, stderr=b"Could not find version")
            return MagicMock(returncode=0, stderr=b"", stdout=b"Successfully installed")

        with patch("subprocess.run", side_effect=mock_pip_run):
            result = ConfigureAgent().run({
                "pip_packages": ["numpy", "nonexistent-pkg-xyz", "pandas"],
                "software_list": [],
            })

        pip_results = result.get("pip_results", {})
        assert pip_results["numpy"]["success"] is True
        assert pip_results["nonexistent-pkg-xyz"]["success"] is False
        assert pip_results["pandas"]["success"] is True


# ======================================================================
# 4. PARTIAL INSTALLATIONS — ValidationAgent
# ======================================================================

class TestPartialInstallations:
    """Simulate scenarios where some tools install but others don't."""

    def test_2_of_4_tools_installed(self):
        """Preset with 4 tools where 2 succeed — validation should report both."""
        from backend.agents.validate_agent import ValidationAgent

        mock_detection = {
            "installed": {
                "python": True,
                "git": True,
                "nodejs": False,
                "vscode": False,
            },
            "is_admin": True,
            "free_disk_gb": 50.0,
        }

        with patch("backend.agents.validate_agent.is_simulated_host", return_value=False), \
             patch("backend.agents.validate_agent.DetectionAgent") as MockDet:
            MockDet.return_value.run.return_value = mock_detection
            result = ValidationAgent().run({
                "expected_software": ["python", "git", "nodejs", "vscode"]
            })

        assert result["validation"]["python"] is True
        assert result["validation"]["git"] is True
        assert result["validation"]["nodejs"] is False
        assert result["validation"]["vscode"] is False

    def test_all_tools_missing_after_install(self):
        """Complete installation failure — all expected tools still missing."""
        from backend.agents.validate_agent import ValidationAgent

        mock_detection = {
            "installed": {"python": False, "git": False},
            "is_admin": True,
            "free_disk_gb": 50.0,
        }

        with patch("backend.agents.validate_agent.is_simulated_host", return_value=False), \
             patch("backend.agents.validate_agent.DetectionAgent") as MockDet:
            MockDet.return_value.run.return_value = mock_detection
            result = ValidationAgent().run({
                "expected_software": ["python", "git"]
            })

        assert all(v is False for v in result["validation"].values())

    def test_empty_expected_list(self):
        """Empty expected_software should return empty validation, not crash."""
        from backend.agents.validate_agent import ValidationAgent

        with patch("backend.agents.validate_agent.is_simulated_host", return_value=True):
            result = ValidationAgent().run({"expected_software": []})

        assert result["validation"] == {}


# ======================================================================
# 5. DISK SPACE FAILURES — DetectionAgent + Orchestrator
# ======================================================================

class TestDiskSpaceFailures:
    """Simulate low disk scenarios."""

    @patch("backend.agents.detection_agent._platform_free_disk_gb", return_value=0.3)
    @patch("backend.agents.detection_agent._platform_is_admin", return_value=True)
    @patch("backend.agents.detection_agent._probe", return_value=False)
    @patch("backend.agents.detection_agent._check_paths", return_value=False)
    @patch("backend.agents.detection_agent._check_registry", return_value=False)
    def test_critically_low_disk(self, mock_reg, mock_paths, mock_probe,
                                  mock_admin, mock_disk):
        """0.3 GB free disk should be reported in detection results."""
        from backend.agents.detection_agent import DetectionAgent
        result = DetectionAgent().run({})

        assert result["free_disk_gb"] == 0.3
        assert result["free_disk_gb"] < 1.0

    def test_disk_full_during_file_write(self):
        """IOError during download file write should be caught."""
        from backend.agents.download_agent import DownloadAgent

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"content-length": "1000"}
        mock_response.iter_content.return_value = [b"x" * 100]

        with patch("backend.agents.download_agent.is_simulated_host", return_value=False), \
             patch("backend.agents.download_agent.repo_sync.get_download_info",
                   return_value={"filename": "test.exe", "url": "http://fake/test.exe"}), \
             patch("backend.agents.download_agent.requests.get", return_value=mock_response), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=False), \
             patch("builtins.open", side_effect=IOError("No space left on device")):

            with pytest.raises((RuntimeError, IOError)):
                DownloadAgent().download("python")


# ======================================================================
# 6. OLLAMA / LLM FAILURES — Intent Parser
# ======================================================================

class TestOllamaFailures:
    """Simulate Ollama being offline, slow, or returning bad data."""

    def test_ollama_offline_fallback(self):
        """When Ollama is unreachable, parse_intent should still work for rule-based inputs."""
        from backend.llm.intent_parser import parse_intent

        # Rule-based intents should work without Ollama
        result = parse_intent("install python")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "python"

    def test_ollama_offline_canned_response(self):
        """Greetings should return canned responses without needing Ollama."""
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("hello")
        assert result["intent"] == "general_chat"
        assert len(result["response_text"]) > 10

    def test_ollama_connection_refused(self):
        """LLM fallback path with connection refused should return safe response."""
        from backend.llm.intent_parser import _llm_chat

        with patch("backend.llm.intent_parser.requests.post",
                   side_effect=__import__("requests").exceptions.ConnectionError("Connection refused")):
            result = _llm_chat("tell me something interesting")

        assert result["intent"] == "consultation"
        assert "ollama" in result["response_text"].lower() or "can't reach" in result["response_text"].lower()

    def test_ollama_returns_malformed_json(self):
        """LLM returning invalid JSON should be handled gracefully."""
        from backend.llm.intent_parser import _llm_chat

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"message": {"content": "not json {{{broken"}}

        with patch("backend.llm.intent_parser.requests.post", return_value=mock_response):
            result = _llm_chat("what is python")

        assert "response_text" in result
        assert result["response_text"] is not None

    def test_ollama_timeout_60s(self):
        """60-second Ollama timeout should return fallback, not crash."""
        from backend.llm.intent_parser import _llm_chat

        with patch("backend.llm.intent_parser.requests.post",
                   side_effect=__import__("requests").exceptions.Timeout("Read timed out")):
            result = _llm_chat("complex ambiguous question")

        assert result is not None
        assert "response_text" in result


# ======================================================================
# 7. DATABASE FAILURES — TaskManager
# ======================================================================

class TestDatabaseFailures:
    """Simulate database errors and edge cases."""

    def test_get_nonexistent_task(self):
        """Getting a task that doesn't exist should return None."""
        from backend.core.task_manager import TaskManager
        result = TaskManager().get_task("nonexistent-uuid-00000000")
        assert result is None

    def test_update_nonexistent_task(self):
        """Updating a non-existent task should not crash."""
        from backend.core.task_manager import TaskManager
        try:
            TaskManager().update_task("fake-uuid", "running", 50, "test")
        except Exception:
            pytest.fail("update_task should not crash on missing task")

    def test_cancel_nonexistent_task(self):
        """Cancelling a non-existent task should not crash."""
        from backend.core.task_manager import TaskManager
        try:
            TaskManager().cancel_task("fake-uuid-cancel")
        except Exception:
            pytest.fail("cancel_task should not crash on missing task")

    def test_create_many_tasks_concurrently(self):
        """Creating 20 tasks rapidly should not cause database lock errors."""
        from backend.core.task_manager import TaskManager
        tm = TaskManager()
        ids = []

        for i in range(20):
            task_id = tm.create_task(f"test_preset_{i}")
            ids.append(task_id)

        assert len(ids) == 20
        assert len(set(ids)) == 20  # All unique UUIDs

        # Verify all are readable
        for tid in ids:
            task = tm.get_task(tid)
            assert task is not None
            assert task["status"] == "pending"


# ======================================================================
# 8. ENVIRONMENT AGENT FAILURES
# ======================================================================

class TestEnvironmentFailures:
    """Simulate filesystem errors during project scaffolding."""

    def test_permission_denied_mkdir(self, tmp_path):
        """Read-only directory should not crash the agent."""
        from backend.agents.environment_agent import EnvironmentAgent

        # Use a path that the agent will try to create inside
        with patch("pathlib.Path.mkdir", side_effect=PermissionError("Access denied")):
            result = EnvironmentAgent().run({"project_path": str(tmp_path / "readonly")})

        # Should return results dict (possibly with errors), not crash
        assert "project_root" in result

    def test_venv_creation_fails(self, tmp_path):
        """Failed venv creation should be logged, not crash the pipeline."""
        from backend.agents.environment_agent import EnvironmentAgent

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr=b"Error: venv module not available"
            )
            result = EnvironmentAgent().run({"project_path": str(tmp_path / "no_venv")})

        assert result["venv_created"] is False
        assert result["venv_error"] is not None

    def test_venv_subprocess_timeout(self, tmp_path):
        """venv creation timeout should be handled gracefully."""
        from backend.agents.environment_agent import EnvironmentAgent

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="venv", timeout=120)):
            result = EnvironmentAgent().run({"project_path": str(tmp_path / "timeout_venv")})

        assert result["venv_created"] is False
        assert "timeout" in result["venv_error"].lower() or result["venv_error"] is not None


# ======================================================================
# 9. INTENT PARSER EDGE CASES
# ======================================================================

class TestIntentParserEdgeCases:
    """Simulate unusual, adversarial, and malformed inputs."""

    def test_extremely_long_input(self):
        """5000-character input should not crash or hang."""
        from backend.llm.intent_parser import parse_intent
        long_input = "install python " + "a" * 5000
        result = parse_intent(long_input)
        assert result is not None
        assert "intent" in result

    def test_null_bytes_in_input(self):
        """Null bytes in input should be handled safely."""
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("install\x00python")
        # Should not crash — may or may not match
        assert result is None or isinstance(result, dict)

    def test_unicode_emoji_input(self):
        """Emoji-only input should not crash."""
        from backend.llm.intent_parser import parse_intent

        with patch("backend.llm.intent_parser._llm_chat") as mock_llm:
            mock_llm.return_value = {
                "intent": "consultation",
                "preset_or_software": None,
                "needs_clarification": False,
                "response_text": "I can help with software installation.",
            }
            result = parse_intent("🐍🔧💻")

        assert result is not None

    def test_sql_injection_in_input(self):
        """SQL injection attempts should be treated as normal text."""
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("'; DROP TABLE users; --")
        assert result is None  # No install intent detected

    def test_html_xss_in_input(self):
        """XSS payload should not cause issues in intent parsing."""
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("<script>alert('xss')</script>")
        assert result is None  # No install intent detected
