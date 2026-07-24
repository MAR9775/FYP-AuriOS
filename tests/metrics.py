"""
metrics.py — AuriOS v1.1 Evaluation Metrics Calculator

Computes 8 system evaluation metrics from test results and installation
history data. Produces a structured report suitable for FYP evaluation.

Usage:
    from tests.metrics import MetricsCalculator
    calc = MetricsCalculator()
    calc.load_from_database("data/aurjos.db")
    report = calc.compute_all()
    calc.save_report("tests/reports/metrics.json")

Or standalone:
    python tests/metrics.py
"""

import json
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InstallRecord:
    """A single installation attempt from the database."""
    preset_name: str
    software: str            # comma-separated list for presets
    status: str              # "success", "failed", "cancelled"
    duration_s: float
    error_log: Optional[str] = None

@dataclass
class FailureEvent:
    """A failure scenario and how it was handled."""
    scenario: str
    handled_gracefully: bool   # True = logged + user message, False = crash/hang

@dataclass
class ExecutionCheck:
    """Correctness of a single installer execution."""
    software: str
    expected_flags: list
    actual_flags: list
    exit_interpreted_correctly: bool
    correct_package_manager: bool

@dataclass
class ValidationCheck:
    """Post-install detection accuracy check."""
    software: str
    actually_installed: bool
    detected: bool

@dataclass
class SessionRecord:
    """One app session (launch → close)."""
    backend_alive_throughout: bool
    unhandled_exceptions: int
    renderer_crashes: int
    max_freeze_seconds: float

@dataclass
class AttemptRecord:
    """A user install attempt for user-effort tracking."""
    software_target: str
    attempt_number: int       # 1 = first try, 2 = retry, etc.
    final_status: str         # "success", "failed"


# ---------------------------------------------------------------------------
# Metric results
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    """Result of a single metric calculation."""
    name: str
    abbreviation: str
    value: float
    unit: str
    formula: str
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class MetricsCalculator:
    """Computes all 8 AuriOS evaluation metrics."""

    # Weights for composite score
    WEIGHTS = {
        "TSR": 0.25,
        "PSR": 0.10,
        "FRR": 0.15,
        "TEA": 0.15,
        "VA":  0.10,
        "TTC": 0.05,
        "SS":  0.15,
        "UE":  0.05,
    }

    def __init__(self):
        self.installs: list[InstallRecord] = []
        self.failures: list[FailureEvent] = []
        self.executions: list[ExecutionCheck] = []
        self.validations: list[ValidationCheck] = []
        self.sessions: list[SessionRecord] = []
        self.attempts: list[AttemptRecord] = []
        self._results: dict[str, MetricResult] = {}

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_from_database(self, db_path: str):
        """Load installation history from the AuriOS SQLite database."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            "SELECT preset_name, software, status, duration_s, error_log "
            "FROM installation_history ORDER BY timestamp"
        ).fetchall()

        for row in rows:
            self.installs.append(InstallRecord(
                preset_name=row["preset_name"] or "",
                software=row["software"] or "",
                status=row["status"] or "unknown",
                duration_s=row["duration_s"] or 0,
                error_log=row["error_log"],
            ))
        conn.close()

    def load_from_test_results(self, results_path: str):
        """Load test results from run_all_tests.py JSON output."""
        with open(results_path, "r") as f:
            data = json.load(f)

        for suite in data.get("suites", {}).values():
            for file_result in suite.get("files", []):
                for test in file_result.get("tests", []):
                    # Map robustness tests to failure events
                    if "failure" in test.get("nodeid", "").lower() or \
                       "error" in test.get("nodeid", "").lower() or \
                       "timeout" in test.get("nodeid", "").lower():
                        self.failures.append(FailureEvent(
                            scenario=test["nodeid"],
                            handled_gracefully=test["outcome"] == "passed",
                        ))

                    # Map test session stability
                    if test["outcome"] == "error":
                        self.sessions.append(SessionRecord(
                            backend_alive_throughout=False,
                            unhandled_exceptions=1,
                            renderer_crashes=0,
                            max_freeze_seconds=0,
                        ))

    def add_install(self, preset: str, software: str, status: str,
                    duration_s: float, error_log: str = None):
        """Manually add an installation record."""
        self.installs.append(InstallRecord(preset, software, status, duration_s, error_log))

    def add_failure_event(self, scenario: str, handled: bool):
        """Manually add a failure event."""
        self.failures.append(FailureEvent(scenario, handled))

    def add_execution(self, software: str, expected_flags: list, actual_flags: list,
                      exit_correct: bool, manager_correct: bool):
        """Manually add an execution correctness check."""
        self.executions.append(ExecutionCheck(
            software, expected_flags, actual_flags, exit_correct, manager_correct
        ))

    def add_validation(self, software: str, actually_installed: bool, detected: bool):
        """Manually add a validation accuracy check."""
        self.validations.append(ValidationCheck(software, actually_installed, detected))

    def add_session(self, backend_alive: bool, exceptions: int = 0,
                    crashes: int = 0, max_freeze: float = 0):
        """Manually add a session stability record."""
        self.sessions.append(SessionRecord(backend_alive, exceptions, crashes, max_freeze))

    def add_attempt(self, target: str, attempt_num: int, status: str):
        """Manually add a user attempt record."""
        self.attempts.append(AttemptRecord(target, attempt_num, status))

    # ------------------------------------------------------------------
    # Metric calculations
    # ------------------------------------------------------------------

    def task_success_rate(self) -> MetricResult:
        """M1: Task Success Rate (TSR)."""
        if not self.installs:
            return MetricResult("Task Success Rate", "TSR", 0, "%",
                                "Fully Successful / Total Attempted × 100",
                                {"note": "No installation data"})

        total = len(self.installs)
        successful = sum(1 for i in self.installs if i.status in ("success", "done"))
        tsr = (successful / total) * 100

        return MetricResult(
            name="Task Success Rate",
            abbreviation="TSR",
            value=round(tsr, 1),
            unit="%",
            formula=f"{successful} / {total} × 100",
            details={"successful": successful, "total": total,
                     "failed": total - successful},
        )

    def partial_success_rate(self) -> MetricResult:
        """M2: Partial Success Rate (PSR) — multi-software tasks only."""
        multi = [i for i in self.installs if "," in i.software]
        if not multi:
            return MetricResult("Partial Success Rate", "PSR", 0, "%",
                                "Tasks with ≥1 success / Multi-Software Tasks × 100",
                                {"note": "No multi-software tasks"})

        partial = sum(1 for i in multi if i.status in ("success", "done", "partial"))
        psr = (partial / len(multi)) * 100

        return MetricResult(
            name="Partial Success Rate",
            abbreviation="PSR",
            value=round(psr, 1),
            unit="%",
            formula=f"{partial} / {len(multi)} × 100",
            details={"partial_successes": partial, "total_multi": len(multi)},
        )

    def failure_recovery_rate(self) -> MetricResult:
        """M3: Failure Recovery Rate (FRR)."""
        if not self.failures:
            return MetricResult("Failure Recovery Rate", "FRR", 100, "%",
                                "Gracefully Handled / Total Failures × 100",
                                {"note": "No failure events recorded"})

        graceful = sum(1 for f in self.failures if f.handled_gracefully)
        frr = (graceful / len(self.failures)) * 100

        return MetricResult(
            name="Failure Recovery Rate",
            abbreviation="FRR",
            value=round(frr, 1),
            unit="%",
            formula=f"{graceful} / {len(self.failures)} × 100",
            details={
                "graceful": graceful,
                "unhandled": len(self.failures) - graceful,
                "total": len(self.failures),
            },
        )

    def tool_execution_accuracy(self) -> MetricResult:
        """M4: Tool Execution Accuracy (TEA)."""
        if not self.executions:
            return MetricResult("Tool Execution Accuracy", "TEA", 0, "%",
                                "Correct Executions / Total × 100",
                                {"note": "No execution data"})

        correct = sum(1 for e in self.executions if (
            e.expected_flags == e.actual_flags and
            e.exit_interpreted_correctly and
            e.correct_package_manager
        ))
        tea = (correct / len(self.executions)) * 100

        return MetricResult(
            name="Tool Execution Accuracy",
            abbreviation="TEA",
            value=round(tea, 1),
            unit="%",
            formula=f"{correct} / {len(self.executions)} × 100",
            details={"correct": correct, "total": len(self.executions)},
        )

    def validation_accuracy(self) -> MetricResult:
        """M5: Validation Accuracy (VA) with confusion matrix."""
        if not self.validations:
            return MetricResult("Validation Accuracy", "VA", 0, "%",
                                "(TP + TN) / Total × 100",
                                {"note": "No validation data"})

        tp = sum(1 for v in self.validations if v.actually_installed and v.detected)
        tn = sum(1 for v in self.validations if not v.actually_installed and not v.detected)
        fp = sum(1 for v in self.validations if not v.actually_installed and v.detected)
        fn = sum(1 for v in self.validations if v.actually_installed and not v.detected)

        total = tp + tn + fp + fn
        accuracy = ((tp + tn) / total) * 100 if total > 0 else 0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        return MetricResult(
            name="Validation Accuracy",
            abbreviation="VA",
            value=round(accuracy, 1),
            unit="%",
            formula=f"({tp} + {tn}) / {total} × 100",
            details={
                "confusion_matrix": {"TP": tp, "TN": tn, "FP": fp, "FN": fn},
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "f1_score": round(f1, 3),
            },
        )

    def time_to_completion(self) -> MetricResult:
        """M6: Time to Completion (TTC)."""
        successful = [i for i in self.installs if i.status in ("success", "done") and i.duration_s > 0]
        if not successful:
            return MetricResult("Time to Completion", "TTC", 0, "seconds",
                                "AVG(duration_s) for successful tasks",
                                {"note": "No successful installations"})

        durations = [i.duration_s for i in successful]
        avg_ttc = sum(durations) / len(durations)
        min_ttc = min(durations)
        max_ttc = max(durations)

        # Breakdown by preset
        by_preset = defaultdict(list)
        for i in successful:
            by_preset[i.preset_name].append(i.duration_s)

        preset_avgs = {
            k: round(sum(v) / len(v), 1) for k, v in by_preset.items()
        }

        return MetricResult(
            name="Time to Completion",
            abbreviation="TTC",
            value=round(avg_ttc, 1),
            unit="seconds",
            formula=f"AVG of {len(successful)} successful tasks",
            details={
                "avg_seconds": round(avg_ttc, 1),
                "min_seconds": round(min_ttc, 1),
                "max_seconds": round(max_ttc, 1),
                "sample_count": len(successful),
                "by_preset": preset_avgs,
            },
        )

    def system_stability(self) -> MetricResult:
        """M7: System Stability (SS) — crash-free session rate."""
        if not self.sessions:
            return MetricResult("System Stability", "SS", 100, "%",
                                "Stable Sessions / Total Sessions × 100",
                                {"note": "No session data"})

        stable = sum(1 for s in self.sessions if all([
            s.backend_alive_throughout,
            s.unhandled_exceptions == 0,
            s.renderer_crashes == 0,
            s.max_freeze_seconds < 5.0,
        ]))
        ss = (stable / len(self.sessions)) * 100

        return MetricResult(
            name="System Stability",
            abbreviation="SS",
            value=round(ss, 1),
            unit="%",
            formula=f"{stable} / {len(self.sessions)} × 100",
            details={
                "stable": stable,
                "unstable": len(self.sessions) - stable,
                "total": len(self.sessions),
            },
        )

    def user_effort(self) -> MetricResult:
        """M8: User Effort (UE) — average retries per success."""
        if not self.attempts:
            return MetricResult("User Effort", "UE", 1.0, "attempts/success",
                                "Total Attempts / Unique Successes",
                                {"note": "No attempt data"})

        total_attempts = len(self.attempts)
        targets_succeeded = set(
            a.software_target for a in self.attempts if a.final_status == "success"
        )
        unique_successes = len(targets_succeeded)

        ue = total_attempts / unique_successes if unique_successes > 0 else float("inf")

        return MetricResult(
            name="User Effort",
            abbreviation="UE",
            value=round(ue, 2),
            unit="attempts/success",
            formula=f"{total_attempts} / {unique_successes}",
            details={
                "total_attempts": total_attempts,
                "unique_successes": unique_successes,
                "retry_rate": round(ue - 1.0, 2) if ue != float("inf") else "N/A",
            },
        )

    # ------------------------------------------------------------------
    # Composite score
    # ------------------------------------------------------------------

    def composite_score(self) -> dict:
        """Compute weighted composite system score from all metrics."""
        if not self._results:
            self.compute_all()

        # Normalize TTC and UE to 0-100 scale
        ttc_val = self._results.get("TTC", MetricResult("", "", 0, "", "")).value
        ue_val = self._results.get("UE", MetricResult("", "", 1.0, "", "")).value

        ttc_norm = max(0, 100 - (ttc_val / 6))            # 0s→100, 600s→0
        ue_norm = max(0, 100 * (2.0 - ue_val))            # 1.0→100, 2.0→0

        normalized = {}
        for abbr, result in self._results.items():
            if abbr == "TTC":
                normalized[abbr] = round(ttc_norm, 1)
            elif abbr == "UE":
                normalized[abbr] = round(ue_norm, 1)
            else:
                normalized[abbr] = result.value

        weighted_sum = sum(
            self.WEIGHTS[abbr] * normalized.get(abbr, 0)
            for abbr in self.WEIGHTS
        )
        total_weight = sum(self.WEIGHTS.values())
        score = weighted_sum / total_weight if total_weight > 0 else 0

        return {
            "composite_score": round(score, 1),
            "normalized_values": normalized,
            "weights": self.WEIGHTS,
            "weighted_contributions": {
                abbr: round(self.WEIGHTS[abbr] * normalized.get(abbr, 0), 2)
                for abbr in self.WEIGHTS
            },
        }

    # ------------------------------------------------------------------
    # Compute all + report
    # ------------------------------------------------------------------

    def compute_all(self) -> dict:
        """Compute all 8 metrics and return structured report."""
        metrics = [
            self.task_success_rate(),
            self.partial_success_rate(),
            self.failure_recovery_rate(),
            self.tool_execution_accuracy(),
            self.validation_accuracy(),
            self.time_to_completion(),
            self.system_stability(),
            self.user_effort(),
        ]

        self._results = {m.abbreviation: m for m in metrics}

        report = {
            "project": "AuriOS v1.1",
            "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "metrics": {m.abbreviation: asdict(m) for m in metrics},
            "composite": self.composite_score(),
            "data_summary": {
                "install_records": len(self.installs),
                "failure_events": len(self.failures),
                "execution_checks": len(self.executions),
                "validation_checks": len(self.validations),
                "session_records": len(self.sessions),
                "attempt_records": len(self.attempts),
            },
        }
        return report

    def save_report(self, path: str):
        """Save metrics report to JSON file."""
        report = self.compute_all()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Metrics report saved to: {path}")

    def print_summary(self):
        """Print a formatted summary table to stdout."""
        if not self._results:
            self.compute_all()

        print("\n" + "=" * 65)
        print("  AuriOS v1.1 — Evaluation Metrics Summary")
        print("=" * 65)
        print(f"  {'Metric':<30} {'Abbr':<6} {'Value':>8}  {'Unit'}")
        print(f"  {'-'*30} {'-'*5} {'-'*8}  {'-'*15}")

        for abbr, result in self._results.items():
            val = f"{result.value:.1f}" if isinstance(result.value, float) else str(result.value)
            print(f"  {result.name:<30} {abbr:<6} {val:>8}  {result.unit}")

        composite = self.composite_score()
        print(f"\n  {'COMPOSITE SCORE':<30} {'':6} {composite['composite_score']:>7.1f}  / 100")
        print("=" * 65)


# ---------------------------------------------------------------------------
# Demo with sample data (matches the 25 scenarios in evaluation_metrics.md)
# ---------------------------------------------------------------------------

def demo():
    """Run metrics calculation with sample data from the 25-scenario table."""
    calc = MetricsCalculator()

    # Install records (20 install scenarios from the sample table)
    sample_installs = [
        ("python_basic",  "python",                        "success",  45),
        ("git",           "git",                           "success",  180),
        ("vscode",        "vscode",                        "failed",   90),
        ("full_stack",    "python, git, nodejs, vscode",   "partial",  320),
        ("python_ml",     "python, tensorflow",            "partial",  240),
        ("docker",        "docker",                        "failed",   3),
        ("python_basic",  "python",                        "success",  2),    # already installed
        ("nodejs",        "nodejs",                        "failed",   1),    # disk full
        ("python_basic",  "python",                        "failed",   1),    # typo
        ("python_basic",  "python",                        "success",  55),   # Hinglish
        ("git",           "git",                           "failed",   45),   # network drop
        ("web_dev",       "python, git, nodejs, vscode",   "success",  210),
        ("mysql",         "mysql",                         "failed",   600),  # timeout
        ("postgresql",    "postgresql",                    "success",  90),
        ("data_science",  "python, numpy, pandas",         "success",  280),
        ("postman",       "postman",                       "success",  60),
        ("vlc",           "vlc",                           "success",  35),
        ("full_stack",    "python, git, nodejs, vscode",   "success",  350),  # Ollama offline
        ("rufus",         "rufus",                         "success",  20),
        ("java",          "java",                          "failed",   40),   # 1603
    ]
    for preset, sw, status, dur in sample_installs:
        calc.add_install(preset, sw, status, dur)

    # Failure events (15 failure scenarios)
    failure_scenarios = [
        ("Antivirus blocks exe", True),
        ("1 of 4 tools failed in preset", True),
        ("pip tensorflow fails", True),
        ("No admin privileges", True),
        ("Disk < 1GB", True),
        ("Typo in software name", True),
        ("Network drops at 60%", True),
        ("Installer timeout 10min", True),
        ("Backend crash mid-task", False),     # Unhandled!
        ("Cancel mid-download", True),
        ("Exit code 1603", True),
        ("Ollama offline", True),
        ("WebSocket disconnect", True),
        ("Database locked", True),
        ("Rate limit triggered", True),
    ]
    for scenario, handled in failure_scenarios:
        calc.add_failure_event(scenario, handled)

    # Execution checks (16 installer executions)
    executions = [
        ("python", ["/quiet", "PrependPath=1"], ["/quiet", "PrependPath=1"], True, True),
        ("git",    ["/VERYSILENT"], ["/VERYSILENT"], True, True),
        ("vscode", ["/VERYSILENT"], ["/VERYSILENT"], True, True),
        ("nodejs", ["/quiet"], ["/quiet"], True, True),
        ("python", ["/quiet", "PrependPath=1"], ["/quiet", "PrependPath=1"], True, True),
        ("docker", [], [], True, True),                         # blocked before exec
        ("git",    ["/VERYSILENT"], ["/VERYSILENT"], True, True),
        ("nodejs", ["/quiet"], ["/quiet"], True, True),
        ("vscode", ["/VERYSILENT"], ["/VERYSILENT"], True, True),
        ("mysql",  ["/quiet"], ["/quiet"], True, True),
        ("postgresql", ["/quiet"], ["/quiet"], True, True),
        ("python", ["/quiet", "PrependPath=1"], ["/quiet", "PrependPath=1"], True, True),
        ("postman", ["/S"], ["/S"], True, True),
        ("vlc",    ["/S"], ["/S"], True, True),
        ("rufus",  ["/S"], ["/S"], True, True),
        ("java",   ["/quiet"], ["/quiet"], True, False),        # Wrong manager fallback
    ]
    for sw, exp, act, exit_ok, mgr_ok in executions:
        calc.add_execution(sw, exp, act, exit_ok, mgr_ok)

    # Validation checks (18 detection results)
    validations = [
        ("python", True, True),     # TP
        ("git", True, True),        # TP
        ("vscode", False, False),   # TN (install failed)
        ("python", True, True),     # TP
        ("git", True, True),        # TP
        ("nodejs", True, True),     # TP
        ("vscode", True, False),    # FN — AV blocked, validation missed
        ("python", True, True),     # TP
        ("nodejs", True, True),     # TP
        ("postgresql", True, True), # TP
        ("python", True, True),     # TP
        ("postman", True, False),   # FN — portable, not on PATH
        ("vlc", True, True),        # TP (registry detection)
        ("mysql", False, False),    # TN (install timed out)
        ("python", True, True),     # TP
        ("git", True, True),        # TP
        ("rufus", True, True),      # TP
        ("java", False, False),     # TN (1603 failed)
    ]
    for sw, actual, detected in validations:
        calc.add_validation(sw, actual, detected)

    # Session records (25 sessions)
    for i in range(24):
        calc.add_session(backend_alive=True, exceptions=0, crashes=0, max_freeze=0.5)
    calc.add_session(backend_alive=False, exceptions=1, crashes=0, max_freeze=0)  # Crash #18

    # User attempts (23 attempts, 18 unique successes)
    attempts = [
        ("python", 1, "success"), ("git", 1, "success"),
        ("vscode", 1, "failed"), ("vscode", 2, "failed"),  # Never succeeded
        ("python", 1, "success"), ("python", 1, "success"),
        ("docker", 1, "failed"), ("docker", 2, "success"),
        ("python", 1, "success"),                           # Already installed
        ("nodejs", 1, "failed"), ("nodejs", 2, "failed"),
        ("python", 1, "success"),                           # Hinglish
        ("git", 1, "failed"), ("git", 2, "success"),        # Retry after network
        ("nodejs", 1, "success"), ("vscode", 1, "success"),
        ("mysql", 1, "failed"),
        ("postgresql", 1, "success"), ("python", 1, "success"),
        ("postman", 1, "success"), ("vlc", 1, "success"),
        ("rufus", 1, "success"), ("java", 1, "failed"),
    ]
    for target, num, status in attempts:
        calc.add_attempt(target, num, status)

    # Compute and display
    report = calc.compute_all()
    calc.print_summary()

    # Save to reports directory
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    calc.save_report(str(reports_dir / "metrics.json"))

    return report


if __name__ == "__main__":
    demo()
