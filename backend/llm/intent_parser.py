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
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

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

    # Install verb present but no known keyword matched — try to extract the
    # software name so the availability check in server.py can give a clear
    # "not in repo" message instead of letting the LLM hallucinate a result.
    slug = _extract_slug(text)
    if slug:
        return {
            "intent": "single_software",
            "preset_or_software": slug,
            "needs_clarification": False,
        }

    # No software name extractable — ask clarifying question via LLM.
    return None


_INSTALL_VERB_SPLIT = re.compile(
    r"\b(?:install|setup|set\s*up|download|get\s*me|gimme|need|want|"
    r"chahiye|chahye|chaahiye|laga\s*do|install\s*karo|install\s*kar|de\s*do|bana\s*do)\s+",
    re.IGNORECASE,
)
_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


def _extract_slug(text: str) -> Optional[str]:
    """Pull the first word after an install verb and normalise to a slug."""
    m = _INSTALL_VERB_SPLIT.search(text)
    if not m:
        return None
    remainder = text[m.end():].strip()
    # Take only the first word (e.g. "vlc media player" → "vlc")
    first_word = remainder.split()[0] if remainder.split() else ""
    slug = _SLUG_CLEAN.sub("", first_word.lower())
    return slug if len(slug) >= 2 else None


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

_SYSTEM_PROMPT = """You are AuriOS, an AI assistant whose ONLY job is helping users install developer software on Windows.

STRICT RULES — follow every one without exception:
1. You ONLY discuss installing or setting up software (Python, Git, VS Code, Docker, Node.js, Java, MySQL, PostgreSQL, MongoDB, Redis, Postman, VLC, Rufus, 7-Zip, Notepad++).
2. If the user asks about ANYTHING else (weather, news, sports, jokes, recipes, general knowledge), reply with exactly: "I can only help with installing developer software. Try saying 'install Python' or 'show available software'."
3. Keep every reply to 1-2 sentences maximum.
4. NEVER invent facts, software names, version numbers, URLs, or features.
5. NEVER pretend to perform actions you cannot do (browsing the web, checking weather, running code).
6. If you do not know something, say "I don't know."
7. Reply in the same language the user used (English, Hinglish, or Urdu). Never switch languages mid-reply.
8. Do NOT output JSON, markdown, bullet points, or any structured format — plain text only.
9. If asked who made you, say: "I was built by The Automators team."
10. Do NOT repeat the user's message back to them."""

# ---------------------------------------------------------------------------
# URL / domain detector — never send raw URLs to the LLM
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"^\s*(https?://\S+|\S+\.(com|org|net|io|dev|app|edu|gov|co)\s*)$",
    re.IGNORECASE,
)


def _is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


# ---------------------------------------------------------------------------
# "Show available software" detector
# ---------------------------------------------------------------------------

_LIST_SOFTWARE_RE = re.compile(
    r"\b(show|list|display|see|view|tell|give)\b.{0,40}\b(software|tools?|programs?|apps?|packages?|available)\b"
    r"|\bwhat.{0,30}\b(can you install|do you (have|support|offer)|is available)\b"
    r"|\bavailable\s+(software|tools?|apps?|in\s+(repo|repository))\b"
    r"|\b(repo|repository)\s*(list|catalog|software)?\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pre-canned responses for ultra-common phrases — avoids LLM entirely
# ---------------------------------------------------------------------------

_OFFTOPIC_REPLY = (
    "I'm AuriOS — I can only help with installing developer software on Windows. "
    "Try 'install Python', 'install Git', or 'show available software'."
)

_GENERAL_FALLBACK = (
    "I'm AuriOS, your Windows dev-environment assistant! "
    "I can install software like Python, Git, VS Code, Docker, and more. "
    "Try: 'install Python' or 'show available software'."
)

_UNKNOWN_FALLBACK = (
    "I didn't quite understand that. "
    "Try saying 'install [software name]' or 'show available software' to see what I can install."
)

_INSTALL_HINT = "Try 'install Python', 'install Git', 'install VS Code', or 'show available software'."

_CANNED: dict[str, str] = {
    # Greetings
    "hi":                        "Hi! I'm AuriOS — I install developer software on Windows. " + _INSTALL_HINT,
    "hello":                     "Hello! I'm AuriOS, your dev-environment assistant. " + _INSTALL_HINT,
    "hey":                       "Hey! Ready to set up some software? " + _INSTALL_HINT,
    "yo":                        "Hey! What software can I install for you?",
    "sup":                       "Hey! What software can I install for you?",
    "hiya":                      "Hi there! What would you like to install?",
    # State / small talk
    "how are you":               "All systems go! What would you like to install today?",
    "how are you doing":         "Running great! What software can I set up for you?",
    "hows it going":             "Going well! What can I install for you?",
    "how's it going":            "Going well! What can I install for you?",
    "what's up":                 "Not much — ready to install some software! " + _INSTALL_HINT,
    "whats up":                  "Not much — ready to install some software! " + _INSTALL_HINT,
    "i hope you are doing good": "Thanks! I'm here to help. " + _INSTALL_HINT,
    "i hope you are doing well": "Thanks! What software can I set up for you?",
    "i hope you are well":       "Thanks! What software can I set up for you today?",
    "good morning":              "Good morning! What software can I install for you today?",
    "good afternoon":            "Good afternoon! What software can I install for you today?",
    "good evening":              "Good evening! What software can I install for you today?",
    # Off-topic weather
    "hows the weather":          _OFFTOPIC_REPLY,
    "how's the weather":         _OFFTOPIC_REPLY,
    "what's the weather":        _OFFTOPIC_REPLY,
    "what is the weather":       _OFFTOPIC_REPLY,
    "weather":                   _OFFTOPIC_REPLY,
    # Acknowledgements
    "thanks":                    "You're welcome! Let me know if you need anything else installed.",
    "thank you":                 "Happy to help! Let me know what else you need.",
    "thx":                       "No problem! Let me know what else you need.",
    "ok":                        "Got it! Just say what you'd like to install.",
    "okay":                      "Got it! Just say what you'd like to install.",
    "ok cool":                   "Great! Let me know what you'd like to install next.",
    "got it":                    "Let me know whenever you're ready to install something!",
    "sounds good":               "Let me know whenever you're ready to install something!",
    "great":                     "Let me know what software you'd like to set up next.",
    "awesome":                   "Let me know what software you'd like to set up next.",
    "nice":                      "What else can I install for you?",
    "cool":                      "What else can I install for you?",
    "perfect":                   "Let me know what you'd like to install next.",
    # Yes / No
    "yes":                       "Sure! What software would you like me to install? " + _INSTALL_HINT,
    "yeah":                      "Sure! What would you like to install?",
    "yep":                       "Sure! What would you like to install?",
    "yup":                       "Sure! What would you like to install?",
    "no":                        "No problem! Let me know if you need anything installed.",
    "nope":                      "No problem! Let me know if you need anything installed.",
    "nah":                       "No problem! Let me know if you need anything installed.",
    # Farewells
    "bye":                       "Goodbye! Come back whenever you need software installed. 👋",
    "goodbye":                   "Goodbye! 👋",
    "see you":                   "See you! 👋",
    "take care":                 "Take care! 👋",
    "cya":                       "See you! 👋",
    "ttyl":                      "Talk later! 👋",
    # Help
    "help":                      "I install developer software on Windows. " + _INSTALL_HINT,
    "what can you do":           "I install developer software on Windows. " + _INSTALL_HINT,
    "what do you do":            "I install developer software on Windows. " + _INSTALL_HINT,
    "who are you":               "I'm AuriOS — an AI assistant that installs developer software on Windows. " + _INSTALL_HINT,
    "what are you":              "I'm AuriOS — an AI assistant that installs developer software on Windows. " + _INSTALL_HINT,
}

# Off-topic question patterns — return _OFFTOPIC_REPLY without hitting the LLM.
_OFFTOPIC_RE = re.compile(
    r"\b(weather|temperature|forecast|rain|sunny|hot|cold|climate|"
    r"news|sports|score|match|game|movie|film|song|music|lyrics|"
    r"joke|story|poem|write\s+me|tell\s+me\s+a|"
    r"who\s+(won|is\s+the\s+president|is\s+the\s+pm)|"
    r"what\s+time\s+is|what\s+day\s+is|what\s+is\s+the\s+date|"
    r"capital\s+of|population\s+of|how\s+far|distance\s+to|"
    r"translate|meaning\s+of|define\b|synonym|"
    r"recipe|cook|food|restaurant|"
    r"stock\s+price|bitcoin|crypto)\b",
    re.IGNORECASE,
)


def _canned_reply(text: str) -> Optional[str]:
    """Return a pre-canned response for very simple inputs, or None."""
    key = text.strip().lower().rstrip("!?.,:;")
    # Exact match first
    if key in _CANNED:
        return _CANNED[key]
    # Off-topic question catch-all
    if _OFFTOPIC_RE.search(text) and not _INSTALL_VERBS.search(text):
        return _OFFTOPIC_REPLY
    return None


# ---------------------------------------------------------------------------
# LLM response sanitiser — strip template placeholders from model output
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"<[^>]{3,120}>")  # e.g. <current weather conditions>


def _sanitize(text: str) -> str:
    """Remove template placeholder artifacts that tiny models emit."""
    cleaned = _TEMPLATE_RE.sub("", text).strip()
    # If the whole reply was a placeholder, return the fallback
    return cleaned if len(cleaned) > 10 else _OFFTOPIC_REPLY


# ---------------------------------------------------------------------------
# General-conversation detector
# ---------------------------------------------------------------------------

# Patterns that clearly signal casual / small-talk (not an install command).
_GENERAL_CONV_RE = re.compile(
    r"^\s*("
    # Greetings
    r"hi\b|hey\b|hello\b|howdy|sup\b|what'?s up|how are you|how'?s it going|"
    r"good\s+(morning|afternoon|evening|night|day)|greetings|"
    r"namaste|assalam|salam|salaam|"
    # Questions about the bot
    r"who are you|what are you|what'?s your name|introduce yourself|"
    r"what can you do|what do you (do|know)|tell me about yourself|"
    r"are you (an? )?(ai|bot|assistant)|"
    # Small talk / humour
    r"how'?s it|what'?s going on|"
    r"tell me (a )?joke|say something funny|make me laugh|be funny|"
    r"give me a (quote|fact|tip)|"
    # Acknowledgements
    r"thanks|thank you|thx|ty\b|ok(ay)?[\s,!.]*cool|"
    r"got it|noted|sounds good|great|awesome|nice|perfect|cool\b|"
    r"interesting|wow\b|haha|lol\b|"
    # Farewells
    r"bye\b|goodbye|see you|take care|ciao|ttyl|talk later"
    r")\b",
    re.IGNORECASE,
)


def _is_general_conversation(text: str) -> bool:
    """Return True if the message is clearly casual with no install intent."""
    # If there's an install verb anywhere, let the install path decide.
    if _INSTALL_VERBS.search(text):
        return False
    return bool(_GENERAL_CONV_RE.search(text))


def _llm_chat(user_message: str) -> Dict[str, Any]:
    """Single LLM call for all conversational responses using the strict system prompt."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "top_p": 0.9, "num_predict": 100, "repeat_penalty": 1.1},
            },
            timeout=60,
        )
        resp.raise_for_status()
        reply = resp.json()["message"]["content"].strip()
        # Strip any JSON the model might still emit
        if reply.startswith("{"):
            try:
                j = json.loads(reply)
                reply = j.get("response_text") or j.get("response") or j.get("content") or reply
            except Exception:
                pass
        return {
            "intent": "general_chat",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": _sanitize(reply) if reply else _GENERAL_FALLBACK,
        }
    except requests.exceptions.ConnectionError:
        return {
            "intent": "general_chat",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": (
                "I can't reach Ollama right now. "
                "Make sure it's running with: ollama serve"
            ),
        }
    except Exception:
        return {
            "intent": "general_chat",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": _GENERAL_FALLBACK,
        }


def _llm_conversational(user_message: str) -> Dict[str, Any]:
    """Legacy — delegates to _llm_chat."""
    return _llm_chat(user_message)


def _llm_general_chat(user_message: str) -> Dict[str, Any]:
    """Legacy — delegates to _llm_chat."""
    return _llm_chat(user_message)


def _llm_conversational_json(user_message: str) -> Dict[str, Any]:
    """Structured JSON path — kept for reference but not used in routing."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 120},
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
            "response_text": _sanitize(result.get("response_text") or "") or _GENERAL_FALLBACK,
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

    Routing:
    1. URL/domain inputs → fixed reply, no LLM.
    2. Pre-canned greetings/acks → fixed reply, no LLM.
    3. "Show available software" → list_software intent, no LLM.
    4. Rule-based install classifier → only confirmation sentence from LLM.
    5. General-conversation detector → free-form Ollama call.
    6. Everything else → JSON-structured LLM fallback.
    """
    # ── Stage 1: URL / domain — never hallucinate about external sites ────────
    if _is_url(text):
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": (
                "I can only help with installing developer software. "
                "Try saying 'install Python' or 'show available software'."
            ),
        }

    # ── Stage 2: pre-canned responses (greetings, acks, yes/no) ─────────────
    canned = _canned_reply(text)
    if canned:
        return {
            "intent": "general_chat",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": canned,
        }

    # ── Stage 3: show available software ─────────────────────────────────────
    if _LIST_SOFTWARE_RE.search(text) and not _INSTALL_VERBS.search(text):
        return {
            "intent": "list_software",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": "__LIST__",  # server.py replaces this with real catalog
        }

    # ── Stage 4: rule-based install detection ────────────────────────────────
    ruled = _rule_based_intent(text)
    if ruled is not None:
        software = ruled["preset_or_software"]
        # server.py always overrides response_text for install intents,
        # so we never call the LLM here — it would be thrown away anyway.
        return {
            "intent": ruled["intent"],
            "preset_or_software": software,
            "needs_clarification": False,
            "response_text": "",
        }

    # ── Stage 5 & 6: LLM with strict system prompt ───────────────────────────
    # Guardrails already fired above (URL block, off-topic regex, canned
    # responses) so only genuinely ambiguous messages reach here.
    return _llm_chat(text)
