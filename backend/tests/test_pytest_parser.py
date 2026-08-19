"""Tests that reported metrics come from real pytest output, never a model."""

from app.services.pytest_parser import parse_pytest_output


def test_all_passing_run():
    out = "===== 5 passed in 0.42s ====="
    r = parse_pytest_output(out, "", 0)
    assert (r["total"], r["passed"], r["failed"]) == (5, 5, 0)
    assert r["parse_ok"] is True


def test_mixed_run_reports_real_counts_and_failures():
    out = (
        "FAILED tests/test_api.py::test_login - NameError: name 'get_db' is not defined\n"
        "===== 1 failed, 4 passed in 1.20s ====="
    )
    r = parse_pytest_output(out, "", 1)
    assert (r["total"], r["passed"], r["failed"]) == (5, 4, 1)
    assert r["failures"][0]["test_name"] == "tests/test_api.py::test_login"
    assert "get_db" in r["failures"][0]["error"]


def test_skipped_counted_in_total_but_not_passed():
    r = parse_pytest_output("===== 3 passed, 2 skipped in 0.1s =====", "", 0)
    assert (r["total"], r["passed"], r["failed"], r["skipped"]) == (5, 3, 0, 2)


def test_errors_count_as_failures():
    r = parse_pytest_output("===== 2 errors in 0.1s =====", "", 1)
    assert r["failed"] == 2


def test_coverage_is_extracted():
    out = "TOTAL      120     18    85%\n===== 5 passed in 0.4s ====="
    assert parse_pytest_output(out, "", 0)["coverage"] == 85.0


def test_no_coverage_plugin_reports_zero():
    assert parse_pytest_output("===== 1 passed in 0.1s =====", "", 0)["coverage"] == 0.0


def test_crash_is_a_failure_not_a_clean_pass():
    """A collection error must never be reported as zero failures."""
    r = parse_pytest_output("", "ImportError: No module named 'app'", 2)
    assert r["parse_ok"] is False
    assert r["failed"] >= 1
    assert r["passed"] == 0
    assert "ImportError" in r["failures"][0]["error"]


def test_empty_output_is_a_failure():
    r = parse_pytest_output("", "", 127)
    assert r["failed"] >= 1
    assert r["parse_ok"] is False


def test_no_tests_collected_parses_without_inventing_failures():
    r = parse_pytest_output("collected 0 items\n===== no tests ran in 0.01s =====", "", 5)
    assert r["parse_ok"] is True
    assert r["total"] == 0
    # exit code was non-zero, so it must not look like success
    assert r["failed"] == 1


def test_nonzero_exit_without_parsed_failure_still_fails():
    r = parse_pytest_output("===== 3 passed in 0.2s =====", "", 1)
    assert r["failed"] == 1


def test_failure_without_message_still_recorded():
    out = "FAILED tests/test_x.py::test_y\n===== 1 failed in 0.1s ====="
    r = parse_pytest_output(out, "", 1)
    assert r["failures"][0]["test_name"] == "tests/test_x.py::test_y"
    assert r["failures"][0]["error"]
