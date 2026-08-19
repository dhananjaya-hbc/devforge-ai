"""Deterministic parsing of pytest output.

Test metrics must come from the actual run, never from a model's summary of it,
so a passing report can always be traced back to real execution.
"""

import re

# "===== 1 failed, 4 passed, 2 skipped in 0.42s ====="
_COUNT = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)\b")
# "FAILED tests/test_api.py::test_login - NameError: name 'x' is not defined"
_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$", re.MULTILINE)
# coverage.py total row: "TOTAL   120   18   85%"
_COVERAGE = re.compile(r"^TOTAL\s+.*?(\d+(?:\.\d+)?)%", re.MULTILINE)
# "no tests ran in 0.01s" / "collected 0 items"
_NO_TESTS = re.compile(r"no tests ran|collected 0 items")


def parse_pytest_output(stdout: str, stderr: str = "", exit_code: int | None = None) -> dict:
    """Extract real test counts from pytest output.

    Returns total/passed/failed/coverage/failures plus `parse_ok`, which is
    False when no recognisable summary was found (a crash, an import error, or
    a missing pytest). Callers must treat parse_ok=False as a failed run rather
    than as zero failures.
    """
    combined = f"{stdout}\n{stderr}"

    counts: dict[str, int] = {}
    # The summary line is last; later matches win over any echoed earlier text.
    for value, label in _COUNT.findall(combined):
        key = "error" if label.startswith("error") else label
        counts[key] = int(value)

    passed = counts.get("passed", 0) + counts.get("xpassed", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0) + counts.get("xfailed", 0)
    skipped = counts.get("skipped", 0)
    total = passed + failed + skipped

    failures = [
        {"test_name": name, "error": (msg or "").strip() or "See test output for details."}
        for name, msg in _FAILED.findall(combined)
    ]

    coverage = 0.0
    if match := _COVERAGE.search(combined):
        coverage = float(match.group(1))

    parse_ok = bool(counts) or bool(_NO_TESTS.search(combined))

    # pytest exited non-zero but nothing parsed as a failure: still a failure.
    if not parse_ok:
        failed = max(failed, 1)
        failures = failures or [
            {
                "test_name": "pytest",
                "error": (
                    f"Could not parse pytest output (exit code {exit_code}). "
                    f"Tail: {combined.strip()[-400:] or 'no output'}"
                ),
            }
        ]
    elif exit_code not in (None, 0) and failed == 0:
        failed = 1
        failures = failures or [
            {"test_name": "pytest", "error": f"pytest exited {exit_code} with no reported failure."}
        ]

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "coverage": coverage,
        "failures": failures,
        "parse_ok": parse_ok,
    }
