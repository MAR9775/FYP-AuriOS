"""Intent parser for AuriOS — uses Ollama LLM for natural language understanding
and response generation. Supports English, Urdu, and Hinglish."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

SYSTEM_PROMPT = """You are Auri, a warm and friendly AI assistant that helps users set up their developer environment on Windows. You naturally switch between English and Hinglish (Roman Urdu/Hindi mixed with English), always matching the user's own language style.

Your task is to classify the user's message into one of the intents below and respond naturally.

── INSTALL INTENTS (trigger actual software installation) ──────────────────────
- python_basic    : user wants a basic Python setup
- python_ml       : user wants ML/AI tools (TensorFlow, PyTorch, Jupyter, etc.)
- web_dev         : user wants web dev tools (Node.js, React, HTML/CSS, etc.)
- full_stack      : user wants a complete / everything development environment
- data_science    : user wants data science tools (pandas, numpy, matplotlib, etc.)
- java            : user wants Java / JDK setup

── NEEDS CLARIFICATION ─────────────────────────────────────────────────────────
- database_clarify  : user wants a database but didn't say which one
- single_software   : user wants one specific tool
                      (python, git, docker, nodejs, mysql, postgresql, mongodb,
                       redis, postman, vscode, java)

── CONVERSATIONAL (no installation) ────────────────────────────────────────────
- greeting  : user is saying hello
- help      : user wants to know what you can do
- thanks    : user is expressing gratitude
- goodbye   : user is leaving
- unknown   : intent is unclear — ask a friendly clarifying question

── RESPONSE STYLE ───────────────────────────────────────────────────────────────
- Mirror the user's language (Urdu, Hinglish, or English).
- Be enthusiastic for install intents; confirm you're starting the setup.
- For database_clarify, ask which database they want (MySQL, PostgreSQL, MongoDB).
- For unknown, ask a friendly question to understand what they need.
- Never mention JSON, intents, or classification to the user.

── OUTPUT FORMAT ────────────────────────────────────────────────────────────────
Return ONLY a valid JSON object — no markdown fences, no extra text:
{
  "intent": "<intent_name>",
  "preset_or_software": "<software or intent name for installs; null for conversational>",
  "needs_clarification": <true only for database_clarify, otherwise false>,
  "response_text": "<your natural response to the user>"
}"""


def parse_intent(text: str) -> Dict[str, Any]:
    """Send *text* to Ollama and return a structured intent + response dict.

    Return keys mirror the original interface so server.py needs no changes:
    - intent
    - preset_or_software
    - needs_clarification
    - response_text
    """
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.7},
            },
            timeout=60,
        )
        resp.raise_for_status()

        raw = resp.json()["message"]["content"]
        result: Dict[str, Any] = json.loads(raw)

        return {
            "intent": result.get("intent", "unknown"),
            "preset_or_software": result.get("preset_or_software"),
            "needs_clarification": bool(result.get("needs_clarification", False)),
            "response_text": result.get("response_text", "Kuch samjha nahi, phir se bolo? 😊"),
        }

    except requests.exceptions.ConnectionError:
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": (
                "Ollama se connect nahi ho pa raha! "
                "Please run: ollama serve 🧠"
            ),
        }
    except (requests.exceptions.Timeout, requests.exceptions.HTTPError) as e:
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": f"Ollama response mein masla aaya ({e}). Dobara try karo 😅",
        }
    except (json.JSONDecodeError, KeyError):
        return {
            "intent": "unknown",
            "preset_or_software": None,
            "needs_clarification": False,
            "response_text": "Auri ka response parse nahi hua. Dobara try karo 🤔",
        }
