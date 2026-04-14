"""Intent parser for AuriOS.

Uses a deterministic rule-based classifier for install intents (keyword matching
on the user message), and falls back to Ollama only for conversational replies
or unclear inputs. The LLM is still used to generate the natural-language
``response_text`` in the user's language, but the intent itself comes from rules
because small local models (e.g. llama3.2:1b) cannot reliably emit a strict
enum in JSON.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# ---------------------------------------------------------------------------
# Canonical vocabulary
# ---------------------------------------------------------------------------

_PRESET_INTENTS = {
    "python_basic", "python_ml", "web_dev",
    "full_stack", "data_science", "java",
}

_ALL_INTENTS = _PRESET_INTENTS | {
    "single_software", "database_clarify",
    "greeting", "help", "thanks", "goodbye", "unknown",
}

# Aliases commonly invented by small models — mapped to canonical intents.
_INTENT_ALIASES = {
    "install_python": "single_software",
    "install_git": "single_software",
    "install_nodejs": "single_software",
    "install_node": "single_software",
    "install_docker": "single_software",
    "install_java": "single_software",
    "install_vscode": "single_software",
    "install_intent": "single_software",
    "install": "single_software",
    "full_python_dev": "python_basic",
    "python_dev": "python_basic",
    "python_development": "python_basic",
    "ml": "python_ml",
    "ai": "python_ml",
    "machine_learning": "python_ml",
    "webdev": "web_dev",
    "fullstack": "full_stack",
    "datascience": "data_science",
    "hi": "greeting",
    "hello": "greeting",
}

# ---------------------------------------------------------------------------
# Rule-based classifier
# ---------------------------------------------------------------------------

_QUESTION_STARTS = re.compile(
    r"^\s*(how|why|should|is|can|could|would|does|do|what|where|which)\b",
    re.IGNORECASE,
)
_NEGATIVE_FILTER = re.compile(r"\b(un ?install|remove|delete|uninstalling|removing)\b", re.IGNORECASE)
_STATUS_QUERY = re.compile(r"\bis\b.*\binstalled\b", re.IGNORECASE)

_INSTALL_VERBS = re.compile(
    r"\b(install|setup|set\s*up|download|get\s*me|gimme|"
    r"need|want|chahiye|chahye|chaahiye|laga\s*do|install\s*karo|install\s*kar|de\s*do|bana\s*do)\b",
    re.IGNORECASE,
)

# Presets are checked BEFORE single software because they're more specific.
_PRESET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bfull\s*stack\b|\beverything\b|\ball\s*tools?\b|\bcomplete\s*(dev|setup)\b", re.I), "full_stack"),
    (re.compile(r"\bpython\b.*\b(ml|machine\s*learning|tensorflow|pytorch|ai)\b|\b(ml|ai)\b.*\bpython\b", re.I), "python_ml"),
    (re.compile(r"\bdata\s*science\b|\b(pandas|numpy|jupyter|matplotlib)\b", re.I), "data_science"),
    (re.compile(r"\b(web\s*dev|frontend|front[-\s]end|react|angular|vue)\b", re.I), "web_dev"),
    # Unordered java-setup: "java setup" or "setup java"
    (re.compile(r"(\bjava\b.*\b(setup|environment|dev)\b)|(\b(setup|environment|dev)\b.*\bjava\b)", re.I), "java"),
    # Unordered python basic: "python setup" or "setup python" or "python dev"
    (re.compile(r"(\bpython\b.*\b(setup|environment|dev|basic)\b)|(\b(setup|environment|dev|basic)\b.*\bpython\b)|\bpython\s*dev\b", re.I), "python_basic"),
]

# Single software — checked ONLY if no preset matched. Order matters: "node" before "python"
# so "install node and python" doesn't wrongly pick python first.
_SOFTWARE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bnode(\.?js)?\b|\bnpm\b", re.I), "nodejs"),
    (re.compile(r"\bvs\s*code\b|\bvisual\s*studio\s*code\b", re.I), "vscode"),
    (re.compile(r"\bdocker\b", re.I), "docker"),
    (re.compile(r"\b(java|jdk)\b", re.I), "java"),
    (re.compile(r"\bmysql\b", re.I), "mysql"),
    (re.compile(r"\bpostgres(ql)?\b", re.I), "postgresql"),
    (re.compile(r"\bmongo(db)?\b", re.I), "mongodb"),
    (re.compile(r"\bredis\b", re.I), "redis"),
    (re.compile(r"\bpostman\b", re.I), "postman"),
    (re.compile(r"\bgit\b", re.I), "git"),
    (re.compile(r"\bpython\b", re.I), "python"),
]


def _rule_based_intent(text: str) -> Optional[Dict[str, Any]]:
    """Deterministic intent classification for install requests.

    Returns None if the message is conversational or ambiguous — the caller
    will then fall through to the LLM for a natural reply.
    """
    if not text or not text.strip():
        return None

    # Short-circuit: questions, negatives, and status queries are never installs.
    if _QUESTION_STARTS.match(text):
        return None
    if _NEGATIVE_FILTER.search(text):
        return None
    if _STATUS_QUERY.search(text):
        return None

    # Must contain an install verb to count as an install request.
    if not _INSTALL_VERBS.search(text):
        return None

    # Presets first (most specific wins).
    for pattern, preset in _PRESET_PATTERNS:
        if pattern.search(text):
            return {
                "intent": preset,
                "preset_or_software": preset,
                "needs_clarification": False,
            }

    # Then single software keywords.
    for pattern, software in _SOFTWARE_PATTERNS:
        if pattern.search(text):
            return {
                "intent": "single_software",
                "preset_or_software": software,
                "needs_clarification": False,
            }

    # Install verb but no software keyword — let the LLM ask a clarifying question.
    return None


def _normalize_intent(raw: Any) -> str:
    """Map LLM-invented intent strings to the canonical vocabulary."""
    if not isinstance(raw, str):
        return "unknown"
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if key in _ALL_INTENTS:
        return key
    return _INTENT_ALIASES.get(key, "unknown")


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

_CONFIRM_PROMPT = (
    "You are Auri, a friendly developer-tools assistant on Windows. "
    "The user just asked you to install or set up some software and the "
    "system has already confirmed the request. Reply in ONE short, "
    "enthusiastic sentence confirming you're starting the setup now. "
    "Reply in the SAME language and script the user used — if they wrote "
    "English, reply in English. Never switch scripts. "
    "Do NOT mention JSON, intents, or classification."
)

_CONVERSATIONAL_PROMPT = (
    "You are Auri, a warm friendly AI assistant for Windows developer setup. "
    "Match the user's language and script exactly (English, Hinglish, or Urdu). "
    "Respond naturally in 1-2 short sentences. "
    "Never switch to a different script (stay in English if they wrote English). "
    "Do NOT mention JSON, intents, or classification. "
    "Return ONLY valid JSON (no markdown): "
    '{"intent":"<greeting|help|thanks|goodbye|unknown>",'
    '"preset_or_software":null,'
    '"needs_clarification":false,'
    '"response_text":"<your reply>"}'
)


def _llm_confirmation_text(user_message: str, software_label: str) -> str:
    """Ask Ollama for a short confirmation sentence in the user's language."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": _CONFIRM_PROMPT},
                    {
                        "role": "user",
                        "content": f"User asked: {user_message!r}. You are starting setup for: {software_label}.",
                    },
                ],
                "stream": False,
                "options": {"temperature": 0.3},
            },
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json()["message"]["content"].strip()
        # Defensive: some tiny models still emit JSON even without format=json
        if text.startswith("{") and text.endswith("}"):
            try:
                j = json.loads(text)
                text = j.get("response_text") or j.get("response") or text
            except Exception:
                pass
        return text or f"Got it! Starting {software_label} setup now. 🚀"
    except Exception:
        return f"Got it! Starting {software_label} setup now. Watch the progress panel! 🚀"


def _llm_conversational(user_message: str) -> Dict[str, Any]:
    """Ask Ollama for a conversational reply (greeting/help/etc.)."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": _CONVERSATIONAL_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2},
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        result: Dict[str, Any] = json.loads(raw)
        return {
            "intent": _normalize_intent(result.get("intent", "unknown")),
            "preset_or_software": result.get("preset_or_software"),
            "needs_clarification": bool(result.get("needs_clarification", False)),
            "response_text": result.get("response_text") or "How can I help you today? 😊",
        }
    except requests.exceptions.ConnectionError:
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": (
                "I can't reach my brain right now! Make sure Ollama is running "
                "(try: ollama serve) and try again. 🧠"
            ),
        }
    except (requests.exceptions.Timeout, requests.exceptions.HTTPError) as e:
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": f"Ollama had trouble responding ({e}). Please try again. 😅",
        }
    except (json.JSONDecodeError, KeyError):
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": "Sorry, I got confused for a second — could you rephrase that? 🤔",
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_SOFTWARE_LABELS = {
    "python": "Python",
    "nodejs": "Node.js",
    "git": "Git",
    "vscode": "VS Code",
    "docker": "Docker",
    "java": "Java",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "postman": "Postman",
    "python_basic": "Python basics",
    "python_ml": "Python ML",
    "web_dev": "web dev",
    "full_stack": "full stack",
    "data_science": "data science",
}


def parse_intent(text: str) -> Dict[str, Any]:
    """Return a structured intent + natural-language reply for ``text``.

    1. Run the rule-based classifier first. If it matches an install intent,
       the intent/software fields are authoritative and we only use the LLM
       to generate a friendly confirmation sentence.
    2. Otherwise, hand the message to the LLM for conversational handling.
    """
    ruled = _rule_based_intent(text)
    if ruled is not None:
        software = ruled["preset_or_software"]
        label = _SOFTWARE_LABELS.get(software, software)
        reply = _llm_confirmation_text(text, label)
        return {
            "intent": ruled["intent"],
            "preset_or_software": software,
            "needs_clarification": False,
            "response_text": reply,
        }

    # No install intent → go conversational via LLM.
    return _llm_conversational(text)
