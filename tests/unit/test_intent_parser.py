"""
test_intent_parser.py — Unit tests for the intent parsing engine.

Tests rule-based classification, pre-canned responses, exclusion filters,
multilingual keywords, URL blocking, and the full parse_intent() router.
No LLM calls — Ollama is mocked for fallback tests.

Run: pytest tests/unit/test_intent_parser.py -v
"""

import pytest
from unittest.mock import patch


class TestCannedResponses:
    """Stage 2: Pre-canned responses for greetings, acks, farewells."""

    def test_hello_returns_canned(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("hello")
        assert result["intent"] == "general_chat"
        assert "AuriOS" in result["response_text"]

    def test_hi_returns_canned(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("hi")
        assert result["intent"] == "general_chat"

    def test_thanks_returns_canned(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("thanks")
        assert "welcome" in result["response_text"].lower()

    def test_bye_returns_canned(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("bye")
        assert "👋" in result["response_text"]

    def test_weather_returns_offtopic(self):
        """Off-topic questions should be blocked without hitting LLM."""
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("how's the weather")
        assert "only help with" in result["response_text"].lower()


class TestURLBlocking:
    """Stage 1: URLs should be blocked immediately."""

    def test_url_blocked(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("https://malicious.com/payload.exe")
        assert result["intent"] == "unknown"
        assert "only help with" in result["response_text"].lower()

    def test_domain_blocked(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("evil.com")
        assert result["intent"] == "unknown"


class TestListSoftwareIntent:
    """Stage 3: 'show available software' detection."""

    def test_show_software(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("show me available software")
        assert result["intent"] == "list_software"

    def test_list_tools(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("list available tools")
        assert result["intent"] == "list_software"

    def test_what_can_you_install(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("show me what software you have")
        assert result["intent"] == "list_software"


class TestRuleBasedInstallIntents:
    """Stage 4: Rule-based install intent detection."""

    def test_install_python(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install python")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "python"

    def test_install_git(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install git")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "git"

    def test_install_vscode(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install vs code")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "vscode"

    def test_install_docker(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install docker")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "docker"

    def test_install_nodejs(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install node.js")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "nodejs"

    def test_install_mysql(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install mysql")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "mysql"

    def test_install_postman(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install postman")
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "postman"


class TestPresetIntents:
    """Stage 4: Preset detection (multi-software bundles)."""

    def test_full_stack(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install full stack environment")
        assert result["intent"] == "full_stack"

    def test_python_ml(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install python for machine learning")
        assert result["intent"] == "python_ml"

    def test_data_science(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install pandas and jupyter")
        assert result["intent"] == "data_science"

    def test_web_dev(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("set up web dev environment")
        assert result["intent"] == "web_dev"

    def test_java_setup(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("setup java environment")
        assert result["intent"] == "java"

    def test_python_basic(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("setup python environment")
        assert result["intent"] == "python_basic"


class TestExclusionRules:
    """Negative filters: uninstall, questions, status queries."""

    def test_uninstall_blocked(self):
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("uninstall python")
        assert result is None  # Should NOT trigger install intent

    def test_remove_blocked(self):
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("remove git from my system")
        assert result is None

    def test_question_blocked(self):
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("how do I install python?")
        assert result is None  # Questions start with "how" → blocked

    def test_status_query_blocked(self):
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("is python installed")
        assert result is None

    def test_no_install_verb_returns_none(self):
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("python is great")
        assert result is None  # No install verb


class TestMultilingualInput:
    """Hinglish and Urdu keyword support."""

    def test_hinglish_chahiye(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("python chahiye")
        assert result["preset_or_software"] == "python"

    def test_hinglish_install_karo(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("git install karo")
        assert result["preset_or_software"] == "git"

    def test_urdu_de_do(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("python de do")
        assert result["preset_or_software"] == "python"


class TestEdgeCases:
    """Edge cases: empty strings, whitespace, mixed case, extra spaces."""

    def test_empty_string(self):
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("")
        assert result is None

    def test_whitespace_only(self):
        from backend.llm.intent_parser import _rule_based_intent
        result = _rule_based_intent("   ")
        assert result is None

    def test_mixed_case(self):
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("INSTALL PYTHON")
        assert result["preset_or_software"] == "python"

    def test_java_vs_javascript(self):
        """'java' should match java, not javascript/nodejs."""
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install java")
        assert result["preset_or_software"] == "java"

    def test_unknown_software_slug_extraction(self):
        """Install verb + unknown word → slug extracted for catalog lookup."""
        from backend.llm.intent_parser import parse_intent
        result = parse_intent("install vlc")
        # Should get single_software with slug "vlc"
        assert result["intent"] == "single_software"
        assert result["preset_or_software"] == "vlc"
