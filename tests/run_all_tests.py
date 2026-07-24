"""
run_all_tests.py — AuriOS v1.1 Automated Test Runner

Executes all test suites (unit, integration, e2e, security, performance),
collects pass/fail results per test, measures response times, and writes
a structured JSON report to tests/reports/results.json.

Usage:
    python tests/run_all_tests.py              # Run all suites
    python tests/run_all_tests.py --unit       # Run only unit tests
    python tests/run_all_tests.py --no-backend # Skip integration tests

Requirements:
    pip install pytest
"""

import json
import os
import sys
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# Ensure Unicode output works on Windows terminals with cp1252 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
REPORTS_DIR = TESTS_DIR / "reports"
RESULTS_FILE = REPORTS_DIR / "results.json"

# Test suites in execution order
TEST_SUITES = {
    "unit": {
        "path": "tests/unit/",
        "description": "Unit Tests — Agents, Intent Parser, Utilities",
        "requires_backend": False,
        "files": [
            "tests/unit/test_detection.py",
            "tests/unit/test_install.py",
            "tests/unit/test_intent_parser.py",
            "tests/unit/test_failure_simulation.py",
        ],
    },
    "integration": {
        "path": "tests/integration/",
        "description": "Integration Tests — FastAPI Endpoints (requires running backend)",
        "requires_backend": True,
        "files": [
            "tests/integration/test_api.py",
        ],
    },
    "e2e": {
        "path": "tests/e2e/",
        "description": "End-to-End Tests — Pipeline, TaskManager, Environment",
        "requires_backend": False,
        "files": [
            "tests/e2e/test_full_pipeline.py",
        ],
    },
    "security": {
        "path": "tests/security/",
        "description": "Security Tests — Auth, Rate Limiting, Encryption",
        "requires_backend": True,
        "files": [
            "tests/security/test_auth.py",
        ],
    },
    "performance": {
        "path": "tests/performance/",
        "description": "Performance Tests — Latency, Concurrency, DB Speed",
        "requires_backend": True,
        "files": [
            "tests/performance/test_load.py",
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_backend():
    """Return True if the backend is reachable on localhost:8000."""
    try:
        import requests
        r = requests.get("http://127.0.0.1:8000/ping", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def run_pytest_json(test_path: str) -> dict:
    """
    Run pytest on a single test file and parse the JSON output.

    Returns a dict with:
      - file: test file path
      - passed / failed / skipped / errors: counts
      - duration_s: total time for this file
      - tests: list of individual test results
    """
    json_tmp = REPORTS_DIR / f"_tmp_{Path(test_path).stem}.json"

    cmd = [
        sys.executable, "-m", "pytest",
        str(PROJECT_ROOT / test_path),
        f"--json-report-file={json_tmp}",
        "--json-report",
        "-v",
        "--tb=short",
        "-q",
    ]

    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    duration = time.perf_counter() - start

    result = {
        "file": test_path,
        "exit_code": proc.returncode,
        "duration_s": round(duration, 3),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "tests": [],
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-300:] if proc.stderr else "",
    }

    # Try to parse the JSON report if pytest-json-report is available
    if json_tmp.exists():
        try:
            with open(json_tmp, "r", encoding="utf-8") as f:
                report = json.load(f)

            summary = report.get("summary", {})
            result["passed"] = summary.get("passed", 0)
            result["failed"] = summary.get("failed", 0)
            result["skipped"] = summary.get("skipped", 0)
            result["errors"] = summary.get("error", 0)
            result["duration_s"] = round(report.get("duration", duration), 3)

            for t in report.get("tests", []):
                result["tests"].append({
                    "nodeid": t.get("nodeid", ""),
                    "outcome": t.get("outcome", "unknown"),
                    "duration_s": round(t.get("duration", 0), 4),
                    "message": (t.get("call", {}).get("longrepr", "") or "")[:200],
                })
        except (json.JSONDecodeError, KeyError):
            pass
        finally:
            json_tmp.unlink(missing_ok=True)
    else:
        # Fallback: parse pytest stdout for counts
        result.update(_parse_pytest_stdout(proc.stdout, proc.returncode))

    return result


def _parse_pytest_stdout(stdout: str, exit_code: int) -> dict:
    """Fallback parser when pytest-json-report is not installed."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "tests": []}

    for line in stdout.splitlines():
        line_stripped = line.strip()

        # Parse individual test lines: "test_file.py::TestClass::test_name PASSED"
        if " PASSED" in line_stripped or " FAILED" in line_stripped or " SKIPPED" in line_stripped:
            parts = line_stripped.rsplit(" ", 1)
            if len(parts) == 2:
                nodeid, outcome = parts
                outcome = outcome.strip().lower()
                if outcome == "passed":
                    counts["passed"] += 1
                elif outcome == "failed":
                    counts["failed"] += 1
                elif outcome in ("skipped", "skip"):
                    counts["skipped"] += 1
                counts["tests"].append({
                    "nodeid": nodeid.strip(),
                    "outcome": outcome,
                    "duration_s": 0,
                    "message": "",
                })

        # Parse summary line: "X passed, Y failed, Z skipped"
        if "passed" in line_stripped and ("failed" in line_stripped or "warning" in line_stripped
                                          or line_stripped.startswith("=")):
            import re
            for key in ("passed", "failed", "skipped", "error"):
                m = re.search(rf"(\d+)\s+{key}", line_stripped)
                if m:
                    counts[key if key != "error" else "errors"] = int(m.group(1))

    if exit_code != 0 and counts["passed"] == 0 and counts["failed"] == 0:
        counts["errors"] = 1

    return counts


# ---------------------------------------------------------------------------
# Fancy console output
# ---------------------------------------------------------------------------

class Colors:
    """ANSI color codes for terminal output."""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    DIM    = "\033[2m"


def print_header(text: str):
    print(f"\n{'='*70}")
    print(f"  {Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}")
    print(f"{'='*70}")


def print_suite_header(name: str, desc: str):
    print(f"\n{Colors.BOLD}▶ [{name.upper()}] {desc}{Colors.RESET}")
    print(f"  {'-'*60}")


def print_test_result(nodeid: str, outcome: str, duration: float):
    icon = {
        "passed": f"{Colors.GREEN}✓{Colors.RESET}",
        "failed": f"{Colors.RED}✗{Colors.RESET}",
        "skipped": f"{Colors.YELLOW}○{Colors.RESET}",
        "error": f"{Colors.RED}!{Colors.RESET}",
    }.get(outcome, "?")
    dur_str = f"{Colors.DIM}{duration:.3f}s{Colors.RESET}" if duration > 0 else ""
    # Shorten nodeid for display
    short = nodeid.split("::", 1)[-1] if "::" in nodeid else nodeid
    print(f"    {icon} {short} {dur_str}")


def print_suite_summary(result: dict):
    p, f, s = result["passed"], result["failed"], result["skipped"]
    total = p + f + s
    status = f"{Colors.GREEN}ALL PASSED{Colors.RESET}" if f == 0 else f"{Colors.RED}{f} FAILED{Colors.RESET}"
    print(f"  {Colors.BOLD}Result:{Colors.RESET} {p} passed, {f} failed, {s} skipped ({total} total) — {result['duration_s']:.2f}s — {status}")


def print_final_summary(report: dict):
    totals = report["totals"]
    p, f, s = totals["passed"], totals["failed"], totals["skipped"]
    total = p + f + s

    print_header("FINAL TEST REPORT")

    if f == 0 and totals["errors"] == 0:
        print(f"\n  {Colors.GREEN}{Colors.BOLD}★ ALL {total} TESTS PASSED ★{Colors.RESET}")
    else:
        print(f"\n  {Colors.RED}{Colors.BOLD}✗ {f} TESTS FAILED{Colors.RESET}")

    print(f"""
  {Colors.BOLD}Total:{Colors.RESET}     {total} tests
  {Colors.GREEN}Passed:{Colors.RESET}    {p}
  {Colors.RED}Failed:{Colors.RESET}    {f}
  {Colors.YELLOW}Skipped:{Colors.RESET}   {s}
  {Colors.RED}Errors:{Colors.RESET}    {totals['errors']}
  {Colors.CYAN}Duration:{Colors.RESET}  {report['total_duration_s']:.2f}s
  {Colors.DIM}Report:{Colors.RESET}    {RESULTS_FILE}
""")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_all(suites_to_run: list[str], skip_backend_suites: bool = False):
    """Execute selected test suites and generate the JSON report."""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    backend_up = check_backend()

    report = {
        "project": "AuriOS v1.1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "backend_status": "online" if backend_up else "offline",
        "suites": {},
        "totals": {"passed": 0, "failed": 0, "skipped": 0, "errors": 0},
        "total_duration_s": 0,
    }

    overall_start = time.perf_counter()

    print_header("AuriOS v1.1 — Automated Test Runner")
    print(f"  Python:    {sys.version.split()[0]}")
    print(f"  Backend:   {'[ONLINE]' if backend_up else '[OFFLINE]'}")
    print(f"  Timestamp: {report['timestamp']}")
    print(f"  Suites:    {', '.join(suites_to_run)}")

    for suite_name in suites_to_run:
        suite_config = TEST_SUITES.get(suite_name)
        if not suite_config:
            print(f"\n  {Colors.YELLOW}⚠ Unknown suite '{suite_name}' — skipped{Colors.RESET}")
            continue

        # Skip backend-dependent suites if backend is offline
        if suite_config["requires_backend"] and (not backend_up or skip_backend_suites):
            reason = "backend offline" if not backend_up else "--no-backend flag"
            print_suite_header(suite_name, suite_config["description"])
            print(f"    {Colors.YELLOW}○ Skipped ({reason}){Colors.RESET}")
            report["suites"][suite_name] = {
                "description": suite_config["description"],
                "status": "skipped",
                "reason": reason,
                "files": [],
            }
            continue

        print_suite_header(suite_name, suite_config["description"])

        suite_results = {
            "description": suite_config["description"],
            "status": "passed",
            "files": [],
        }

        for test_file in suite_config["files"]:
            file_path = PROJECT_ROOT / test_file
            if not file_path.exists():
                print(f"    {Colors.YELLOW}○ {test_file} — file not found, skipping{Colors.RESET}")
                suite_results["files"].append({
                    "file": test_file,
                    "status": "missing",
                    "passed": 0, "failed": 0, "skipped": 0,
                })
                continue

            try:
                file_result = run_pytest_json(test_file)
            except subprocess.TimeoutExpired:
                file_result = {
                    "file": test_file,
                    "exit_code": -1,
                    "duration_s": 300,
                    "passed": 0, "failed": 0, "skipped": 0, "errors": 1,
                    "tests": [],
                    "stdout_tail": "", "stderr_tail": "Test execution timed out (300s)",
                }

            # Print individual test results
            if file_result["tests"]:
                for t in file_result["tests"]:
                    print_test_result(t["nodeid"], t["outcome"], t["duration_s"])
            else:
                # No detailed results — print file-level summary
                status = "passed" if file_result["exit_code"] == 0 else "failed"
                icon = f"{Colors.GREEN}✓{Colors.RESET}" if status == "passed" else f"{Colors.RED}✗{Colors.RESET}"
                print(f"    {icon} {test_file} ({file_result['passed']}p/{file_result['failed']}f) — {file_result['duration_s']:.2f}s")

            # Aggregate counts
            report["totals"]["passed"] += file_result["passed"]
            report["totals"]["failed"] += file_result["failed"]
            report["totals"]["skipped"] += file_result["skipped"]
            report["totals"]["errors"] += file_result["errors"]

            if file_result["failed"] > 0 or file_result["errors"] > 0:
                suite_results["status"] = "failed"

            # Clean up stdout/stderr for JSON serialization
            file_result.pop("stdout_tail", None)
            file_result.pop("stderr_tail", None)
            suite_results["files"].append(file_result)

        print_suite_summary({
            "passed": sum(f.get("passed", 0) for f in suite_results["files"]),
            "failed": sum(f.get("failed", 0) for f in suite_results["files"]),
            "skipped": sum(f.get("skipped", 0) for f in suite_results["files"]),
            "duration_s": sum(f.get("duration_s", 0) for f in suite_results["files"]),
        })

        report["suites"][suite_name] = suite_results

    report["total_duration_s"] = round(time.perf_counter() - overall_start, 3)

    # Compute overall verdict
    report["verdict"] = "PASS" if report["totals"]["failed"] == 0 and report["totals"]["errors"] == 0 else "FAIL"

    # Write JSON report
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print_final_summary(report)

    # Return exit code: 0 if all passed, 1 if any failures
    return 0 if report["verdict"] == "PASS" else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AuriOS v1.1 — Run all automated tests and generate report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tests/run_all_tests.py                  # All suites
  python tests/run_all_tests.py --unit            # Unit tests only
  python tests/run_all_tests.py --unit --e2e      # Unit + E2E
  python tests/run_all_tests.py --no-backend      # Skip backend-dependent suites
  python tests/run_all_tests.py --all             # Force all (same as default)
        """,
    )

    parser.add_argument("--unit", action="store_true", help="Run unit tests")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--e2e", action="store_true", help="Run end-to-end tests")
    parser.add_argument("--security", action="store_true", help="Run security tests")
    parser.add_argument("--performance", action="store_true", help="Run performance tests")
    parser.add_argument("--all", action="store_true", help="Run all suites (default)")
    parser.add_argument("--no-backend", action="store_true",
                        help="Skip suites that require a running backend")

    args = parser.parse_args()

    # Determine which suites to run
    selected = []
    if args.unit:         selected.append("unit")
    if args.integration:  selected.append("integration")
    if args.e2e:          selected.append("e2e")
    if args.security:     selected.append("security")
    if args.performance:  selected.append("performance")

    # Default: run all
    if not selected or args.all:
        selected = list(TEST_SUITES.keys())

    exit_code = run_all(selected, skip_backend_suites=args.no_backend)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
