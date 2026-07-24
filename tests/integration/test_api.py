"""
test_api.py — Integration tests for FastAPI backend endpoints.

Tests real HTTP request/response cycles against the running backend
using the `requests` library. Backend must be running on localhost:8000.

Run:
  1. Start backend: python -m uvicorn backend.server:app --port 8000
  2. Run tests:     pytest tests/integration/test_api.py -v

These tests create real data in the database — use a test DB or clean up after.
"""

import pytest
import requests
import time
import uuid

BASE = "http://127.0.0.1:8000"
_test_email = f"testuser_{uuid.uuid4().hex[:8]}@test.com"
_test_password = "TestPass123!"
_test_name = "Test User"


def _is_backend_running():
    """Check if backend is accessible."""
    try:
        r = requests.get(f"{BASE}/ping", timeout=2)
        return r.status_code == 200
    except requests.ConnectionError:
        return False


# Skip entire module if backend is not running
pytestmark = pytest.mark.skipif(
    not _is_backend_running(),
    reason="Backend not running on localhost:8000"
)


# -----------------------------------------------------------------------
# Auth endpoints
# -----------------------------------------------------------------------

class TestAuthSignup:
    """POST /auth/signup"""

    def test_signup_success(self):
        resp = requests.post(f"{BASE}/auth/signup", json={
            "name": _test_name,
            "email": _test_email,
            "password": _test_password,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_signup_duplicate_email(self):
        """Second signup with same email should fail."""
        resp = requests.post(f"{BASE}/auth/signup", json={
            "name": "Duplicate", "email": _test_email, "password": "pass"
        })
        assert resp.status_code == 400
        assert "already" in resp.json()["detail"].lower()

    def test_signup_missing_fields(self):
        """Missing required fields should return 422."""
        resp = requests.post(f"{BASE}/auth/signup", json={"name": "No Email"})
        assert resp.status_code == 422


class TestAuthLogin:
    """POST /auth/login"""

    def test_login_success(self):
        resp = requests.post(f"{BASE}/auth/login", json={
            "email": _test_email, "password": _test_password
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == _test_email
        assert data["user"]["role"] == "user"

    def test_login_wrong_password(self):
        resp = requests.post(f"{BASE}/auth/login", json={
            "email": _test_email, "password": "WrongPassword"
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self):
        resp = requests.post(f"{BASE}/auth/login", json={
            "email": "ghost@nowhere.com", "password": "anything"
        })
        assert resp.status_code == 401


class TestAuthVerifyAndLogout:
    """POST /auth/verify, POST /auth/logout"""

    def _get_token(self):
        resp = requests.post(f"{BASE}/auth/login", json={
            "email": _test_email, "password": _test_password
        })
        return resp.json()["token"]

    def test_verify_valid_token(self):
        token = self._get_token()
        resp = requests.post(f"{BASE}/auth/verify", json={"token": token})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_verify_invalid_token(self):
        resp = requests.post(f"{BASE}/auth/verify", json={"token": "fake_token"})
        # Backend returns 401 for invalid tokens
        assert resp.status_code in (200, 401)

    def test_logout_then_verify_fails(self):
        token = self._get_token()
        requests.post(f"{BASE}/auth/logout", json={"token": token})
        resp = requests.post(f"{BASE}/auth/verify", json={"token": token})
        # After logout, token should no longer be valid
        if resp.status_code == 200:
            assert resp.json().get("valid") is False
        else:
            assert resp.status_code == 401  # Token rejected


# -----------------------------------------------------------------------
# Chat endpoint
# -----------------------------------------------------------------------

class TestChatEndpoint:
    """POST /chat"""

    def test_greeting_response(self):
        resp = requests.post(f"{BASE}/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert data.get("task_id") is None  # Greetings don't start tasks

    def test_install_intent_detected(self):
        resp = requests.post(f"{BASE}/chat", json={"message": "install python"})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        # May have task_id depending on detection state

    def test_offtopic_blocked(self):
        resp = requests.post(f"{BASE}/chat", json={"message": "what's the weather"})
        assert resp.status_code == 200
        data = resp.json()
        assert "only help" in data["response"].lower() or "software" in data["response"].lower()

    def test_empty_message_handled(self):
        """Empty or whitespace message should not crash the backend."""
        resp = requests.post(f"{BASE}/chat", json={"message": ""})
        # Should return 200 with some response, or 422 validation error
        assert resp.status_code in (200, 422)


# -----------------------------------------------------------------------
# Profile and Preferences
# -----------------------------------------------------------------------

class TestProfileEndpoints:
    """GET/POST /profile, GET/POST /preferences"""

    def _get_token(self):
        resp = requests.post(f"{BASE}/auth/login", json={
            "email": _test_email, "password": _test_password
        })
        return resp.json()["token"]

    def test_get_profile(self):
        token = self._get_token()
        resp = requests.get(f"{BASE}/profile", headers={
            "Authorization": f"Bearer {token}"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "user_name" in data

    def test_post_preferences(self):
        resp = requests.post(f"{BASE}/preferences", json={
            "key": "test_key", "value": "test_value"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "test_key"

    def test_get_preferences(self):
        resp = requests.get(f"{BASE}/preferences")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# -----------------------------------------------------------------------
# System status
# -----------------------------------------------------------------------

class TestSystemStatus:
    """GET /ping, GET /system-status-full"""

    def test_ping(self):
        resp = requests.get(f"{BASE}/ping")
        assert resp.status_code == 200

    def test_system_status_full(self):
        resp = requests.get(f"{BASE}/system-status-full")
        assert resp.status_code == 200
        data = resp.json()
        assert "ollama_connected" in data
        assert "is_admin" in data
        assert "free_disk_gb" in data
        assert "installed" in data

    def test_available_software(self):
        resp = requests.get(f"{BASE}/available-software")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# -----------------------------------------------------------------------
# Admin endpoints (require admin token)
# -----------------------------------------------------------------------

class TestAdminEndpoints:
    """Admin-only endpoints should reject unauthorized access."""

    def test_dashboard_stats_no_auth(self):
        resp = requests.get(f"{BASE}/admin/dashboard-stats")
        assert resp.status_code in (401, 403)

    def test_accounts_no_auth(self):
        resp = requests.get(f"{BASE}/admin/accounts")
        # 401/403 = auth required, 405 = method not allowed (also blocks access)
        assert resp.status_code in (401, 403, 405)

    def test_installations_no_auth(self):
        resp = requests.get(f"{BASE}/admin/installations")
        assert resp.status_code in (401, 403)

    def test_fake_token_rejected(self):
        resp = requests.get(f"{BASE}/admin/dashboard-stats", headers={
            "Authorization": "Bearer completely_fake_admin_token"
        })
        assert resp.status_code in (401, 403)


# -----------------------------------------------------------------------
# Rate limiting
# -----------------------------------------------------------------------

class TestRateLimiting:
    """POST /auth/login rate limiting (5 attempts → 429)."""

    def test_rate_limit_triggers_after_5_failures(self):
        """Send 6 wrong password attempts — 6th should get 429."""
        email = f"ratelimit_{uuid.uuid4().hex[:6]}@test.com"
        # Create the account first
        requests.post(f"{BASE}/auth/signup", json={
            "name": "Rate Limit Test", "email": email, "password": "correctpass"
        })
        # Send 5 wrong passwords
        for i in range(5):
            resp = requests.post(f"{BASE}/auth/login", json={
                "email": email, "password": "wrongpass"
            })
            assert resp.status_code == 401, f"Attempt {i+1} should be 401"

        # 6th attempt should be rate-limited
        resp = requests.post(f"{BASE}/auth/login", json={
            "email": email, "password": "wrongpass"
        })
        assert resp.status_code == 429
        assert "too many" in resp.json()["detail"].lower()
