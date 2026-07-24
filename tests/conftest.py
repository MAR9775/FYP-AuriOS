"""
conftest.py — Shared pytest fixtures for the AuriOS test suite.

Provides reusable fixtures for database connections, test clients,
mock agents, and authentication helpers used across all test modules.
"""

import os
import sys
import pytest
import asyncio
import aiosqlite
from pathlib import Path

# Ensure the project root is on sys.path so `backend.*` imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# In-memory SQLite database fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def test_db(tmp_path):
    """
    Provide a temporary SQLite database with the full AuriOS schema.
    Yields an aiosqlite connection. Automatically cleaned up after test.
    """
    db_path = tmp_path / "test_aurjos.db"
    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")

        await db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                role TEXT, content TEXT, metadata TEXT
            );
            CREATE TABLE IF NOT EXISTS preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE, value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS installation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                preset_name TEXT, software TEXT, status TEXT,
                duration_s REAL, error_log TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, preset TEXT, status TEXT DEFAULT 'pending',
                progress INTEGER DEFAULT 0, current_step TEXT,
                final_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, role TEXT DEFAULT 'user',
                status TEXT DEFAULT 'active',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS software_catalog (
                slug TEXT PRIMARY KEY, display_name TEXT, filename TEXT,
                url TEXT, version TEXT, category TEXT, source TEXT,
                status TEXT DEFAULT 'available',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()
        yield db


# ---------------------------------------------------------------------------
# FastAPI async test client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def api_client():
    """
    Provide an httpx AsyncClient pointed at the FastAPI test app.
    Requires `httpx` to be installed: pip install httpx
    """
    try:
        from httpx import AsyncClient, ASGITransport
        from backend.server import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver"
        ) as client:
            yield client
    except ImportError:
        pytest.skip("httpx not installed — run: pip install httpx")


# ---------------------------------------------------------------------------
# Rate limit isolation — prevents state bleed between security tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Clear in-memory login attempt counters before each test."""
    try:
        from backend import server
        server._login_attempts.clear()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        from backend import server
        server._login_attempts.clear()
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Auth helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_headers():
    """Return Authorization headers for the system admin (for tests that mock auth)."""
    return {"Authorization": "Bearer admin_test_token_for_testing"}


@pytest.fixture
def user_headers():
    """Return Authorization headers for a regular user (for tests that mock auth)."""
    return {"Authorization": "Bearer user_test_token_for_testing"}


# ---------------------------------------------------------------------------
# Environment flags
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def force_simulation_mode(monkeypatch, request):
    """
    Force simulation mode so no real installers run during tests.
    Skipped for tests explicitly marked with 'no_simulation'.
    """
    if "no_simulation" in request.keywords:
        return
    monkeypatch.setenv("AURIOS_SIMULATE_INSTALL", "1")
