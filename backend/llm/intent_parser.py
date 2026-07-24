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
# Category Intent Mapping
# ---------------------------------------------------------------------------

_CATEGORY_MAP = {
    "database": ["MySQL", "PostgreSQL", "MongoDB", "Redis"],
    "ml": ["Python", "TensorFlow", "PyTorch", "scikit-learn"],
    "coding": ["VS Code", "Python", "Node.js", "Java", "Git"],
    "api": ["Postman", "Node.js"],
    "devops": ["Docker", "Git"],
    "design": [],
}

_CATEGORY_PATTERNS = [
    (re.compile(r"\b(database|sql|nosql|db|storage|data\s*store)\b", re.I), "database"),
    (re.compile(r"\b(ml|ai|machine\s*learning|deep\s*learning|data\s*science|neural\s*network)\b", re.I), "ml"),
    (re.compile(r"\b(coding|programming|ide|editor|development\s*environment|code)\b", re.I), "coding"),
    (re.compile(r"\b(design|ui|ux|graphics|vector|image)\b", re.I), "design"),
    (re.compile(r"\b(api|rest|graphql|endpoints)\b", re.I), "api"),
    (re.compile(r"\b(devops|containers|deployment|ci/cd|version\s*control)\b", re.I), "devops"),
]

_CATEGORY_CONVERSATIONS = {
    "database": "If you're setting up a database, I've got a few great options for you. I can install {tools}. What kind of data are you working with?",
    "ml": "For machine learning, having the right environment is key! I can set up {tools} for you. Ready to get started?",
    "coding": "Awesome, let's get your coding setup ready. I can install popular tools like {tools}. What language are you planning to write in?",
    "design": "I mostly focus on developer tools right now, so I don't have specific design software like Figma or Photoshop in my repo yet. Is there anything else you need?",
    "api": "Working with APIs? Nice! I can set up {tools} to help you build and test your endpoints. Which one do you need?",
    "devops": "For devops and deployments, I can help you install {tools}. Would you like me to set any of those up?"
}

_PROJECT_CLARIFY_RE = re.compile(r"\b(software|tools?|apps?|programs?|project|setup|need|want|have|recommend|suggest)\b", re.I)


# ---------------------------------------------------------------------------
# Touch Point 1 — Pre-install explanation (3b generates, rules decide)
# ---------------------------------------------------------------------------

def _llm_explain_preset(user_message: str, tools: list, category: str) -> str:
    """Ask 3b to explain the tools and ask for confirmation.
    Falls back to the hardcoded string if Ollama is unavailable or slow."""
    tools_str = ", ".join(tools)
    fallback = _CATEGORY_CONVERSATIONS.get(category, "").replace("{tools}", tools_str)
    if not fallback:
        fallback = f"I can set up {tools_str} for you. Ready to get started?"

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are AuriOS, a Windows developer environment assistant. "
                            f"The user wants to set up a {category} environment. "
                            f"The tools that will be installed are: {tools_str}. "
                            "In 2-3 sentences: briefly explain what each tool is for, "
                            "then ask if they want to proceed. "
                            "Do NOT suggest any other tools. "
                            "Do NOT ask questions about their project. "
                            "Plain text only, no markdown, no bullet points."
                        ),
                    },
                    {"role": "user", "content": user_message},
                ],
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 120, "repeat_penalty": 1.1},
            },
            timeout=15,
        )
        resp.raise_for_status()
        reply = resp.json()["message"]["content"].strip()
        # Strip any JSON the model might emit
        if reply.startswith("{"):
            try:
                j = json.loads(reply)
                reply = j.get("response_text") or j.get("content") or reply
            except Exception:
                pass
        return reply if len(reply) > 20 else fallback
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Touch Point 2 — Post-install completion message (3b generates)
# ---------------------------------------------------------------------------

def _llm_completion_message(preset: str, software_list: list,
                             pip_packages: list, duration_s: float) -> str:
    """Ask 3b to generate a helpful completion message after a successful install.
    Falls back to a plain string if Ollama is unavailable."""
    fallback = f"Your {preset.replace('_', ' ')} environment is ready. Everything installed successfully in {duration_s}s."

    all_tools = software_list + pip_packages
    tools_str = ", ".join(all_tools)

    # Build a practical "how to start" hint per preset
    start_hints = {
        "python_basic":  "open a terminal and type: python --version",
        "python_ml":     "open a terminal and type: jupyter notebook",
        "web_dev":       "open a terminal and type: node --version",
        "data_science":  "open a terminal and type: jupyter notebook",
        "full_stack":    "open VS Code and start your project",
        "java":          "open a terminal and type: java --version",
    }
    hint = start_hints.get(preset, "open a terminal to get started")

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are AuriOS. You just finished a successful installation. "
                            f"Installed: {tools_str}. "
                            f"Total time: {duration_s} seconds. "
                            f"To get started: {hint}. "
                            "In 2-3 sentences: confirm what's ready, give the exact "
                            "command to get started, and add one encouraging sentence. "
                            "Be specific and practical. Plain text only, no markdown."
                        ),
                    },
                    {"role": "user", "content": "Installation done?"},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 100, "repeat_penalty": 1.1},
            },
            timeout=15,
        )
        resp.raise_for_status()
        reply = resp.json()["message"]["content"].strip()
        if reply.startswith("{"):
            try:
                j = json.loads(reply)
                reply = j.get("response_text") or j.get("content") or reply
            except Exception:
                pass
        return reply if len(reply) > 20 else fallback
    except Exception:
        return fallback

def _detect_category_intent(text: str) -> Optional[Dict[str, Any]]:
    # Check if the text matches a category keyword
    matched_category = None
    for pattern, category in _CATEGORY_PATTERNS:
        if pattern.search(text):
            matched_category = category
            break
            
    # If a category matches AND the user implies a need for tools/setup:
    if matched_category and _PROJECT_CLARIFY_RE.search(text):
        tools = _CATEGORY_MAP[matched_category]
        # Touch Point 1: ask 3b to explain the tools in context of what the
        # user said. Falls back to the hardcoded string if Ollama is offline.
        response_text = _llm_explain_preset(text, tools, matched_category)
        return {
            "intent": "category_query",
            "preset_or_software": matched_category,
            "needs_clarification": False,
            "response_text": response_text,
        }
        
    # Check if a specific software or preset is mentioned. If so, return None and let Stage 4 handle it.
    for pattern, _ in _PRESET_PATTERNS:
        if pattern.search(text):
            return None
    for pattern, _ in _SOFTWARE_PATTERNS:
        if pattern.search(text):
            return None
            
    # Unclear intent: user mentions "project", "software", or "tools" without a clear category or specific software
    if re.search(r"\b(project|software|tools)\b", text, re.I):
        if re.search(r"\b(need|want|have|any|building|creating|set\s*up)\b", text, re.I):
            return {
                "intent": "category_query",
                "preset_or_software": "unclear",
                "needs_clarification": True,
                "response_text": "What kind of project are you building? For example, is it a web app, a machine learning model, or a database?",
            }
            
    return None

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
    (re.compile(r"\bfull\s*stack\b|\ball\s*tools?\b|\bcomplete\s*(dev|setup)\b", re.I), "full_stack"),
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
    (re.compile(r"\blm(\s*studio)?\b", re.I), "lm"),
    (re.compile(r"\b(oracle|virtualbox|vbox)\b", re.I), "oracle"),
    # Additional catalog tools
    (re.compile(r"\beverything\b", re.I), "everything"),
    (re.compile(r"\bwiztree\b", re.I), "wiztree"),
    (re.compile(r"\bwindsurf\b", re.I), "windsurf"),
    (re.compile(r"\bgreenshot\b", re.I), "greenshot"),
    (re.compile(r"\bgithub\s*desktop\b", re.I), "githubdesktop"),
    (re.compile(r"\bdbeaver\b", re.I), "dbeaver"),
    (re.compile(r"\b\.?net\b|dotnet\b", re.I), "dotnet"),
    (re.compile(r"\bnotion\b", re.I), "notion"),
    (re.compile(r"\bpowertoys\b", re.I), "powertoys"),
    (re.compile(r"\brufus\b", re.I), "rufus"),
    (re.compile(r"\b7.?zip\b", re.I), "7zip"),
    (re.compile(r"\bnotepad\+\+\b|\bnotepadpp\b", re.I), "notepadpp"),
    (re.compile(r"\bvlc\b", re.I), "vlc"),
    (re.compile(r"\bpython\b", re.I), "python"),
]

# Card-prompt patterns — direct matches for the 6 preset cards that bypass
# the install-verb requirement. These fire before the verb check so that
# prompts like "Create a new React project" and "Configure a PostgreSQL
# database" route correctly without needing the word "install".
_CARD_PROMPT_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # (pattern, intent, preset_or_software)
    (re.compile(r"\bcreate\b.{0,30}\breact\b|\breact\b.{0,30}\bproject\b|\bnew\s+react\b", re.I), "web_dev", "web_dev"),
    (re.compile(r"\bconfigure\b.{0,40}\b(postgres|postgresql|database|db)\b|\bpostgres\b.{0,30}\b(configure|setup|set\s*up)\b", re.I), "single_software", "postgresql"),
    (re.compile(r"\binstall\b.{0,30}\bmachine\s*learning\b|\bmachine\s*learning\s*tools?\b", re.I), "python_ml", "python_ml"),
    (re.compile(r"\bset\s*up\b.{0,30}\bgit\b.{0,30}\bgithub\b|\bgit\b.{0,30}\bgithub\b.{0,30}\b(account|configure|setup)\b", re.I), "single_software", "git"),
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

    # Card-prompt patterns fire BEFORE the install-verb check so that prompts
    # like "Create a new React project" and "Configure a PostgreSQL database"
    # route correctly without needing the word "install".
    for pattern, intent, software in _CARD_PROMPT_PATTERNS:
        if pattern.search(text):
            return {
                "intent": intent,
                "preset_or_software": software,
                "needs_clarification": False,
            }

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

_SYSTEM_PROMPT = """You are AuriOS, an AI assistant that helps users install and set up developer software on Windows.

STRICT RULES — follow every one without exception:
1. You can discuss two things: (a) installing/setting up software, and (b) briefly explaining what a known tool is and why someone would use it. Known tools: Python, Git, VS Code, Docker, Node.js, Java, MySQL, PostgreSQL, MongoDB, Redis, Postman, TensorFlow, PyTorch, scikit-learn, Jupyter, npm, yarn.
2. If the user asks about ANYTHING outside those two topics (weather, news, sports, jokes, recipes, math, personal advice, emotions, general knowledge unrelated to dev tools), reply with exactly: "I'm AuriOS — I can only help with developer software. Try saying 'install Python' or 'show available software'."
3. When explaining a tool, keep it to 1-2 sentences maximum, then suggest installing it if relevant.
4. If the user asks for recommendations or is discussing a project, recommend the best tools from the known list and guide them toward installation.
5. Keep every reply to 1-3 sentences maximum.
6. NEVER invent facts, software names, version numbers, URLs, or features.
7. NEVER pretend to perform actions you cannot do (browsing the web, checking weather, running code).
8. Reply in the same language the user used (English, Hinglish, or Urdu). Never switch languages mid-reply.
9. Do NOT output JSON, markdown, bullet points, or any structured format — plain text only. Never wrap words in asterisks. No bold, no italic, no markdown.
10. If asked who made you, say: "I was built by The Automators team."
11. Do NOT repeat the user's message back to them."""

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
    "bye":                       "Goodbye! Come back whenever you need software installed.",
    "goodbye":                   "Goodbye!",
    "see you":                   "See you!",
    "take care":                 "Take care!",
    "cya":                       "See you!",
    "ttyl":                      "Talk later!",
    # Help
    "help":                      "I install developer software on Windows. " + _INSTALL_HINT,
    "what can you do":           "I install developer software on Windows. " + _INSTALL_HINT,
    "what do you do":            "I install developer software on Windows. " + _INSTALL_HINT,
    "who are you":               "I'm AuriOS — an AI assistant that installs developer software on Windows. " + _INSTALL_HINT,
    "what are you":              "I'm AuriOS — an AI assistant that installs developer software on Windows. " + _INSTALL_HINT,
    # Personal / emotional — warm redirect
    "i am sad":                  "Sorry to hear that. I'm just a software installer, but I hope things look up! Let me know if setting up a project might help distract you.",
    "i feel sad":                "I'm just a dev tool, but I hope you feel better soon! Let me know if there's anything I can set up for you.",
    "i am bored":                "Let's fix that — want to start a new project? I can set up Python, Node.js, or a full dev environment for you.",
    "i am tired":                "Take a break! When you're ready, I'm here to set up your dev environment.",
    "i am happy":                "Great to hear! Ready to build something? " + _INSTALL_HINT,
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
    r"stock\s+price|bitcoin|crypto|"
    # Math / general knowledge
    r"what\s+is\s+\d|calculate|solve|equation|"
    r"how\s+much\s+is\s+\d|plus|minus|multiply|divide|"
    # Personal / emotional
    r"i\s+(am|feel|felt|feeling|'?m)\s+(sad|happy|bored|tired|angry|lonely|depressed|stressed|anxious|upset|excited|scared|fine|okay|good|bad|great)|"
    r"feeling\s+(sad|happy|bored|tired|angry|lonely|depressed|stressed|anxious|upset|scared)|"
    r"i\s+(need|want)\s+(a\s+hug|to\s+cry|to\s+vent|advice\s+on\s+life)|"
    r"my\s+(life|relationship|family|friend|girlfriend|boyfriend|wife|husband)|"
    r"motivat(e|ion)|mental\s+health|"
    # Random general knowledge
    r"who\s+is\s+(god|allah|jesus|buddha|einstein|newton|shakespeare)|"
    r"history\s+of|when\s+was\s+.{0,20}\s+born|"
    r"what\s+is\s+the\s+meaning\s+of\s+life|"
    r"do\s+you\s+love|are\s+you\s+conscious|do\s+you\s+have\s+feelings)\b",
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


def _llm_chat(user_message: str, history: list[Dict[str, str]] = None) -> Dict[str, Any]:
    """Single LLM call for all conversational responses using the strict system prompt."""
    
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
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
            "intent": "consultation",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": _sanitize(reply) if reply else _GENERAL_FALLBACK,
        }
    except requests.exceptions.ConnectionError:
        return {
            "intent": "consultation",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": (
                "I can't reach Ollama right now. "
                "Make sure it's running with: ollama serve"
            ),
        }
    except Exception:
        return {
            "intent": "consultation",
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
                "(try: ollama serve) and try again."
            ),
        }
    except (requests.exceptions.Timeout, requests.exceptions.HTTPError) as e:
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": f"Ollama had trouble responding ({e}). Please try again.",
        }
    except (json.JSONDecodeError, KeyError):
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": "Sorry, I got confused for a second — could you rephrase that?",
        }


# ---------------------------------------------------------------------------
# Confirmation detector — resolves "yes/sure/ok" against pending category
# ---------------------------------------------------------------------------

_CONFIRM_RE = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|start|begin|"
    r"let'?s go|let'?s do it|sounds good|go for it|please|haan|ha\b|"
    r"bilkul|zaroor|theek hai|chalo)\s*[!.]*\s*$",
    re.IGNORECASE,
)

# Maps category name → the install intent to trigger on confirmation
_CATEGORY_TO_INTENT = {
    "ml":       "python_ml",
    "database": "database_clarify",   # still needs clarification
    "coding":   "python_basic",
    "api":      "web_dev",
    "devops":   "full_stack",
}

# Phrases Auri uses when asking "Ready to get started?" for each category
_CATEGORY_READY_PHRASES = {
    "ml":       "ready to get started",
    "database": "what kind of data",
    "coding":   "what language are you planning",
    "api":      "which one do you need",
    "devops":   "would you like me to set",
}

_CONFIRM_RESPONSES = {
    "python_ml":        "Got it! Starting the Machine Learning setup now — I'll install Python, TensorFlow, PyTorch, and scikit-learn. Watch the progress panel.",
    "python_basic":     "Got it! Starting the Python dev setup now. Watch the progress panel.",
    "web_dev":          "Got it! Starting the web dev setup now. Watch the progress panel.",
    "full_stack":       "Got it! Starting the full stack setup now. Watch the progress panel.",
    "data_science":     "Got it! Starting the data science setup now. Watch the progress panel.",
}


def _resolve_confirmation(text: str, history: list[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """If the user just said 'yes/sure/ok', check the last assistant message
    to see if it was a category prompt awaiting confirmation. If so, return
    the appropriate install intent instead of the generic canned reply."""
    if not _CONFIRM_RE.match(text):
        return None
    if not history:
        return None

    # Find the most recent assistant message
    last_assistant = None
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            last_assistant = msg.get("content", "").lower()
            break

    if not last_assistant:
        return None

    # Check which category prompt it matches
    for category, phrase in _CATEGORY_READY_PHRASES.items():
        if phrase in last_assistant:
            intent = _CATEGORY_TO_INTENT.get(category)
            if intent and intent not in ("database_clarify",):
                return {
                    "intent": intent,
                    "preset_or_software": intent,
                    "needs_clarification": False,
                    "response_text": _CONFIRM_RESPONSES.get(intent, "Got it! Starting setup now."),
                }

    return None

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


def parse_intent(text: str, history: list[Dict[str, str]] = None) -> Dict[str, Any]:
    """Return a structured intent + natural-language reply for ``text``.

    Routing:
    0. Confirmation of a pending category prompt → install intent (checked first).
    1. URL/domain inputs → fixed reply, no LLM.
    2. Pre-canned greetings/acks → fixed reply, no LLM.
    3. "Show available software" → list_software intent, no LLM.
    4. Rule-based install classifier → only confirmation sentence from LLM.
    5. General-conversation detector → free-form Ollama call.
    6. Everything else → JSON-structured LLM fallback.
    """
    # ── Stage 0: confirmation of a pending category prompt ───────────────────
    # Must run BEFORE the canned lookup so "yes/sure/ok" after "Ready to get
    # started?" resolves to the correct install intent, not a generic reply.
    confirmed = _resolve_confirmation(text, history)
    if confirmed:
        return confirmed
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

    # ── Stage 3.5: Category intent detector ──────────────────────────────────
    category_intent = _detect_category_intent(text)
    if category_intent:
        return category_intent

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
    return _llm_chat(text, history)
