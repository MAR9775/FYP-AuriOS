"""
test_load.py — Performance and load tests for AuriOS backend.

Measures response latency, concurrent request handling, and
database query performance under simulated load conditions.
"""

import pytest
import time
import asyncio
import uuid


class TestResponseLatency:
    """Benchmark API response times against target thresholds."""

    async def test_ping_under_50ms(self, api_client):
        """GET /ping should respond in under 50ms."""
        start = time.perf_counter()
        resp = await api_client.get("/ping")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 50, f"Ping took {elapsed_ms:.1f}ms (target: <50ms)"

    async def test_chat_greeting_under_200ms(self, api_client):
        """POST /chat with a greeting (rule-based, no LLM) should respond in <200ms."""
        start = time.perf_counter()
        resp = await api_client.post("/chat", json={"message": "hello"})
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 200, f"Chat greeting took {elapsed_ms:.1f}ms (target: <200ms)"

    async def test_preferences_read_under_100ms(self, api_client):
        """GET /preferences should respond in <100ms."""
        start = time.perf_counter()
        resp = await api_client.get("/preferences")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 100, f"Preferences took {elapsed_ms:.1f}ms (target: <100ms)"


class TestConcurrentRequests:
    """Test backend stability under concurrent load."""

    async def test_10_concurrent_chat_requests(self, api_client):
        """Backend should handle 10 simultaneous /chat POSTs without errors."""
        async def send_chat(msg):
            return await api_client.post("/chat", json={"message": msg})

        messages = [f"hello {i}" for i in range(10)]
        results = await asyncio.gather(*[send_chat(m) for m in messages])

        for i, resp in enumerate(results):
            assert resp.status_code == 200, f"Request {i} failed with {resp.status_code}"

    async def test_concurrent_signup_unique_emails(self, api_client, test_db):
        """10 concurrent signups with unique emails should all succeed."""
        async def signup(n):
            return await api_client.post("/auth/signup", json={
                "name": f"User {n}",
                "email": f"concurrent_{uuid.uuid4().hex[:8]}_{n}@test.com",
                "password": "pass123"
            })

        results = await asyncio.gather(*[signup(i) for i in range(10)])
        success_count = sum(1 for r in results if r.status_code == 200)
        assert success_count == 10, f"Only {success_count}/10 signups succeeded"


class TestDatabasePerformance:
    """Benchmark database operations."""

    async def test_insert_100_conversations_under_1s(self, test_db):
        """Inserting 100 conversation rows should complete in <1 second."""
        start = time.perf_counter()
        for i in range(100):
            await test_db.execute(
                "INSERT INTO conversations (role, content) VALUES (?, ?)",
                ("user", f"Test message {i}")
            )
        await test_db.commit()
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"100 inserts took {elapsed:.2f}s (target: <1s)"

    async def test_query_conversations_under_50ms(self, test_db):
        """SELECT last 50 conversations should complete in <50ms."""
        # Seed data
        for i in range(200):
            await test_db.execute(
                "INSERT INTO conversations (role, content) VALUES (?, ?)",
                ("user", f"Message {i}")
            )
        await test_db.commit()

        start = time.perf_counter()
        async with test_db.execute(
            "SELECT * FROM conversations ORDER BY timestamp DESC LIMIT 50"
        ) as cursor:
            rows = await cursor.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(rows) == 50
        assert elapsed_ms < 50, f"Query took {elapsed_ms:.1f}ms (target: <50ms)"
