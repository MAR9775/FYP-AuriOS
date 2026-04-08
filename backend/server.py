"""AuriOS FastAPI backend — chat, profile, preferences, and installation-history endpoints."""

from __future__ import annotations

import asyncio
import json
import platform
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.agents.detection_agent import DetectionAgent
from backend.agents.download_agent import DownloadAgent
from backend.agents.install_agent import InstallAgent
from backend.core.orchestrator import Orchestrator
from backend.core.task_manager import task_manager
from backend.llm.intent_parser import parse_intent
from backend.utils.admin_check import is_admin

# ---------------------------------------------------------------------------
# Task infrastructure
# ---------------------------------------------------------------------------

# task_manager is imported as singleton from backend.core.task_manager

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "aurjos.db"


# ---------------------------------------------------------------------------
# Pydantic request schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Incoming chat message."""
    message: str


class ProfileRequest(BaseModel):
    """Fields accepted by POST /profile."""
    user_name: Optional[str] = None
    experience: Optional[str] = None
    interests: Optional[str] = None


class PreferenceRequest(BaseModel):
    """Single key-value pair for POST /preferences."""
    key: str
    value: str


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

class _RowFactoryDB:
    """Async context manager that opens an aiosqlite connection with Row factory set."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        return self._conn

    async def __aexit__(self, *args: Any) -> None:
        if self._conn:
            await self._conn.close()


def get_db() -> _RowFactoryDB:
    """Return an async context manager that opens the AuriOS database with Row factory."""
    return _RowFactoryDB(DB_PATH)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure required tables exist before serving requests."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                role      TEXT,
                content   TEXT,
                metadata  TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                key        TEXT UNIQUE,
                value      TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS installation_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                preset_name TEXT,
                software    TEXT,
                status      TEXT,
                duration_s  REAL,
                error_log   TEXT
            )
            """
        )
        await db.commit()
    yield


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title="AuriOS Backend", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost", "http://127.0.0.1",
                   "http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

async def run_orchestrator_background(preset: str, task_id: str):
    """Run full preset installation pipeline in background."""
    try:
        orchestrator = Orchestrator()
        await orchestrator.run(
            preset_name=preset,
            task_id=task_id,
            progress_callback=lambda step, status, pct, msg:
                task_manager.update_task(task_id, status, pct, step)
        )
        # Save to installation history
        async with get_db() as db:
            await db.execute(
                "INSERT INTO installation_history (preset_name, status) VALUES (?, ?)",
                (preset, "success")
            )
            await db.commit()
    except Exception as e:
        task_manager.update_task(task_id, "failed", 0, str(e))


async def run_single_software_background(software: str, task_id: str):
    """Download and install a single software in background."""
    try:
        task_manager.update_task(task_id, "running", 0, f"Starting {software}")

        # Step 1: Download
        task_manager.update_task(task_id, "running", 10, f"download_{software}")
        downloader = DownloadAgent()

        def on_progress(pct):
            task_manager.update_task(task_id, "running", int(pct * 0.7), f"download_{software}")

        filepath = await asyncio.to_thread(downloader.download, software, on_progress)

        # Step 2: Install
        task_manager.update_task(task_id, "running", 75, f"install_{software}")
        installer = InstallAgent()
        result = await asyncio.to_thread(installer.install, filepath)

        if result["success"]:
            task_manager.update_task(task_id, "done", 100, "complete")
            async with get_db() as db:
                await db.execute(
                    "INSERT INTO installation_history (preset_name, status) VALUES (?, ?)",
                    (software, "success")
                )
                await db.commit()
        else:
            task_manager.update_task(task_id, "failed", 75, result["error"])
    except Exception as e:
        task_manager.update_task(task_id, "failed", 0, str(e))


@app.post("/chat")
async def chat(request: ChatRequest):
    """Process user message, parse intent, and trigger installation if needed."""
    user_message = request.message

    # Save user message to DB
    async with get_db() as db:
        await db.execute(
            "INSERT INTO conversations (role, content) VALUES (?, ?)",
            ("user", user_message)
        )
        await db.commit()

    # Parse intent via Ollama (blocking HTTP — run off the event loop)
    result = await asyncio.to_thread(parse_intent, user_message)
    response_text = result["response_text"]
    task_id = None

    if result["needs_clarification"]:
        # Just respond with clarifying question, no install
        pass

    elif result["intent"] in [
        "python_basic", "python_ml", "web_dev",
        "full_stack", "data_science", "java"
    ]:
        # Check admin before starting
        if not is_admin():
            response_text = (
                "AuriOS needs administrator privileges to install software. "
                "Please restart AuriOS as Administrator. "
                "Right-click AuriOS → Run as Administrator 🔐"
            )
        else:
            # Check disk space
            free_gb = shutil.disk_usage("C:/").free / (1024 ** 3)
            if free_gb < 1.0:
                response_text = (
                    f"Heads up! You only have {free_gb:.1f}GB free. "
                    f"Installation needs at least 1GB. Free up some space first! 💾"
                )
            else:
                # Use the intent name as preset key (matches PRESET_CONFIGS keys)
                preset = result["intent"]
                response_text = (
                    f"Got it! Starting {preset} setup now. "
                    f"Watch the progress panel on the right! 🚀"
                )
                # Create task and start orchestrator in background
                task_id = task_manager.create_task(preset)
                asyncio.create_task(
                    run_orchestrator_background(preset, task_id)
                )

    elif result["intent"] == "single_software":
        software = result["preset_or_software"]
        if not is_admin():
            response_text = (
                "Need admin privileges to install. "
                "Please restart as Administrator 🔐"
            )
        else:
            task_id = task_manager.create_task(software)
            asyncio.create_task(
                run_single_software_background(software, task_id)
            )
            response_text = f"Installing {software} for you now! 🚀"

    # Save assistant response
    async with get_db() as db:
        await db.execute(
            "INSERT INTO conversations (role, content) VALUES (?, ?)",
            ("assistant", response_text)
        )
        await db.commit()

    return {
        "response": response_text,
        "task_id": task_id,
        "intent": result["intent"],
        "preset_or_software": result.get("preset_or_software"),
        "needs_clarification": result["needs_clarification"]
    }


@app.get("/history")
async def history() -> list[Dict[str, Any]]:
    """Return the last 50 rows from the conversations table."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM conversations ORDER BY id DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in reversed(rows)]


@app.get("/system-status")
async def system_status() -> Dict[str, Any]:
    """Return system info including installed software detected by DetectionAgent."""
    disk = shutil.disk_usage(BASE_DIR)

    # Run DetectionAgent in a thread so we don't block the event loop
    import asyncio
    detection = await asyncio.get_event_loop().run_in_executor(
        None, lambda: DetectionAgent().run({})
    )

    return {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": platform.python_version(),
        "disk_total_gb": round(disk.total / 1024 ** 3, 2),
        "disk_used_gb": round(disk.used / 1024 ** 3, 2),
        "disk_free_gb": round(disk.free / 1024 ** 3, 2),
        "is_admin": detection.get("is_admin", False),
        "free_disk_gb": detection.get("free_disk_gb", 0.0),
        "installed": detection.get("installed", {}),
    }


@app.get("/profile")
async def get_profile() -> Dict[str, Any]:
    """Read user_name, experience, and interests from the preferences table."""
    keys = ("user_name", "experience", "interests")
    async with get_db() as db:
        cursor = await db.execute(
            f"SELECT key, value FROM preferences WHERE key IN ({','.join('?'*len(keys))})",
            keys,
        )
        rows = await cursor.fetchall()
    profile: Dict[str, Any] = {k: None for k in keys}
    for row in rows:
        profile[row["key"]] = row["value"]
    return profile


@app.post("/profile")
async def save_profile(req: ProfileRequest) -> Dict[str, Any]:
    """Upsert user_name, experience, and interests into the preferences table."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No profile fields provided.")

    async with get_db() as db:
        for key, value in updates.items():
            await db.execute(
                """
                INSERT INTO preferences (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                               updated_at=excluded.updated_at
                """,
                (key, value),
            )
        await db.commit()
    return {"saved": list(updates.keys())}


@app.post("/profile/reset")
async def reset_profile() -> Dict[str, Any]:
    """Delete all rows from the preferences table."""
    async with get_db() as db:
        await db.execute("DELETE FROM preferences")
        await db.commit()
    return {"status": "preferences cleared"}


@app.get("/preferences")
async def get_preferences() -> list[Dict[str, Any]]:
    """Return all key-value rows from the preferences table."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM preferences ORDER BY key")
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@app.post("/preferences")
async def set_preference(req: PreferenceRequest) -> Dict[str, Any]:
    """Insert or update a single key-value pair in the preferences table."""
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO preferences (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                           updated_at=excluded.updated_at
            """,
            (req.key, req.value),
        )
        await db.commit()
    return {"key": req.key, "value": req.value}


@app.delete("/history")
async def clear_history() -> dict:
    """Delete all rows from the conversations table."""
    async with get_db() as db:
        await db.execute("DELETE FROM conversations")
        await db.commit()
    return {"status": "cleared"}


@app.get("/system-status-full")
async def system_status_full() -> Dict[str, Any]:
    """Return Ollama connectivity, admin status, free disk space, and installed software."""
    import ctypes
    import subprocess
    import urllib.request as _ureq

    # ── Ollama connectivity ───────────────────────────────────────────────────
    import os as _os
    _ollama_url = _os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_connected = False
    try:
        with _ureq.urlopen(_ollama_url, timeout=2) as _r:
            ollama_connected = (_r.getcode() == 200)
    except Exception:
        ollama_connected = False

    # ── Admin privileges (Windows only) ──────────────────────────────────────
    is_admin = False
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False

    # ── Free disk space ───────────────────────────────────────────────────────
    free_disk_gb = 0.0
    try:
        _usage = shutil.disk_usage("C:/")
        free_disk_gb = round(_usage.free / (1024 ** 3), 1)
    except Exception:
        try:
            _usage = shutil.disk_usage("/")
            free_disk_gb = round(_usage.free / (1024 ** 3), 1)
        except Exception:
            free_disk_gb = 0.0

    # ── Software detection via subprocess ────────────────────────────────────
    _SW_CMDS: Dict[str, list] = {
        "python": ["python",  "--version"],
        "git":    ["git",     "--version"],
        "nodejs": ["node",    "--version"],
        "npm":    ["npm",     "--version"],
        "vscode": ["code",    "--version"],
        "docker": ["docker",  "--version"],
        "java":   ["java",    "-version"],
    }
    _no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    async def _check(cmd: list) -> bool:
        try:
            r = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=5,
                    creationflags=_no_window,
                ),
            )
            return r.returncode == 0
        except Exception:
            return False

    installed: Dict[str, bool] = {}
    for _name, _cmd in _SW_CMDS.items():
        installed[_name] = await _check(_cmd)

    return {
        "ollama_connected": ollama_connected,
        "is_admin":         is_admin,
        "free_disk_gb":     free_disk_gb,
        "installed":        installed,
    }


@app.get("/installation-history")
async def installation_history() -> list[Dict[str, Any]]:
    """Return all rows from the installation_history table."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM installation_history ORDER BY id DESC"
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# WebSocket — real-time installation progress
# ---------------------------------------------------------------------------

@app.websocket("/ws/progress/{task_id}")
async def progress_websocket(websocket: WebSocket, task_id: str):
    """Stream real-time installation progress from DB to frontend."""
    await websocket.accept()
    last_status = None

    try:
        while True:
            task = task_manager.get_task(task_id)

            if not task:
                await websocket.send_json({
                    "step": "error",
                    "status": "failed",
                    "progress": 0,
                    "message": "Task not found"
                })
                break

            # Only send if something changed
            current_status = (task["status"], task["progress"], task["current_step"])
            if current_status != last_status:
                await websocket.send_json({
                    "step":     task["current_step"],
                    "status":   task["status"],
                    "progress": task["progress"],
                    "message":  f"{task['current_step']} — {task['status']}"
                })
                last_status = current_status

            if task["status"] in ["done", "cancelled", "failed"]:
                break

            await asyncio.sleep(0.5)

    except Exception:
        pass
    finally:
        await websocket.close()


# ---------------------------------------------------------------------------
# Cancel endpoint
# ---------------------------------------------------------------------------

@app.post("/cancel/{task_id}")
async def cancel_task(task_id: str) -> Dict[str, Any]:
    """Cancel the running task identified by *task_id*."""
    cancelled = await asyncio.get_running_loop().run_in_executor(
        None, task_manager.cancel_task, task_id
    )
    return {"cancelled": cancelled}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.server:app", host="127.0.0.1", port=8000, reload=True)
