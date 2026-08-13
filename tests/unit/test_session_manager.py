"""
Unit tests for core/session_manager.py - pure logic, no browser, mirrors
the style of tests/unit/test_parallel.py.
"""
import pytest

from core.excel_reader import TestCase, TestStep
from core.session_manager import (
    extract_session_directive, session_state_path, preflight_check_sessions,
)
from core.exceptions import SessionStateError


def _step(row_id, keyword, test_data="", **kw):
    return TestStep(
        row_id=row_id, test_scenario="Dashboard", description="", keyword=keyword,
        locator_type="", locator_value="", test_data=test_data, expected_output="", suite="Smoke", **kw
    )


class TestExtractSessionDirective:
    def test_no_use_session_step_returns_unchanged(self):
        case = TestCase(test_scenario="Dashboard", steps=[_step(1, "Navigate"), _step(2, "Click")])
        session_name, directive, effective = extract_session_directive(case)
        assert session_name is None
        assert directive is None
        assert effective is case

    def test_use_session_first_step_is_stripped(self):
        use_session = _step(1, "UseSession", test_data="loggedInUser")
        remaining = [_step(2, "Navigate"), _step(3, "Click")]
        case = TestCase(test_scenario="Dashboard", steps=[use_session] + remaining)
        session_name, directive, effective = extract_session_directive(case)
        assert session_name == "loggedInUser"
        assert directive is use_session
        assert effective.steps == remaining
        assert effective.test_scenario == "Dashboard"

    def test_blank_test_data_defaults_to_default_session(self):
        case = TestCase(test_scenario="Dashboard", steps=[_step(1, "UseSession", test_data="")])
        session_name, _, _ = extract_session_directive(case)
        assert session_name == "default"

    def test_case_matching_is_case_insensitive_and_trims_whitespace(self):
        case = TestCase(test_scenario="Dashboard", steps=[_step(1, "  UseSession ", test_data=" loggedInUser ")])
        session_name, _, _ = extract_session_directive(case)
        assert session_name == "loggedInUser"

    def test_original_test_case_object_not_mutated(self):
        use_session = _step(1, "UseSession", test_data="x")
        other = _step(2, "Navigate")
        case = TestCase(test_scenario="Dashboard", steps=[use_session, other])
        extract_session_directive(case)
        assert case.steps == [use_session, other]  # untouched


def test_session_state_path_builds_expected_json_path():
    assert str(session_state_path("sessions", "loggedInUser")) == "sessions/loggedInUser.json"


class TestPreflightCheckSessions:
    def test_no_use_session_cases_pass_silently(self, tmp_path):
        cases = [TestCase(test_scenario="A", steps=[_step(1, "Navigate")])]
        preflight_check_sessions(cases, str(tmp_path))  # no raise

    def test_existing_session_file_passes(self, tmp_path):
        (tmp_path / "loggedInUser.json").write_text("{}", encoding="utf-8")
        cases = [TestCase(test_scenario="Dashboard", steps=[_step(1, "UseSession", test_data="loggedInUser")])]
        preflight_check_sessions(cases, str(tmp_path))  # no raise

    def test_missing_session_file_raises(self, tmp_path):
        cases = [TestCase(test_scenario="Dashboard", steps=[_step(1, "UseSession", test_data="loggedInUser")])]
        with pytest.raises(SessionStateError):
            preflight_check_sessions(cases, str(tmp_path))

    def test_multiple_missing_sessions_reported_in_one_error(self, tmp_path):
        cases = [
            TestCase(test_scenario="Dashboard", steps=[_step(1, "UseSession", test_data="a")]),
            TestCase(test_scenario="Payment", steps=[_step(1, "UseSession", test_data="b")]),
        ]
        with pytest.raises(SessionStateError) as exc_info:
            preflight_check_sessions(cases, str(tmp_path))
        assert "Dashboard" in str(exc_info.value)
        assert "Payment" in str(exc_info.value)
