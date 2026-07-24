"""
generate_report.py — AuriOS v1.1 Automated Test Report Generator

Orchestrates the full testing + reporting pipeline:
  1. Runs all test suites via run_all_tests.py  →  reports/results.json
  2. Computes evaluation metrics via metrics.py  →  reports/metrics.json
  3. Generates a human-readable final report     →  reports/final_report.txt

Usage:
    python tests/generate_report.py                # Full pipeline
    python tests/generate_report.py --skip-tests   # Skip test execution, use existing results.json
    python tests/generate_report.py --no-backend   # Skip backend-dependent suites
"""

import json
import os
import sys
import time
import argparse
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
REPORTS_DIR = TESTS_DIR / "reports"

RESULTS_FILE = REPORTS_DIR / "results.json"
METRICS_FILE = REPORTS_DIR / "metrics.json"
REPORT_FILE  = REPORTS_DIR / "final_report.txt"


# ---------------------------------------------------------------------------
# Step 1: Run all tests
# ---------------------------------------------------------------------------

def run_tests(extra_args: list[str] = None) -> dict:
    """Execute run_all_tests.py and return the results dict."""
    print("\n" + "=" * 70)
    print("  STEP 1/3 — Running All Test Suites")
    print("=" * 70)

    cmd = [sys.executable, str(TESTS_DIR / "run_all_tests.py")]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=False, env=env)

    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        print("  ⚠ results.json not generated — tests may have crashed")
        return {}


def load_existing_results() -> dict:
    """Load previously generated results.json."""
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"\n  ✓ Loaded existing results.json ({data.get('timestamp', 'unknown')})")
        return data
    else:
        print("\n  ⚠ No existing results.json found — running tests first")
        return run_tests()


# ---------------------------------------------------------------------------
# Step 2: Compute metrics
# ---------------------------------------------------------------------------

def compute_metrics(results: dict) -> dict:
    """Run metrics.py demo and return the metrics dict."""
    print("\n" + "=" * 70)
    print("  STEP 2/3 — Computing Evaluation Metrics")
    print("=" * 70)

    # Import and run the metrics calculator
    sys.path.insert(0, str(TESTS_DIR))
    from metrics import MetricsCalculator

    calc = MetricsCalculator()

    # Seed from test results if available
    if results:
        _seed_metrics_from_results(calc, results)

    # Also load from database if available
    db_path = PROJECT_ROOT / "data" / "aurjos.db"
    if db_path.exists():
        try:
            calc.load_from_database(str(db_path))
            print(f"  ✓ Loaded {len(calc.installs)} install records from database")
        except Exception as e:
            print(f"  ⚠ Could not load database: {e}")

    # If we still have no data, use the demo scenario data
    if not calc.installs and not calc.failures:
        print("  ℹ No live data — using demo scenario data for metrics")
        from metrics import demo
        report = demo()
        return report

    report = calc.compute_all()
    calc.save_report(str(METRICS_FILE))
    calc.print_summary()
    return report


def _seed_metrics_from_results(calc, results: dict):
    """Convert test results into metrics data points.

    Only failure-simulation tests are mapped to FRR failure events.
    Session records are NOT synthesised from test counts — SS is only
    populated from real database data or explicit add_session() calls.
    """
    for suite_name, suite in results.get("suites", {}).items():
        if suite.get("status") == "skipped":
            continue

        for file_result in suite.get("files", []):
            for test in file_result.get("tests", []):
                nodeid = test.get("nodeid", "")
                outcome = test.get("outcome", "unknown")

                # Only count dedicated failure-simulation tests as FRR events.
                # These live in test_failure_simulation.py and explicitly test
                # that the system handles a specific failure gracefully.
                if "test_failure_simulation" in nodeid:
                    calc.add_failure_event(
                        scenario=nodeid,
                        handled=outcome == "passed",
                    )


# ---------------------------------------------------------------------------
# Step 3: Generate final_report.txt
# ---------------------------------------------------------------------------

def generate_final_report(results: dict, metrics: dict):
    """Generate the comprehensive human-readable final_report.txt."""
    print("\n" + "=" * 70)
    print("  STEP 3/3 — Generating Final Report")
    print("=" * 70)

    now = datetime.now(timezone.utc)
    lines = []

    def hr(char="=", width=72):
        lines.append(char * width)

    def blank():
        lines.append("")

    def heading(text):
        blank()
        hr()
        lines.append(f"  {text}")
        hr()
        blank()

    def subheading(text):
        blank()
        lines.append(f"--- {text} ---")
        blank()

    # ---- Header ----
    hr()
    lines.append("  AURIOS v1.1 — AUTOMATED TEST REPORT")
    lines.append(f"  Generated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"  Python:    {sys.version.split()[0]}")
    lines.append(f"  Platform:  {sys.platform}")
    lines.append(f"  Backend:   {results.get('backend_status', 'unknown')}")
    hr()

    # ---- Section 1: Executive Summary ----
    heading("1. EXECUTIVE SUMMARY")

    totals = results.get("totals", {})
    total_tests = totals.get("passed", 0) + totals.get("failed", 0) + totals.get("skipped", 0)
    passed = totals.get("passed", 0)
    failed = totals.get("failed", 0)
    skipped = totals.get("skipped", 0)
    errors = totals.get("errors", 0)
    duration = results.get("total_duration_s", 0)
    verdict = results.get("verdict", "UNKNOWN")

    pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0

    lines.append(f"  Verdict:        {verdict}")
    lines.append(f"  Total Tests:    {total_tests}")
    lines.append(f"  Passed:         {passed} ({pass_rate:.1f}%)")
    lines.append(f"  Failed:         {failed}")
    lines.append(f"  Skipped:        {skipped}")
    lines.append(f"  Errors:         {errors}")
    lines.append(f"  Duration:       {duration:.2f} seconds")

    composite = metrics.get("composite", {})
    score = composite.get("composite_score", 0)
    lines.append(f"  System Score:   {score:.1f} / 100")

    # ---- Section 2: Suite-by-Suite Results ----
    heading("2. TEST SUITE RESULTS")

    for suite_name, suite in results.get("suites", {}).items():
        status = suite.get("status", "unknown")
        desc = suite.get("description", "")
        icon = "[PASS]" if status == "passed" else "[SKIP]" if status == "skipped" else "[FAIL]"

        subheading(f"{icon} {suite_name.upper()} — {desc}")

        if status == "skipped":
            reason = suite.get("reason", "unknown reason")
            lines.append(f"    Skipped: {reason}")
            continue

        for file_result in suite.get("files", []):
            fp = file_result.get("file", "")
            fp_passed = file_result.get("passed", 0)
            fp_failed = file_result.get("failed", 0)
            fp_skipped = file_result.get("skipped", 0)
            fp_dur = file_result.get("duration_s", 0)
            fp_total = fp_passed + fp_failed + fp_skipped

            file_icon = "✓" if fp_failed == 0 else "✗"
            lines.append(f"    {file_icon} {fp}")
            lines.append(f"      Results: {fp_passed} passed, {fp_failed} failed, "
                         f"{fp_skipped} skipped ({fp_total} total)")
            lines.append(f"      Duration: {fp_dur:.2f}s")

            # List individual test results
            for test in file_result.get("tests", []):
                nodeid = test.get("nodeid", "")
                outcome = test.get("outcome", "?")
                t_dur = test.get("duration_s", 0)

                # Shorten nodeid for display
                short = nodeid.split("::", 1)[-1] if "::" in nodeid else nodeid
                if len(short) > 55:
                    short = short[:52] + "..."

                outcome_icon = {
                    "passed": "  ✓",
                    "failed": "  ✗",
                    "skipped": "  ○",
                    "error": "  !",
                }.get(outcome, "  ?")

                lines.append(f"        {outcome_icon} {short:<56} {t_dur:.3f}s")

                # Show failure message if available
                msg = test.get("message", "")
                if outcome in ("failed", "error") and msg:
                    for line in msg.strip().split("\n")[:3]:
                        lines.append(f"            → {line.strip()[:70]}")

    # ---- Section 3: Failure Analysis ----
    heading("3. FAILURE ANALYSIS")

    all_failures = []
    for suite_name, suite in results.get("suites", {}).items():
        for file_result in suite.get("files", []):
            for test in file_result.get("tests", []):
                if test.get("outcome") in ("failed", "error"):
                    all_failures.append({
                        "suite": suite_name,
                        "file": file_result.get("file", ""),
                        "test": test.get("nodeid", ""),
                        "outcome": test.get("outcome", ""),
                        "message": test.get("message", ""),
                    })

    if not all_failures:
        lines.append("  No test failures detected. All tests passed or were skipped.")
    else:
        lines.append(f"  Total failures: {len(all_failures)}")
        blank()

        # Group by suite
        by_suite = defaultdict(list)
        for f in all_failures:
            by_suite[f["suite"]].append(f)

        for suite_name, failures in by_suite.items():
            lines.append(f"  [{suite_name.upper()}] — {len(failures)} failure(s):")
            for i, f in enumerate(failures, 1):
                short_test = f["test"].split("::", 1)[-1] if "::" in f["test"] else f["test"]
                lines.append(f"    {i}. {short_test}")
                if f["message"]:
                    for line in f["message"].strip().split("\n")[:2]:
                        lines.append(f"       Cause: {line.strip()[:65]}")
            blank()

        # Categorize failures
        subheading("Failure Categories")

        categories = defaultdict(int)
        for f in all_failures:
            msg = f.get("message", "").lower()
            test_name = f.get("test", "").lower()
            if "assert" in msg:
                categories["Assertion Error"] += 1
            elif "timeout" in msg or "timeout" in test_name:
                categories["Timeout"] += 1
            elif "connection" in msg or "network" in test_name:
                categories["Network/Connection"] += 1
            elif "permission" in msg or "admin" in test_name:
                categories["Permission/Auth"] += 1
            elif "import" in msg:
                categories["Import/Dependency"] += 1
            else:
                categories["Other"] += 1

        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            bar = "█" * count + "░" * (10 - min(count, 10))
            lines.append(f"    {cat:<25} {count:>3}  {bar}")

    # ---- Section 4: Evaluation Metrics ----
    heading("4. EVALUATION METRICS")

    metric_data = metrics.get("metrics", {})
    if metric_data:
        lines.append(f"  {'Metric':<32} {'Abbr':<6} {'Value':>8}  {'Unit':<18} {'Formula'}")
        lines.append(f"  {'-'*32} {'-'*5} {'-'*8}  {'-'*18} {'-'*25}")

        for abbr, m in metric_data.items():
            name = m.get("name", "")
            val = m.get("value", 0)
            unit = m.get("unit", "")
            formula = m.get("formula", "")

            val_str = f"{val:.1f}" if isinstance(val, float) else str(val)
            lines.append(f"  {name:<32} {abbr:<6} {val_str:>8}  {unit:<18} {formula}")

        blank()

        # Composite score breakdown
        subheading("Composite System Score")

        score = composite.get("composite_score", 0)
        lines.append(f"  Overall Score: {score:.1f} / 100")
        blank()

        contributions = composite.get("weighted_contributions", {})
        weights = composite.get("weights", {})
        normalized = composite.get("normalized_values", {})

        if contributions:
            lines.append(f"  {'Metric':<8} {'Weight':>7} {'Normalized':>11} {'Contribution':>13}")
            lines.append(f"  {'-'*8} {'-'*7} {'-'*11} {'-'*13}")
            for abbr in contributions:
                w = weights.get(abbr, 0)
                n = normalized.get(abbr, 0)
                c = contributions.get(abbr, 0)
                lines.append(f"  {abbr:<8} {w:>7.2f} {n:>10.1f}% {c:>12.2f}")
            lines.append(f"  {'':8} {'':7} {'TOTAL':>11} {sum(contributions.values()):>12.1f}")

        blank()

        # Score interpretation
        if score >= 90:
            grade = "A — Excellent"
            interpretation = "System meets all critical requirements with high reliability."
        elif score >= 80:
            grade = "B — Good"
            interpretation = "System is functional with minor issues under edge conditions."
        elif score >= 70:
            grade = "C — Acceptable"
            interpretation = "System works for common cases but has notable gaps in failure handling."
        elif score >= 60:
            grade = "D — Below Average"
            interpretation = "Significant issues affect core functionality. Improvements needed."
        else:
            grade = "F — Critical"
            interpretation = "System has fundamental reliability problems requiring major rework."

        lines.append(f"  Grade:          {grade}")
        lines.append(f"  Interpretation: {interpretation}")

    else:
        lines.append("  No metrics data available.")

    # ---- Section 5: Validation Accuracy Details ----
    heading("5. VALIDATION ACCURACY DETAILS")

    va_data = metric_data.get("VA", {}).get("details", {})
    cm = va_data.get("confusion_matrix", {})
    if cm:
        tp, tn, fp, fn = cm.get("TP", 0), cm.get("TN", 0), cm.get("FP", 0), cm.get("FN", 0)

        lines.append("  Confusion Matrix:")
        lines.append(f"                        Detected=True    Detected=False")
        lines.append(f"    Actually Installed      TP={tp:<5}           FN={fn:<5}")
        lines.append(f"    Actually Missing        FP={fp:<5}           TN={tn:<5}")
        blank()
        lines.append(f"  Precision: {va_data.get('precision', 0):.3f}")
        lines.append(f"  Recall:    {va_data.get('recall', 0):.3f}")
        lines.append(f"  F1 Score:  {va_data.get('f1_score', 0):.3f}")
    else:
        lines.append("  No validation data available.")

    # ---- Section 6: Identified Issues ----
    heading("6. IDENTIFIED ISSUES & RECOMMENDATIONS")

    issues = _identify_issues(results, metrics)
    if issues:
        for i, issue in enumerate(issues, 1):
            severity = issue["severity"]
            sev_tag = {"HIGH": "[HIGH]  ", "MEDIUM": "[MED]   ", "LOW": "[LOW]   "}.get(severity, "        ")
            lines.append(f"  {i:>2}. {sev_tag}{issue['title']}")
            for detail in issue.get("details", []):
                lines.append(f"              {detail}")
            blank()
    else:
        lines.append("  No critical issues identified.")

    # ---- Section 7: Data Summary ----
    heading("7. DATA SUMMARY")

    data_sum = metrics.get("data_summary", {})
    if data_sum:
        lines.append(f"  Install records:     {data_sum.get('install_records', 0)}")
        lines.append(f"  Failure events:      {data_sum.get('failure_events', 0)}")
        lines.append(f"  Execution checks:    {data_sum.get('execution_checks', 0)}")
        lines.append(f"  Validation checks:   {data_sum.get('validation_checks', 0)}")
        lines.append(f"  Session records:     {data_sum.get('session_records', 0)}")
        lines.append(f"  Attempt records:     {data_sum.get('attempt_records', 0)}")

    # ---- Footer ----
    blank()
    hr()
    lines.append("  END OF REPORT")
    lines.append(f"  Generated by: tests/generate_report.py")
    lines.append(f"  Output files:")
    lines.append(f"    - {RESULTS_FILE}")
    lines.append(f"    - {METRICS_FILE}")
    lines.append(f"    - {REPORT_FILE}")
    hr()

    # Write file
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n  ✓ Final report saved to: {REPORT_FILE}")
    print(f"  ✓ Report size: {len(content):,} bytes, {len(lines)} lines")

    return content


def _identify_issues(results: dict, metrics: dict) -> list[dict]:
    """Analyze results and metrics to identify actionable issues."""
    issues = []
    totals = results.get("totals", {})
    metric_data = metrics.get("metrics", {})
    composite = metrics.get("composite", {})

    # Check for test failures
    failed = totals.get("failed", 0)
    if failed > 0:
        issues.append({
            "severity": "HIGH",
            "title": f"{failed} test(s) failed",
            "details": [
                "Review the FAILURE ANALYSIS section for specific test names and causes.",
                "Fix failing tests before production deployment.",
            ],
        })

    # Check for test errors (crashes)
    errors = totals.get("errors", 0)
    if errors > 0:
        issues.append({
            "severity": "HIGH",
            "title": f"{errors} test(s) produced unhandled errors",
            "details": [
                "Errors indicate crashes or unhandled exceptions during testing.",
                "These may indicate missing error handling in the codebase.",
            ],
        })

    # TSR below threshold
    tsr = metric_data.get("TSR", {}).get("value", 100)
    if tsr < 75:
        issues.append({
            "severity": "HIGH",
            "title": f"Task Success Rate is low ({tsr:.1f}%)",
            "details": [
                "Less than 75% of installation tasks complete successfully.",
                "Recommendation: Add retry logic for failed downloads and installer crashes.",
            ],
        })
    elif tsr < 85:
        issues.append({
            "severity": "MEDIUM",
            "title": f"Task Success Rate below target ({tsr:.1f}%, target: 85%)",
            "details": [
                "Some installations fail under non-ideal conditions.",
                "Recommendation: Improve error recovery in DownloadAgent and InstallAgent.",
            ],
        })

    # Validation accuracy
    va = metric_data.get("VA", {}).get("value", 100)
    if va < 85:
        va_details = metric_data.get("VA", {}).get("details", {})
        cm = va_details.get("confusion_matrix", {})
        fn = cm.get("FN", 0)
        issues.append({
            "severity": "MEDIUM",
            "title": f"Validation Accuracy is {va:.1f}% ({fn} false negatives)",
            "details": [
                "ValidationAgent fails to detect some installed software.",
                "Recommendation: Expand _WIN_PATHS and _REGISTRY_NAMES for better coverage.",
                "Consider adding PATH refresh delay before re-detection.",
            ],
        })

    # FRR below threshold
    frr = metric_data.get("FRR", {}).get("value", 100)
    if frr < 95:
        issues.append({
            "severity": "HIGH" if frr < 90 else "MEDIUM",
            "title": f"Failure Recovery Rate is {frr:.1f}%",
            "details": [
                "Some failure scenarios cause crashes instead of graceful degradation.",
                "Recommendation: Add try/except handlers around all subprocess and network calls.",
            ],
        })

    # System stability
    ss = metric_data.get("SS", {}).get("value", 100)
    if ss < 95:
        issues.append({
            "severity": "HIGH",
            "title": f"System Stability is {ss:.1f}%",
            "details": [
                "More than 5% of sessions experience crashes or freezes.",
                "Recommendation: Investigate backend crash logs in logs/aurjos.log.",
            ],
        })

    # User effort too high
    ue = metric_data.get("UE", {}).get("value", 1.0)
    if ue > 1.5:
        issues.append({
            "severity": "MEDIUM",
            "title": f"User Effort is high ({ue:.2f} attempts per success)",
            "details": [
                "Users need multiple retries to complete tasks.",
                "Recommendation: Improve typo tolerance in intent parser and error messaging.",
            ],
        })

    # TTC concerns
    ttc = metric_data.get("TTC", {}).get("value", 0)
    if ttc > 300:
        issues.append({
            "severity": "LOW",
            "title": f"Average Time to Completion is {ttc:.0f}s ({ttc/60:.1f} min)",
            "details": [
                "Installations take over 5 minutes on average.",
                "Recommendation: Implement parallel downloads for multi-software presets.",
            ],
        })

    # Composite score
    score = composite.get("composite_score", 100)
    if score < 70:
        issues.append({
            "severity": "HIGH",
            "title": f"Composite System Score is {score:.1f}% (below acceptable threshold)",
            "details": [
                "Overall system quality needs significant improvement.",
                "Focus on the highest-weighted failing metrics: TSR, FRR, TEA, SS.",
            ],
        })

    # Backend offline warning
    if results.get("backend_status") == "offline":
        issues.append({
            "severity": "LOW",
            "title": "Backend was offline — integration/security/performance tests skipped",
            "details": [
                "Start backend with: python -m uvicorn backend.server:app --port 8000",
                "Re-run tests with backend online for complete coverage.",
            ],
        })

    # No failures at all — still note it
    if not issues:
        issues.append({
            "severity": "LOW",
            "title": "No critical issues detected",
            "details": ["System appears stable. Continue monitoring in production."],
        })

    return sorted(issues, key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[x["severity"]])


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AuriOS v1.1 — Generate Full Test Report")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip test execution; use existing results.json")
    parser.add_argument("--no-backend", action="store_true",
                        help="Pass --no-backend flag to test runner")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()

    # Step 1: Run tests (or load existing)
    if args.skip_tests:
        results = load_existing_results()
    else:
        extra = ["--no-backend"] if args.no_backend else []
        results = run_tests(extra)

    # Step 2: Compute metrics
    metrics = compute_metrics(results)

    # Step 3: Generate final report
    report_text = generate_final_report(results, metrics)

    elapsed = time.perf_counter() - start

    print("\n" + "=" * 70)
    print("  REPORT GENERATION COMPLETE")
    print("=" * 70)
    print(f"  Total time:    {elapsed:.1f}s")
    print(f"  Output files:")
    print(f"    📊 {RESULTS_FILE}")
    print(f"    📈 {METRICS_FILE}")
    print(f"    📝 {REPORT_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
