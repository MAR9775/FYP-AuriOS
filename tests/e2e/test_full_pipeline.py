"""
test_full_pipeline.py — End-to-end tests for the TaskManager + pipeline flow.

Tests task lifecycle (create → update → get → cancel), progress tracking,
and final message persistence using the real TaskManager against the
actual SQLite database.

Run: pytest tests/e2e/test_full_pipeline.py -v
"""

import pytest
from backend.core.task_manager import TaskManager


@pytest.fixture
def tm():
    """Fresh TaskManager for each test."""
    return TaskManager()


class TestTaskLifecycle:
    """Test TaskManager CRUD operations."""

    def test_create_task_returns_uuid(self, tm):
        """create_task() should return a UUID string."""
        task_id = tm.create_task("python_basic")
        assert task_id is not None
        assert len(task_id) == 36  # UUID format: 8-4-4-4-12
        assert "-" in task_id

    def test_get_task_after_create(self, tm):
        """Newly created task should be pending with progress 0."""
        task_id = tm.create_task("git")
        task = tm.get_task(task_id)
        assert task is not None
        assert task["status"] == "pending"
        assert task["progress"] == 0
        assert task["preset"] == "git"

    def test_update_task_changes_state(self, tm):
        """update_task() should modify status, progress, and current_step."""
        task_id = tm.create_task("python_basic")
        tm.update_task(task_id, "running", 35, "download:running")
        task = tm.get_task(task_id)
        assert task["status"] == "running"
        assert task["progress"] == 35
        assert task["current_step"] == "download:running"

    def test_get_nonexistent_task_returns_none(self, tm):
        """get_task() with invalid ID should return None, not crash."""
        task = tm.get_task("nonexistent-uuid-12345")
        assert task is None

    def test_set_final_message(self, tm):
        """set_final_message() should persist and be readable."""
        task_id = tm.create_task("python_basic")
        msg = "Python is installed and ready! 🐍"
        tm.set_final_message(task_id, msg)
        task = tm.get_task(task_id)
        assert task["final_message"] == msg

    def test_cancel_task(self, tm):
        """cancel_task() should set status to 'cancelled'."""
        task_id = tm.create_task("full_stack")
        tm.cancel_task(task_id)
        task = tm.get_task(task_id)
        assert task["status"] == "cancelled"


class TestProgressSequence:
    """Simulate a realistic progress sequence through all pipeline stages."""

    def test_full_progress_sequence(self, tm):
        """Simulate the 7-stage pipeline progress updates."""
        task_id = tm.create_task("python_basic")

        stages = [
            ("running", 5,   "detection:running"),
            ("running", 15,  "detection:done"),
            ("running", 20,  "download:running"),
            ("running", 40,  "download:done"),
            ("running", 42,  "install:running"),
            ("running", 60,  "install:done"),
            ("running", 62,  "configure:running"),
            ("running", 75,  "configure:done"),
            ("running", 77,  "validate:running"),
            ("running", 90,  "validate:done"),
            ("running", 92,  "environment:running"),
            ("running", 100, "environment:done"),
            ("done",    100, "complete"),
        ]

        for status, progress, step in stages:
            tm.update_task(task_id, status, progress, step)
            task = tm.get_task(task_id)
            assert task["progress"] == progress
            assert task["status"] == status

        tm.set_final_message(task_id, "Python is installed and ready!")
        task = tm.get_task(task_id)
        assert task["status"] == "done"
        assert task["progress"] == 100
        assert task["final_message"] is not None

    def test_cancel_mid_pipeline(self, tm):
        """Cancel after download stage — status should be cancelled."""
        task_id = tm.create_task("git")
        tm.update_task(task_id, "running", 15, "detection:done")
        tm.update_task(task_id, "running", 35, "download:running")
        tm.cancel_task(task_id)

        task = tm.get_task(task_id)
        assert task["status"] == "cancelled"

    def test_multiple_tasks_independent(self, tm):
        """Two tasks should not interfere with each other."""
        id1 = tm.create_task("python_basic")
        id2 = tm.create_task("git")

        tm.update_task(id1, "running", 50, "install:running")
        tm.update_task(id2, "running", 20, "download:running")

        t1 = tm.get_task(id1)
        t2 = tm.get_task(id2)

        assert t1["progress"] == 50
        assert t2["progress"] == 20
        assert t1["current_step"] != t2["current_step"]


class TestValidationAgent:
    """Test ValidationAgent with mocked detection results."""

    def test_all_expected_found(self):
        """When all expected software is detected, all should be True."""
        from unittest.mock import patch
        from backend.agents.validate_agent import ValidationAgent

        with patch("backend.agents.validate_agent.is_simulated_host", return_value=True):
            result = ValidationAgent().run({
                "expected_software": ["python", "git", "vscode"]
            })
            assert result["validation"]["python"] is True
            assert result["validation"]["git"] is True
            assert result["validation"]["vscode"] is True

    def test_partial_detection(self):
        """When some software missing, validation should reflect reality."""
        from unittest.mock import patch, MagicMock
        from backend.agents.validate_agent import ValidationAgent

        mock_detection = {
            "installed": {"python": True, "git": False, "vscode": True},
            "is_admin": True,
            "free_disk_gb": 50.0,
        }

        with patch("backend.agents.validate_agent.is_simulated_host", return_value=False), \
             patch("backend.agents.validate_agent.DetectionAgent") as MockDetection:
            MockDetection.return_value.run.return_value = mock_detection
            result = ValidationAgent().run({
                "expected_software": ["python", "git"]
            })
            assert result["validation"]["python"] is True
            assert result["validation"]["git"] is False


class TestEnvironmentAgent:
    """Test EnvironmentAgent creates project structure."""

    def test_creates_project_dirs(self, tmp_path):
        """Should create src/, tests/, data/, notebooks/, docs/ subdirs."""
        from backend.agents.environment_agent import EnvironmentAgent
        project_path = str(tmp_path / "test_project")

        result = EnvironmentAgent().run({"project_path": project_path})

        assert result["project_root"] == project_path
        assert len(result["dirs_created"]) == 5  # src, tests, data, notebooks, docs

        # Verify directories actually exist on disk
        from pathlib import Path
        for subdir in ["src", "tests", "data", "notebooks", "docs"]:
            assert (Path(project_path) / subdir).is_dir()

    def test_creates_venv(self, tmp_path):
        """Should create a Python virtual environment."""
        from backend.agents.environment_agent import EnvironmentAgent
        project_path = str(tmp_path / "venv_test")

        result = EnvironmentAgent().run({"project_path": project_path})
        assert result["venv_created"] is True
        assert (tmp_path / "venv_test" / "project_env").is_dir()

    def test_handles_existing_directory(self, tmp_path):
        """Should not crash if project folder already exists."""
        from backend.agents.environment_agent import EnvironmentAgent
        project_path = str(tmp_path / "existing_project")
        (tmp_path / "existing_project" / "src").mkdir(parents=True)

        result = EnvironmentAgent().run({"project_path": project_path})
        assert result["project_root"] == project_path
        # Should succeed without error
