"""AuriOS FastAPI backend — chat, profile, preferences, and installation-history endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import secrets
import bcrypt
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite
import time as _time_module
from collections import defaultdict
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
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

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthTokenRequest(BaseModel):
    token: str

class ChangePasswordRequest(BaseModel):
    token: str
    current_password: str
    new_password: str


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
                user_id    INTEGER,
                key        TEXT,
                value      TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Migrate existing preferences table — add user_id column if missing
        async with db.execute("PRAGMA table_info(preferences)") as _cur:
            _pref_cols = {row[1] for row in await _cur.fetchall()}
        if "user_id" not in _pref_cols:
            await db.execute("ALTER TABLE preferences ADD COLUMN user_id INTEGER")
        # Backfill: assign orphaned preferences (user_id IS NULL, non-system keys)
        # to the first real user in the DB — these were created during their onboarding
        _system_keys = ("admin_session", "gh_owner", "gh_repo", "gh_token_enc", "windowBounds")
        _placeholders = ",".join("?" * len(_system_keys))
        async with db.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1") as _cur:
            _first_user = await _cur.fetchone()
        if _first_user:
            await db.execute(
                f"UPDATE preferences SET user_id = ? "
                f"WHERE user_id IS NULL AND key NOT IN ({_placeholders})",
                (_first_user[0], *_system_keys),
            )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'user',
                status        TEXT NOT NULL DEFAULT 'active',
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Migrate existing users table — safely add role and status columns
        async with db.execute("PRAGMA table_info(users)") as _cur:
            _cols = {row[1] for row in await _cur.fetchall()}
        if "role" not in _cols:
            await db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "status" not in _cols:
            await db.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token         TEXT PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS software_catalog (
                slug         TEXT PRIMARY KEY,
                display_name TEXT,
                filename     TEXT,
                url          TEXT,
                version      TEXT,
                size_mb      REAL DEFAULT 0,
                source       TEXT,
                category     TEXT DEFAULT 'Other',
                status       TEXT DEFAULT 'available',
                updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id            TEXT PRIMARY KEY,
                preset        TEXT,
                status        TEXT DEFAULT 'pending',
                progress      INTEGER DEFAULT 0,
                current_step  TEXT,
                final_message TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()

    # Wait for catalog sync before starting to serve requests
    await asyncio.to_thread(repo_sync.sync)
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

@app.post("/auth/signup")
async def auth_signup(req: SignupRequest):
    if not req.name or not req.email or not req.password:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    hashed = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (req.name, req.email, hashed)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(status_code=400, detail="Email already registered")
            
    return {"status": "ok", "message": "Account created! Please log in."}

def _get_admin_hash() -> str:
    env_path = BASE_DIR / "backend" / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("ADMIN_PASSWORD_HASH="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val
    # No valid hash found — generate one for "Admin@1234" and persist it
    default_hash = bcrypt.hashpw(b"Admin@1234", bcrypt.gensalt()).decode("utf-8")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = env_path.read_text() if env_path.exists() else ""
    if "ADMIN_PASSWORD_HASH=" not in existing:
        with open(env_path, "a") as f:
            f.write(f"ADMIN_PASSWORD_HASH={default_hash}\n")
    return default_hash

# ---------------------------------------------------------------------------
# Rate limiter for login brute-force protection (FIX 12)
# ---------------------------------------------------------------------------

_login_attempts: dict = defaultdict(list)  # ip -> [timestamp, timestamp, ...]
_LOGIN_WINDOW  = 300   # seconds to track attempts
_LOGIN_MAX     = 5     # max failed attempts within window
_LOGIN_LOCKOUT = 60    # lockout duration in seconds after exceeding max

def _check_rate_limit(ip: str) -> None:
    now = _time_module.time()
    # Purge old entries
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW]
    if len(_login_attempts[ip]) >= _LOGIN_MAX:
        oldest = _login_attempts[ip][0]
        remaining = int(_LOGIN_LOCKOUT - (now - oldest))
        if remaining > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many login attempts. Please wait {remaining} seconds before trying again."
            )
        # Lockout expired, reset
        _login_attempts[ip] = []

def _record_failed_login(ip: str) -> None:
    _login_attempts[ip].append(_time_module.time())

def _clear_login_attempts(ip: str) -> None:
    _login_attempts.pop(ip, None)

@app.post("/auth/login")
async def auth_login(req: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    # 1. System Admin bypass
    if req.email == "admin@jarvis.local":
        admin_hash = _get_admin_hash()
        if bcrypt.checkpw(req.password.encode('utf-8'), admin_hash.encode('utf-8')):
            token = "admin_" + secrets.token_hex(26)
            async with get_db() as db:
                await db.execute("INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", ("admin_session", token))
                await db.commit()
            return {"token": token, "user": {"id": 0, "name": "System Admin", "email": req.email, "role": "admin"}}
        else:
            _record_failed_login(client_ip)
            raise HTTPException(status_code=401, detail="Incorrect password.")

    # Regular user lookup
    async with get_db() as db:
        async with db.execute(
            "SELECT id, name, email, password_hash, role, status FROM users WHERE email = ?",
            (req.email,)
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            _record_failed_login(client_ip)
            raise HTTPException(status_code=401, detail="No account found with this email.")

        if (user["status"] or "active") == "inactive":
            raise HTTPException(
                status_code=403,
                detail="This account has been deactivated. Contact an administrator."
            )

        if not bcrypt.checkpw(req.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
            _record_failed_login(client_ip)
            raise HTTPException(status_code=401, detail="Incorrect password.")

        _clear_login_attempts(client_ip)

        token = secrets.token_hex(32)
        await db.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
        await db.commit()

    return {
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"] or "user",
        },
    }

@app.post("/auth/verify")
async def auth_verify(req: AuthTokenRequest):
    async with get_db() as db:
        if req.token.startswith("admin_"):
            async with db.execute("SELECT value FROM preferences WHERE key = 'admin_session'") as cursor:
                row = await cursor.fetchone()
            if row and row['value'] == req.token:
                return {"valid": True, "user": {"id": 0, "name": "Admin", "email": "admin@jarvis.local", "role": "admin"}}
            raise HTTPException(status_code=401, detail="Invalid or expired session")
            
        async with db.execute(
            "SELECT u.id, u.name, u.email FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.token = ?",
            (req.token,)
        ) as cursor:
            user = await cursor.fetchone()
            
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
            
    return {"valid": True, "user": {"id": user['id'], "name": user['name'], "email": user['email'], "role": "user"}}

@app.post("/auth/logout")
async def auth_logout(req: AuthTokenRequest):
    async with get_db() as db:
        if req.token.startswith("admin_"):
            await db.execute("DELETE FROM preferences WHERE key = 'admin_session' AND value = ?", (req.token,))
        else:
            await db.execute("DELETE FROM sessions WHERE token = ?", (req.token,))
        await db.commit()
    return {"status": "ok"}

@app.post("/auth/change-password")
async def auth_change_password(req: ChangePasswordRequest):
    async with get_db() as db:
        if req.token.startswith("admin_"):
            raise HTTPException(status_code=403, detail="Admin password cannot be changed.")
            
        async with db.execute(
            "SELECT u.id, u.password_hash FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.token = ?",
            (req.token,)
        ) as cursor:
            user = await cursor.fetchone()
            
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
            
        if not bcrypt.checkpw(req.current_password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            raise HTTPException(status_code=400, detail="Incorrect current password.")
            
        hashed = bcrypt.hashpw(req.new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        await db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed, user['id']))
        await db.commit()
        
    return {"status": "ok", "message": "Password changed successfully."}

async def run_orchestrator_background(preset: str, task_id: str):
    """Run full preset installation pipeline in background."""
    from backend.core.orchestrator import PRESET_CONFIGS
    from backend.llm.intent_parser import _llm_completion_message
    _start = _time_module.time()
    try:
        orchestrator = Orchestrator()
        await orchestrator.run(
            preset_name=preset,
            task_id=task_id,
            progress_callback=lambda step, status, pct, msg: None,
        )
        task = task_manager.get_task(task_id)
        raw_status = task["status"] if task else "unknown"
        final_status = "success" if raw_status == "done" else raw_status
        duration_s = round(_time_module.time() - _start, 1)
        config = PRESET_CONFIGS.get(preset, {"software": [preset], "pip_packages": []})
        software_csv = ", ".join(config["software"])
        async with get_db() as db:
            await db.execute(
                "INSERT INTO installation_history "
                "(preset_name, software, status, duration_s) VALUES (?, ?, ?, ?)",
                (preset, software_csv, final_status, duration_s)
            )
            await db.commit()

        # Touch Point 2: if install succeeded, ask 3b to generate a helpful
        # completion message. Runs in a thread so it doesn't block the event loop.
        if final_status == "success":
            completion_msg = await asyncio.to_thread(
                _llm_completion_message,
                preset,
                config["software"],
                config.get("pip_packages", []),
                duration_s,
            )
            task_manager.set_final_message(task_id, completion_msg)

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

    # Fetch recent history for context BEFORE inserting new message
    async with get_db() as db:
        cursor = await db.execute("SELECT role, content FROM conversations ORDER BY id DESC LIMIT 6")
        rows = await cursor.fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # Save user message to DB
    async with get_db() as db:
        await db.execute(
            "INSERT INTO conversations (role, content) VALUES (?, ?)",
            ("user", user_message)
        )
        await db.commit()

    # Parse intent via Ollama (blocking HTTP — run off the event loop)
    result = await asyncio.to_thread(parse_intent, user_message, history)
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
                "Right-click AuriOS and select Run as Administrator."
            )
        else:
            # Disk space check (cross-platform).
            free_gb = free_disk_gb()
            if free_gb and free_gb < 1.0:
                response_text = (
                    f"Heads up! You only have {free_gb}GB free. "
                    f"Installation needs at least 1GB. Free up some space first."
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
                            f"Opening it for you now."
                        )
                        from backend.core.orchestrator import _launch
                        try:
                            await asyncio.to_thread(_launch, preset_key)
                        except Exception:
                            pass
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
                    f"Watch the progress panel on the right."
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
async def get_profile(request: Request) -> Dict[str, Any]:
    """Read user_name from users table, and experience/interests from preferences."""
    keys = ("experience", "interests")
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_name = "Unknown"
    created_at = None
    
    async with get_db() as db:
        if token:
            if token.startswith("admin_"):
                user_name = "Admin"
                created_at = "2024-01-01T00:00:00Z"
            else:
                async with db.execute("SELECT u.name, u.created_at FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.token = ?", (token,)) as cursor:
                    user = await cursor.fetchone()
                if user:
                    user_name = user["name"]
                    created_at = user["created_at"]
        
        cursor = await db.execute(
            f"SELECT key, value FROM preferences WHERE key IN ({','.join('?'*len(keys))})",
            keys,
        )
        rows = await cursor.fetchall()
        
    profile: Dict[str, Any] = {k: None for k in keys}
    for row in rows:
        profile[row["key"]] = row["value"]
    profile["user_name"] = user_name
    if created_at:
        profile["created_at"] = created_at
    return profile


@app.post("/profile")
async def save_profile(req: ProfileRequest, request: Request) -> Dict[str, Any]:
    """Upsert user_name to users table, and experience/interests into preferences."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No profile fields provided.")

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = None

    async with get_db() as db:
        # Resolve user_id from token
        if token and not token.startswith("admin_"):
            async with db.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)) as cursor:
                session = await cursor.fetchone()
            if session:
                user_id = session["user_id"]

        if "user_name" in updates:
            new_name = updates.pop("user_name")
            if user_id:
                await db.execute("UPDATE users SET name = ? WHERE id = ?", (new_name, user_id))

        for key, value in updates.items():
            # Delete existing row for this (user_id, key) pair then insert fresh
            await db.execute(
                "DELETE FROM preferences WHERE user_id IS ? AND key = ?",
                (user_id, key),
            )
            await db.execute(
                "INSERT INTO preferences (user_id, key, value, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, key, value),
            )
        await db.commit()
    return {"saved": list(req.model_dump().keys())}


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
async def set_preference(req: PreferenceRequest, request: Request) -> Dict[str, Any]:
    """Insert or update a single key-value pair in the preferences table, linked to the calling user."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = None
    if token and not token.startswith("admin_"):
        async with get_db() as db:
            async with db.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)) as cursor:
                session = await cursor.fetchone()
            if session:
                user_id = session["user_id"]
    async with get_db() as db:
        await db.execute(
            "DELETE FROM preferences WHERE user_id IS ? AND key = ?",
            (user_id, req.key),
        )
        await db.execute(
            "INSERT INTO preferences (user_id, key, value, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (user_id, req.key, req.value),
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


@app.get("/ping")
async def ping() -> Dict[str, str]:
    """Lightweight health check for frontend polling."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Speech transcription — uses Windows System.Speech (offline, no API key)
# ---------------------------------------------------------------------------

@app.post("/speech/transcribe")
async def speech_transcribe(request: Request) -> Dict[str, Any]:
    """Receive a WAV audio blob from the renderer and transcribe it using
    Windows built-in System.Speech recognition. No internet required."""
    import tempfile, subprocess as _sp

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="No audio data received")

    # Write the raw WAV bytes to a temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(body)
        wav_path = tmp.name

    # PowerShell script that uses System.Speech to transcribe the WAV file
    ps_script = r"""
Add-Type -AssemblyName System.Speech
$recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$recognizer.SetInputToWaveFile("{wav_path}")
$grammar = New-Object System.Speech.Recognition.DictationGrammar
$recognizer.LoadGrammar($grammar)
$recognizer.BabbleTimeout = [TimeSpan]::FromSeconds(2)
$recognizer.InitialSilenceTimeout = [TimeSpan]::FromSeconds(3)
try {{
    $result = $recognizer.Recognize()
    if ($result -ne $null) {{
        Write-Output $result.Text
    }} else {{
        Write-Output ""
    }}
}} catch {{
    Write-Output ""
}} finally {{
    $recognizer.Dispose()
}}
""".replace("{wav_path}", wav_path.replace("\\", "\\\\"))

    try:
        result = await asyncio.to_thread(
            lambda: _sp.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=15
            )
        )
        transcript = result.stdout.strip()
        return {"transcript": transcript, "ok": bool(transcript)}
    except Exception as e:
        return {"transcript": "", "ok": False, "error": str(e)}
    finally:
        try:
            import os as _os
            _os.unlink(wav_path)
        except Exception:
            pass



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
    
    # Run all checks in parallel with a 5s maximum timeout
    tasks = {name: asyncio.create_task(_check(cmd)) for name, cmd in _SW_CMDS.items()}
    
    try:
        await asyncio.wait_for(asyncio.gather(*tasks.values()), timeout=5.0)
    except asyncio.TimeoutError:
        pass
        
    for name, task in tasks.items():
        try:
            installed[name] = task.result() if task.done() else False
        except Exception:
            installed[name] = False

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
# Admin endpoints — require admin session token in Authorization header
# ---------------------------------------------------------------------------

from fastapi import Header as _Header

async def _require_admin(authorization: Optional[str]) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token.startswith("admin_"):
        raise HTTPException(status_code=403, detail="Admin access required")
    async with get_db() as db:
        async with db.execute(
            "SELECT value FROM preferences WHERE key = 'admin_session'"
        ) as cursor:
            row = await cursor.fetchone()
    if not row or row["value"] != token:
        raise HTTPException(status_code=401, detail="Invalid or expired admin session")


@app.get("/admin/stats")
async def admin_stats(authorization: Optional[str] = _Header(None)) -> Dict[str, Any]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) AS c FROM users") as cur:
            users = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) AS c FROM sessions") as cur:
            sessions = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) AS c FROM installation_history") as cur:
            installs = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) AS c FROM conversations") as cur:
            convos = (await cur.fetchone())["c"]
    return {"users": users, "active_sessions": sessions, "installations": installs, "conversations": convos}


@app.get("/admin/users")
async def admin_users(authorization: Optional[str] = _Header(None)) -> list[Dict[str, Any]]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute(
            "SELECT id, name, email, role, status, created_at FROM users ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
    # Build regular user list
    result = [
        {
            "id": r["id"],
            "name": r["name"],
            "email": r["email"],
            "role": r["role"],
            "status": r["status"] or "active",
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    # Inject synthetic System Admin row (validated via .env, not stored in users table)
    result.insert(0, {
        "id": 0,
        "name": "System Admin",
        "email": "admin@jarvis.local",
        "role": "admin",
        "status": "active",
        "created_at": None,
    })
    return result


@app.get("/admin/sessions")
async def admin_sessions(authorization: Optional[str] = _Header(None)) -> list[Dict[str, Any]]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute(
            "SELECT s.token, s.created_at, u.id AS user_id, u.name, u.email "
            "FROM sessions s JOIN users u ON s.user_id = u.id "
            "ORDER BY s.created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "token": r["token"],
            "token_preview": r["token"][:8] + "…",
            "user_id": r["user_id"],
            "user_name": r["name"],
            "email": r["email"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.get("/admin/installations")
async def admin_installations(authorization: Optional[str] = _Header(None)) -> list[Dict[str, Any]]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute(
            "SELECT id, timestamp, preset_name, software, status, duration_s "
            "FROM installation_history ORDER BY timestamp DESC LIMIT 200"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/admin/conversations")
async def admin_conversations(authorization: Optional[str] = _Header(None)) -> list[Dict[str, Any]]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute(
            "SELECT id, timestamp, role, content FROM conversations ORDER BY timestamp DESC LIMIT 300"
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "id": r["id"],
            "timestamp": r["timestamp"],
            "role": r["role"],
            "content": (r["content"] or "")[:120] + ("…" if r["content"] and len(r["content"]) > 120 else ""),
        }
        for r in rows
    ]


@app.get("/admin/preferences")
async def admin_preferences(authorization: Optional[str] = _Header(None)) -> list[Dict[str, Any]]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute(
            """
            SELECT p.key, p.value, p.updated_at, p.user_id,
                   u.name AS user_name, u.email AS user_email, u.role AS user_role
            FROM preferences p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.key != 'admin_session'
            ORDER BY p.user_id NULLS FIRST, p.key
            """
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "key": r["key"],
            "value": r["value"],
            "updated_at": r["updated_at"],
            "user_id": r["user_id"],
            "user_name": r["user_name"],
            "user_email": r["user_email"],
            "user_role": r["user_role"],
        }
        for r in rows
    ]


# ── User management ───────────────────────────────────────────────────────────

@app.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    if user_id == 0:
        raise HTTPException(status_code=403, detail="Built-in admin account cannot be deleted")
    async with get_db() as db:
        async with db.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        if row["email"] == "admin@jarvis.local":
            raise HTTPException(status_code=403, detail="Built-in admin account cannot be deleted")
        # Revoke all active sessions for this user before deletion
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
    return {"deleted": user_id}



# ── Admin Account Management ──────────────────────────────────────────────────

class CreateAdminRequest(BaseModel):
    name: str
    email: str
    password: str

@app.post("/admin/accounts")
async def create_admin(req: CreateAdminRequest, authorization: Optional[str] = _Header(None)):
    await _require_admin(authorization)
    hashed = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    async with get_db() as db:
        try:
            await db.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
                (req.name, req.email, hashed)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(status_code=400, detail="Email already registered")
    return {"status": "ok"}

class AdminResetPasswordRequest(BaseModel):
    user_id: int
    new_password: str

@app.post("/admin/accounts/reset-password")
async def admin_reset_password(req: AdminResetPasswordRequest, authorization: Optional[str] = _Header(None)):
    await _require_admin(authorization)
    hashed = bcrypt.hashpw(req.new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Check if target is the System Admin (user_id=0)
    if req.user_id == 0:
        env_path = BASE_DIR / "backend" / ".env"
        # rewrite .env
        lines = []
        if env_path.exists():
            with open(env_path, "r") as f:
                lines = f.readlines()
        with open(env_path, "w") as f:
            replaced = False
            for line in lines:
                if line.startswith("ADMIN_PASSWORD_HASH="):
                    f.write(f"ADMIN_PASSWORD_HASH={hashed}\n")
                    replaced = True
                else:
                    f.write(line)
            if not replaced:
                f.write(f"ADMIN_PASSWORD_HASH={hashed}\n")
        return {"status": "ok"}
        
    async with get_db() as db:
        await db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed, req.user_id))
        await db.commit()
    return {"status": "ok"}

@app.post("/admin/accounts/revoke/{user_id}")
async def admin_revoke_admin(user_id: int, authorization: Optional[str] = _Header(None)):
    await _require_admin(authorization)
    if user_id == 0:
        raise HTTPException(status_code=400, detail="Cannot revoke System Admin")
    async with get_db() as db:
        await db.execute("UPDATE users SET role = 'user' WHERE id = ?", (user_id,))
        # Revoke active sessions so they re-authenticate with new role
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()
    return {"status": "ok"}


# ── User deactivate / reactivate ─────────────────────────────────────────────

@app.post("/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(
    user_id: int,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    if user_id == 0:
        raise HTTPException(status_code=403, detail="Cannot deactivate System Admin")
    async with get_db() as db:
        async with db.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        if row["email"] == "admin@jarvis.local":
            raise HTTPException(status_code=403, detail="Cannot deactivate built-in admin")
        await db.execute("UPDATE users SET status = 'inactive' WHERE id = ?", (user_id,))
        # Revoke active sessions immediately
        await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        await db.commit()
    return {"status": "ok", "user_id": user_id, "account_status": "inactive"}


@app.post("/admin/users/{user_id}/reactivate")
async def admin_reactivate_user(
    user_id: int,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute("SELECT id FROM users WHERE id = ?", (user_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="User not found")
        await db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
        await db.commit()
    return {"status": "ok", "user_id": user_id, "account_status": "active"}

# ── Session management ────────────────────────────────────────────────────────

class _RevokeRequest(BaseModel):
    token: str

@app.post("/admin/sessions/revoke")
async def admin_revoke_session(
    req: _RevokeRequest,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    async with get_db() as db:
        await db.execute("DELETE FROM sessions WHERE token = ?", (req.token,))
        await db.commit()
    return {"revoked": True}


# ── Conversations ─────────────────────────────────────────────────────────────

@app.delete("/admin/conversations")
async def admin_clear_conversations(
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    async with get_db() as db:
        await db.execute("DELETE FROM conversations")
        await db.commit()
    return {"cleared": True}


# ── Preferences management ────────────────────────────────────────────────────

class _PrefUpdateRequest(BaseModel):
    value: str
    user_id: Optional[int] = None

@app.put("/admin/preferences/{key}")
async def admin_update_preference(
    key: str,
    req: _PrefUpdateRequest,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    if key == "admin_session":
        raise HTTPException(status_code=403, detail="Cannot modify admin_session key")
    async with get_db() as db:
        # Update the specific row matching both key and user_id (NULL-safe)
        await db.execute(
            "UPDATE preferences SET value = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE key = ? AND user_id IS ?",
            (req.value, key, req.user_id),
        )
        await db.commit()
    return {"key": key, "value": req.value}


@app.delete("/admin/preferences")
async def admin_reset_preferences(
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    async with get_db() as db:
        await db.execute("DELETE FROM preferences WHERE key != 'admin_session'")
        await db.commit()
    return {"reset": True}


# ── Tasks (installations in-progress) ────────────────────────────────────────

@app.get("/admin/tasks")
async def admin_tasks(authorization: Optional[str] = _Header(None)) -> list[Dict[str, Any]]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute(
            "SELECT id, preset, status, progress, current_step, final_message, created_at, updated_at "
            "FROM tasks ORDER BY created_at DESC LIMIT 100"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── System status (admin-guarded) ─────────────────────────────────────────────

@app.get("/admin/system-status")
async def admin_system_status(
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    import subprocess, urllib.request as _ureq, shutil as _shutil

    _ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_ok = False
    try:
        with _ureq.urlopen(_ollama_url, timeout=2) as _r:
            ollama_ok = (_r.getcode() == 200)
    except Exception:
        ollama_ok = False

    admin_ok = is_admin()
    free_gb  = free_disk_gb()

    _SW: Dict[str, list] = {
        "python": ["python", "--version"],
        "git":    ["git",    "--version"],
        "nodejs": ["node",   "--version"],
        "npm":    ["npm",    "--version"],
        "vscode": ["code",   "--version"],
        "docker": ["docker", "--version"],
    }
    _no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows() else 0

    async def _chk(cmd: list) -> bool:
        if _shutil.which(cmd[0]) is None:
            return False
        try:
            r = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, timeout=5, creationflags=_no_win),
            )
            return r.returncode == 0
        except Exception:
            return False

    tasks_map = {n: asyncio.create_task(_chk(c)) for n, c in _SW.items()}
    try:
        await asyncio.wait_for(asyncio.gather(*tasks_map.values()), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    installed: Dict[str, bool] = {}
    for name, t in tasks_map.items():
        installed[name] = t.result() if t.done() else False
    if not installed.get("python") and __import__("shutil").which("python3"):
        installed["python"] = True

    import psutil as _psutil
    try:
        cpu_pct = _psutil.cpu_percent(interval=0.3)
    except Exception:
        cpu_pct = 0.0
    try:
        _ram = _psutil.virtual_memory()
        ram_pct = _ram.percent
        ram_total_gb = round(_ram.total / 1024 ** 3, 1)
        ram_used_gb  = round(_ram.used  / 1024 ** 3, 1)
    except Exception:
        ram_pct = ram_total_gb = ram_used_gb = 0.0

    disk = __import__("shutil").disk_usage(BASE_DIR)
    return {
        "ollama_connected": ollama_ok,
        "is_admin": admin_ok,
        "cpu_percent": cpu_pct,
        "ram_percent": ram_pct,
        "ram_total_gb": ram_total_gb,
        "ram_used_gb": ram_used_gb,
        "free_disk_gb": free_gb,
        "disk_total_gb": round(disk.total / 1024 ** 3, 2),
        "disk_used_gb":  round(disk.used  / 1024 ** 3, 2),
        "installed": installed,
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": platform.python_version(),
    }


# ── Software catalog ──────────────────────────────────────────────────────────

@app.post("/admin/catalog/refresh")
async def admin_catalog_refresh(
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    await asyncio.to_thread(repo_sync.sync)
    catalog = await asyncio.to_thread(repo_sync.get_catalog)
    return {"synced": True, "count": len(catalog)}


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
                    fm = task.get("final_message")
                    if fm:
                        payload["final_message"] = fm
                    else:
                        payload["final_message"] = (
                            f"Installation failed: "
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
    """Return the current software catalog merged with local overrides."""
    catalog = await asyncio.to_thread(repo_sync.get_catalog)
    
    # Merge local overrides
    async with get_db() as db:
        async with db.execute("SELECT value FROM preferences WHERE key = 'local_catalog'") as cur:
            row = await cur.fetchone()
        if row:
            try:
                local_cat = json.loads(row['value'])
                for slug, item in local_cat.items():
                    catalog[slug] = item
            except Exception:
                pass
                
    return sorted(catalog.values(), key=lambda e: e.get("display_name", e.get("slug")))


# ---------------------------------------------------------------------------
# Admin Dashboard & Catalog
# ---------------------------------------------------------------------------

@app.get("/admin/dashboard-stats")
async def admin_dashboard_stats(authorization: Optional[str] = _Header(None)) -> Dict[str, Any]:
    await _require_admin(authorization)
    async with get_db() as db:
        # Users
        async with db.execute("SELECT date(created_at) as d, COUNT(*) as c FROM users GROUP BY d ORDER BY d DESC LIMIT 14") as cur:
            users_by_day = await cur.fetchall()
        
        # Installs
        async with db.execute("SELECT date(timestamp) as d, COUNT(*) as c FROM installation_history GROUP BY d ORDER BY d DESC LIMIT 30") as cur:
            installs_activity = await cur.fetchall()
            
        # Top software
        async with db.execute("SELECT preset_name as name, COUNT(*) as c FROM installation_history WHERE status IN ('done', 'completed', 'success') GROUP BY preset_name ORDER BY c DESC LIMIT 5") as cur:
            top_software = await cur.fetchall()
            
        # Success/fail
        async with db.execute("SELECT date(timestamp) as d, status, COUNT(*) as c FROM installation_history GROUP BY d, status ORDER BY d DESC LIMIT 30") as cur:
            success_fail = await cur.fetchall()
            
        # Totals
        async with db.execute("SELECT COUNT(*) AS c FROM users") as cur:
            users = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) AS c FROM sessions") as cur:
            sessions = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) AS c FROM installation_history") as cur:
            installs = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) AS c FROM conversations") as cur:
            convos = (await cur.fetchone())["c"]
    # FIX 9: Conversations by day for sparkline
    async with get_db() as db:
        async with db.execute(
            "SELECT date(timestamp) as d, COUNT(*) as c FROM conversations GROUP BY d ORDER BY d DESC LIMIT 14"
        ) as cur:
            conversations_by_day = await cur.fetchall()

    return {
        "totals": {
            "users": users,
            "active_sessions": sessions,
            "installations": installs,
            "conversations": convos,
        },
        "users_by_day": [dict(r) for r in users_by_day],
        "installs_activity": [dict(r) for r in installs_activity],
        "top_software": [dict(r) for r in top_software],
        "success_fail": [dict(r) for r in success_fail],
        "conversations_by_day": [dict(r) for r in conversations_by_day],
    }

class CatalogItemRequest(BaseModel):
    display_name: str
    slug: str
    url: str
    filename: str

@app.post("/admin/catalog/local")
async def admin_catalog_add(req: CatalogItemRequest, authorization: Optional[str] = _Header(None)):
    await _require_admin(authorization)
    async with get_db() as db:
        await db.execute('''
            INSERT INTO software_catalog (slug, display_name, filename, url, version, category, source, status)
            VALUES (?, ?, ?, ?, ?, 'Other', 'local', 'available')
            ON CONFLICT(slug) DO UPDATE SET 
                display_name=excluded.display_name, 
                filename=excluded.filename,
                url=excluded.url,
                status='available',
                updated_at=CURRENT_TIMESTAMP
        ''', (req.slug, req.display_name, req.filename, req.url, '1.0'))
        await db.commit()
    return {"status": "ok"}

@app.delete("/admin/catalog/local/{slug}")
async def admin_catalog_delete(slug: str, authorization: Optional[str] = _Header(None)):
    await _require_admin(authorization)
    async with get_db() as db:
        await db.execute("DELETE FROM software_catalog WHERE slug = ?", (slug,))
        await db.commit()
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# ── Catalog sync status ───────────────────────────────────────────────────────

@app.get("/admin/catalog/sync-status")
async def admin_catalog_sync_status(
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    from backend.utils import repo_sync as _rs
    import time as _time
    last = _rs._last_sync
    if last:
        ago_min = round((_time.time() - last) / 60, 1)
        import datetime as _dt
        ts = _dt.datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M:%S")
    else:
        ago_min = None
        ts = None
    return {"last_sync_ts": ts, "last_sync_ago_min": ago_min, "sync_ok": _rs._sync_ok}


# ── GitHub configuration ──────────────────────────────────────────────────────

from backend.utils.crypto import encrypt_data as _enc, decrypt_data as _dec

class GithubConfigRequest(BaseModel):
    token: str
    owner: str
    repo: str

@app.get("/admin/config/github")
async def admin_get_github_config(
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    async with get_db() as db:
        async with db.execute(
            "SELECT key, value FROM preferences WHERE key IN ('gh_owner','gh_repo','gh_token_enc')"
        ) as cur:
            rows = {r["key"]: r["value"] for r in await cur.fetchall()}
    return {
        "owner": rows.get("gh_owner", ""),
        "repo":  rows.get("gh_repo", ""),
        "token_set": bool(rows.get("gh_token_enc")),
    }

@app.post("/admin/config/github")
async def admin_set_github_config(
    req: GithubConfigRequest,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    enc_token = _enc(req.token) if req.token else ""
    async with get_db() as db:
        for key, val in [("gh_owner", req.owner), ("gh_repo", req.repo), ("gh_token_enc", enc_token)]:
            await db.execute(
                "INSERT INTO preferences (key,value,updated_at) VALUES (?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, val),
            )
        await db.commit()
    return {"status": "ok"}

@app.post("/admin/config/github/validate")
async def admin_validate_github_token(
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    import requests as _req
    async with get_db() as db:
        async with db.execute("SELECT value FROM preferences WHERE key='gh_token_enc'") as cur:
            row = await cur.fetchone()
    if not row or not row["value"]:
        raise HTTPException(status_code=400, detail="No GitHub token configured")
    token = _dec(row["value"])
    try:
        r = await asyncio.to_thread(
            lambda: _req.get(
                "https://api.github.com/user",
                headers={"Authorization": f"token {token}", "User-Agent": "AuriOS/1.1"},
                timeout=8,
            )
        )
        if r.status_code == 200:
            data = r.json()
            return {"valid": True, "login": data.get("login"), "scopes": r.headers.get("X-OAuth-Scopes", "")}
        raise HTTPException(status_code=400, detail=f"GitHub returned {r.status_code}: {r.text[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {e}")


# ── Software download (winget → choco → GitHub search) ───────────────────────

import shutil as _shutil_mod

class SoftwareDownloadRequest(BaseModel):
    name: str
    destination: Optional[str] = None

@app.post("/admin/software/download")
async def admin_software_download(
    req: SoftwareDownloadRequest,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    import subprocess as _sp, urllib.request as _ureq, re as _re

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Software name is required")

    dest_dir = Path(req.destination) if req.destination else BASE_DIR / "data" / "staging"
    dest_dir.mkdir(parents=True, exist_ok=True)

    _no_win = getattr(_sp, "CREATE_NO_WINDOW", 0) if is_windows() else 0

    # 1. Try winget
    if _shutil_mod.which("winget"):
        try:
            r = await asyncio.to_thread(lambda: _sp.run(
                ["winget", "download", name, "--download-directory", str(dest_dir), "--accept-package-agreements", "--accept-source-agreements"],
                capture_output=True, text=True, timeout=120, creationflags=_no_win,
            ))
            if r.returncode == 0:
                return {"status": "ok", "method": "winget", "destination": str(dest_dir), "output": r.stdout[-500:]}
        except Exception:
            pass

    # 2. Try choco download
    if _shutil_mod.which("choco"):
        try:
            r = await asyncio.to_thread(lambda: _sp.run(
                ["choco", "download", name, "--output-directory", str(dest_dir), "-y"],
                capture_output=True, text=True, timeout=120, creationflags=_no_win,
            ))
            if r.returncode == 0:
                return {"status": "ok", "method": "chocolatey", "destination": str(dest_dir), "output": r.stdout[-500:]}
        except Exception:
            pass

    # 3. GitHub releases search fallback
    try:
        search_r = await asyncio.to_thread(lambda: _req.get(
            f"https://api.github.com/search/repositories?q={name}&sort=stars&per_page=3",
            headers={"User-Agent": "AuriOS/1.1"}, timeout=8,
        ))
        if search_r.status_code == 200:
            items = search_r.json().get("items", [])
            if items:
                repo_full = items[0]["full_name"]
                rel_r = await asyncio.to_thread(lambda: _req.get(
                    f"https://api.github.com/repos/{repo_full}/releases/latest",
                    headers={"User-Agent": "AuriOS/1.1"}, timeout=8,
                ))
                if rel_r.status_code == 200:
                    assets = rel_r.json().get("assets", [])
                    win_assets = [a for a in assets if _re.search(r"win|x64|setup|installer", a["name"], _re.I)]
                    asset = win_assets[0] if win_assets else (assets[0] if assets else None)
                    if asset:
                        url = asset["browser_download_url"]
                        out_path = dest_dir / asset["name"]
                        await asyncio.to_thread(lambda: _ureq.urlretrieve(url, out_path))
                        return {"status": "ok", "method": "github", "file": asset["name"],
                                "destination": str(dest_dir), "size_mb": round(out_path.stat().st_size / 1024**2, 1)}
    except Exception as e:
        pass

    raise HTTPException(
        status_code=404,
        detail=f"Could not download '{name}'. Ensure winget or chocolatey is installed, or provide a direct URL."
    )


# ── Software upload to GitHub releases ───────────────────────────────────────

class SoftwareUploadRequest(BaseModel):
    file_path: str
    release_tag: str
    release_name: Optional[str] = None

@app.post("/admin/software/upload")
async def admin_software_upload(
    req: SoftwareUploadRequest,
    authorization: Optional[str] = _Header(None),
) -> Dict[str, Any]:
    await _require_admin(authorization)
    import requests as _req2

    file_path = Path(req.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {req.file_path}")

    # Load GitHub config
    async with get_db() as db:
        async with db.execute(
            "SELECT key, value FROM preferences WHERE key IN ('gh_owner','gh_repo','gh_token_enc')"
        ) as cur:
            cfg = {r["key"]: r["value"] for r in await cur.fetchall()}

    if not cfg.get("gh_token_enc") or not cfg.get("gh_owner") or not cfg.get("gh_repo"):
        raise HTTPException(status_code=400, detail="GitHub not configured. Set owner, repo, and token in GitHub Settings.")

    token  = _dec(cfg["gh_token_enc"])
    owner  = cfg["gh_owner"]
    repo   = cfg["gh_repo"]
    headers = {"Authorization": f"token {token}", "User-Agent": "AuriOS/1.1", "Accept": "application/vnd.github+json"}

    # Get or create release
    def _get_or_create_release():
        # Try to get existing release by tag
        r = _req2.get(f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{req.release_tag}", headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
        # Create new release
        payload = {"tag_name": req.release_tag, "name": req.release_name or req.release_tag, "draft": False, "prerelease": False}
        r2 = _req2.post(f"https://api.github.com/repos/{owner}/{repo}/releases", json=payload, headers=headers, timeout=15)
        if r2.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create release: {r2.text[:300]}")
        return r2.json()

    try:
        release = await asyncio.to_thread(_get_or_create_release)
        upload_url = release["upload_url"].split("{")[0]
        file_name = file_path.name

        def _upload():
            with open(file_path, "rb") as fh:
                up_headers = {**headers, "Content-Type": "application/octet-stream"}
                r = _req2.post(f"{upload_url}?name={file_name}", data=fh, headers=up_headers, timeout=300)
                return r

        up_r = await asyncio.to_thread(_upload)
        if up_r.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"GitHub upload failed: {up_r.text[:300]}")

        asset = up_r.json()
        # Auto-add to software catalog DB
        slug = "".join(c for c in file_name.lower().split(".")[0] if c.isalnum())
        async with get_db() as db:
            await db.execute(
                "INSERT INTO software_catalog (slug, display_name, filename, url, version, source, status) "
                "VALUES (?, ?, ?, ?, ?, 'github.com', 'available') "
                "ON CONFLICT(slug) DO UPDATE SET url=excluded.url, filename=excluded.filename, status='available', updated_at=CURRENT_TIMESTAMP",
                (slug, file_name, file_name, asset.get("browser_download_url", ""), req.release_tag)
            )
            await db.commit()

        return {"status": "ok", "asset_name": asset.get("name"), "download_url": asset.get("browser_download_url"), "slug": slug}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
