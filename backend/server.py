"""AuriOS FastAPI backend — chat, profile, preferences, and installation-history endpoints."""

from __future__ import annotations

import asyncio
import json
import os
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
from backend.core.orchestrator import Orchestrator, PRETTY
from backend.core.task_manager import task_manager
from backend.llm.intent_parser import parse_intent
from backend.utils.admin_check import is_admin
from backend.utils.platform_utils import free_disk_gb, is_windows
from backend.utils import repo_sync

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
        self._conn = await aiosqlite.connect(self._path, timeout=30)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=30000")
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
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=30000")
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

    repo_sync.startup_sync()
    yield


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title="AuriOS Backend", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost", "http://127.0.0.1",
                   "http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:5173", "http://127.0.0.1:5173",
                   "app://app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

async def run_orchestrator_background(preset: str, task_id: str):
    """Run full preset installation pipeline in background.

    The orchestrator handles both named presets (python_basic, full_stack, …)
    and raw software names (git, docker, …) — the single-software case is
    covered by a fallback in ``Orchestrator.run`` which synthesizes a
    ``{"software": [preset], "pip_packages": []}`` config.
    """
    try:
        orchestrator = Orchestrator()
        await orchestrator.run(
            preset_name=preset,
            task_id=task_id,
            progress_callback=lambda step, status, pct, msg: None,
        )
        # Save to installation history
        task = task_manager.get_task(task_id)
        final_status = task["status"] if task else "unknown"
        async with get_db() as db:
            await db.execute(
                "INSERT INTO installation_history (preset_name, status) VALUES (?, ?)",
                (preset, final_status)
            )
            await db.commit()
    except Exception as e:
        task_manager.update_task(task_id, "failed", 0, f"failed:{e}")


_INSTALL_INTENTS = {
    "python_basic", "python_ml", "web_dev",
    "full_stack", "data_science", "java",
    "single_software",
}


def _format_software_list() -> str:
    """Return a formatted list of available software from the catalog."""
    catalog = repo_sync.get_catalog()
    names = sorted(e["display_name"] for e in catalog.values())
    items = "\n".join(f"• {n}" for n in names)
    return f"Here's what I can install for you:\n{items}\n\nJust say 'install <name>' to get started!"


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

    if result["intent"] == "list_software":
        response_text = _format_software_list()

    elif result["needs_clarification"]:
        # Just respond with clarifying question, no install
        pass

    elif result["intent"] in _INSTALL_INTENTS:
        # Admin check: on non-Windows this is always True, so Docker works.
        if not is_admin():
            response_text = (
                "AuriOS needs administrator privileges to install software. "
                "Please restart AuriOS as Administrator. "
                "Right-click AuriOS → Run as Administrator 🔐"
            )
        else:
            # Disk space check (cross-platform).
            free_gb = free_disk_gb()
            if free_gb and free_gb < 1.0:
                response_text = (
                    f"Heads up! You only have {free_gb}GB free. "
                    f"Installation needs at least 1GB. Free up some space first! 💾"
                )
            else:
                # Unify preset + single_software: for single_software we use the
                # specific tool name as the preset key — Orchestrator falls back
                # to a synthesized single-software config.
                if result["intent"] == "single_software":
                    preset_key = result.get("preset_or_software") or "unknown"
                    if not repo_sync.is_available(preset_key):
                        response_text = (
                            f"Sorry, **{preset_key}** isn't available in the AuriOS "
                            f"repository yet. You can browse what's available by asking "
                            f"me to 'show available software'."
                        )
                        async with get_db() as db:
                            await db.execute(
                                "INSERT INTO conversations (role, content) VALUES (?, ?)",
                                ("assistant", response_text),
                            )
                            await db.commit()
                        return {
                            "response": response_text,
                            "task_id": None,
                            "intent": result["intent"],
                            "preset_or_software": preset_key,
                            "needs_clarification": False,
                        }

                    # Check if already installed — skip re-install, just launch
                    detection = await asyncio.to_thread(
                        lambda: DetectionAgent().run({})
                    )
                    if detection.get("installed", {}).get(preset_key):
                        label = PRETTY.get(preset_key, preset_key)
                        response_text = (
                            f"**{label}** is already installed on your PC! "
                            f"Opening it for you now. ✅"
                        )
                        from backend.core.orchestrator import _launch
                        await asyncio.to_thread(_launch, preset_key)
                        async with get_db() as db:
                            await db.execute(
                                "INSERT INTO conversations (role, content) VALUES (?, ?)",
                                ("assistant", response_text),
                            )
                            await db.commit()
                        return {
                            "response": response_text,
                            "task_id": None,
                            "intent": result["intent"],
                            "preset_or_software": preset_key,
                            "needs_clarification": False,
                        }
                else:
                    preset_key = result["intent"]

                # Always use a controlled message — never let the LLM claim
                # the software is already installed or was installed successfully,
                # since it generates that text before any real install happens.
                label = PRETTY.get(preset_key, preset_key)
                response_text = (
                    f"Got it! Starting **{label}** setup now. "
                    f"Watch the progress panel on the right! 🚀"
                )

                task_id = task_manager.create_task(preset_key)
                asyncio.create_task(
                    run_orchestrator_background(preset_key, task_id)
                )

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
    import subprocess
    import urllib.request as _ureq

    # ── Ollama connectivity ───────────────────────────────────────────────────
    _ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_connected = False
    try:
        with _ureq.urlopen(_ollama_url, timeout=2) as _r:
            ollama_connected = (_r.getcode() == 200)
    except Exception:
        ollama_connected = False

    # ── Admin privileges (platform-aware) ────────────────────────────────────
    admin_status = is_admin()

    # ── Free disk space (platform-aware) ─────────────────────────────────────
    free_gb = free_disk_gb()

    # ── Software detection via subprocess (cross-platform) ───────────────────
    _SW_CMDS: Dict[str, list] = {
        "python": ["python",  "--version"],
        "git":    ["git",     "--version"],
        "nodejs": ["node",    "--version"],
        "npm":    ["npm",     "--version"],
        "vscode": ["code",    "--version"],
        "docker": ["docker",  "--version"],
        "java":   ["java",    "-version"],
    }
    _no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows() else 0

    async def _check(cmd: list) -> bool:
        if shutil.which(cmd[0]) is None:
            return False
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
    # python3 also counts as python on Linux
    if not installed["python"] and shutil.which("python3") is not None:
        installed["python"] = True

    return {
        "ollama_connected": ollama_connected,
        "is_admin":         admin_status,
        "free_disk_gb":     free_gb,
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
                # current_step is encoded as "step_id:step_status" by the orchestrator.
                raw = task["current_step"] or ""
                if ":" in raw:
                    step_id, step_stat = raw.split(":", 1)
                else:
                    step_id, step_stat = raw, task["status"]

                # Terminal markers have no matching panel row — send null step so
                # the frontend's updateStep triggers _onAllDone instead.
                _TERMINAL = {"complete", "cancelled", "failed"}
                payload: Dict[str, Any] = {
                    "step":     step_id if step_id not in _TERMINAL else None,
                    "status":   step_stat,
                    "progress": task["progress"],
                    "message":  f"{step_id} — {step_stat}",
                }
                if task["status"] == "done":
                    fm = task.get("final_message")
                    if fm:
                        payload["final_message"] = fm
                elif task["status"] == "failed":
                    payload["final_message"] = (
                        f"⚠️ Installation failed: "
                        f"{task.get('current_step', 'unknown error')}"
                    )
                elif task["status"] == "cancelled":
                    payload["final_message"] = "Installation cancelled."
                await websocket.send_json(payload)
                last_status = current_status

            if task["status"] in ["done", "cancelled", "failed"]:
                break

            await asyncio.sleep(0.5)

    except Exception:
        pass
    finally:
        await websocket.close()


# ---------------------------------------------------------------------------
# Available software catalog
# ---------------------------------------------------------------------------

@app.get("/available-software")
async def available_software() -> list[Dict[str, Any]]:
    """Return the current software catalog from the GitHub repository."""
    catalog = await asyncio.to_thread(repo_sync.get_catalog)
    return sorted(catalog.values(), key=lambda e: e["display_name"])


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
