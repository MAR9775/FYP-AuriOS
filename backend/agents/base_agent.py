"""BaseAgent — ReAct pattern (Reason → Act → Observe → Decide)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Logging setup — all agents share the same file handler
# ---------------------------------------------------------------------------

_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "aurjos.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


class BaseAgent:
    """Abstract base for all AuriOS agents using the ReAct loop."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # ReAct steps — subclasses override these
    # ------------------------------------------------------------------

    def reason(self, context: Dict[str, Any]) -> str:
        """Step 1 — Analyse context and decide what to do next.

        Returns a human-readable reasoning string that is logged.
        """
        thought = f"{self.__class__.__name__} reasoning over context: {list(context.keys())}"
        self.logger.debug("[REASON] %s", thought)
        return thought

    def act(self, action: Dict[str, Any]) -> Any:
        """Step 2 — Execute the action decided during reason().

        Returns raw result (type depends on subclass).
        """
        self.logger.debug("[ACT] executing action: %s", action)
        return None

    def observe(self, result: Any) -> Dict[str, Any]:
        """Step 3 — Interpret the raw result from act().

        Returns a structured observation dict.
        """
        observation: Dict[str, Any] = {"raw": result}
        self.logger.debug("[OBSERVE] observation: %s", observation)
        return observation

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, task: Dict[str, Any]) -> Any:
        """Execute the full ReAct loop for *task* and return the final result."""
        self.logger.info("[RUN] %s starting task: %s", self.__class__.__name__, task)

        thought = self.reason(task)
        raw_result = self.act({"thought": thought, "task": task})
        observation = self.observe(raw_result)

        self.logger.info("[DONE] %s finished. observation keys: %s",
                         self.__class__.__name__, list(observation.keys()))
        return observation
