import uuid
import sqlite3
from pathlib import Path

# Resolve absolute path so it works regardless of CWD
DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "aurjos.db")

def _connect() -> sqlite3.Connection:
    """Return a connection with WAL mode + busy timeout so concurrent writers
    don't immediately raise ``database is locked``."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_tasks_table():
    """Create the tasks table if it does not exist, and migrate older schemas."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id            TEXT PRIMARY KEY,
                preset        TEXT,
                status        TEXT NOT NULL DEFAULT 'pending',
                progress      INTEGER NOT NULL DEFAULT 0,
                current_step  TEXT,
                final_message TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Idempotent migration for DBs created by the old schema.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "final_message" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN final_message TEXT")
        conn.commit()

_ensure_tasks_table()

class TaskManager:
    """Manages installation tasks with real-time SQLite persistence."""

    def create_task(self, preset: str) -> str:
        """Insert a new task into DB and return its UUID."""
        task_id = str(uuid.uuid4())
        with _connect() as conn:
            conn.execute(
                """INSERT INTO tasks (id, status, preset, progress, current_step)
                   VALUES (?, 'pending', ?, 0, 'starting')""",
                (task_id, preset)
            )
            conn.commit()
        return task_id

    def update_task(self, task_id: str, status: str,
                    progress: int, current_step: str):
        """Update task status and progress in DB."""
        with _connect() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status=?, progress=?, current_step=?
                   WHERE id=?""",
                (status, progress, current_step, task_id)
            )
            conn.commit()

    def get_task(self, task_id: str) -> dict | None:
        """Fetch task row from DB as dict."""
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def set_final_message(self, task_id: str, msg: str) -> None:
        """Persist the terminal user-facing message for a task.

        Lives in its own column so it does not race with ``update_task``'s
        ``current_step`` writes — the WebSocket loop reads both in one go.
        """
        with _connect() as conn:
            conn.execute(
                "UPDATE tasks SET final_message=? WHERE id=?",
                (msg, task_id),
            )
            conn.commit()

    def cancel_task(self, task_id: str):
        """Mark task as cancelled."""
        self.update_task(task_id, "cancelled", 0, "cancelled")

# Singleton instance used across all modules
task_manager = TaskManager()
