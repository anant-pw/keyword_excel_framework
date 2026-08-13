"""
Unit tests for the fail-fast / continue-on-failure branch in tests/runner.py.
execute_step and the Playwright page are mocked out entirely - this tests
control flow only, no browser required.
"""
from unittest.mock import MagicMock
import pytest

from core.excel_reader import TestCase, TestStep
from core.exceptions import AssertionFailedError
from core.config_loader import RunConfig
import tests.runner as runner


def make_step(row_id, keyword="Click", suite="Smoke"):
    return TestStep(
        row_id=row_id, test_scenario="Demo Flow", description=f"step {row_id}",
        keyword=keyword, locator_type="css", locator_value="#x", test_data="",
        expected_output="", suite=suite,
    )


def make_case(n_steps):
    return TestCase(test_scenario="Demo Flow", steps=[make_step(i) for i in range(1, n_steps + 1)])


def make_config(tmp_path, screenshot_on_failure=False):
    return RunConfig(report_dir=str(tmp_path), screenshot_on_failure=screenshot_on_failure)


def test_all_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "execute_step", MagicMock())
    case = make_case(3)
    result = runner.run_test_case(MagicMock(), case, make_config(tmp_path), fail_fast=True)
    assert result.status == "PASS"
    assert [s.status for s in result.step_results] == ["PASS", "PASS", "PASS"]


def test_fail_fast_stops_and_skips_remaining(monkeypatch, tmp_path):
    def fake_execute(page, step, config, case_properties, api_context):
        if step.row_id == 2:
            raise AssertionFailedError("boom")
    monkeypatch.setattr(runner, "execute_step", fake_execute)

    case = make_case(3)
    result = runner.run_test_case(MagicMock(), case, make_config(tmp_path), fail_fast=True)

    statuses = [s.status for s in result.step_results]
    assert statuses == ["PASS", "FAIL", "SKIPPED"]
    assert result.status == "FAIL"
    assert "prior step failed" in result.step_results[2].message.lower()


def test_continue_on_failure_runs_all_steps(monkeypatch, tmp_path):
    def fake_execute(page, step, config, case_properties, api_context):
        if step.row_id == 2:
            raise AssertionFailedError("boom")
    monkeypatch.setattr(runner, "execute_step", fake_execute)

    case = make_case(3)
    result = runner.run_test_case(MagicMock(), case, make_config(tmp_path), fail_fast=False)

    statuses = [s.status for s in result.step_results]
    assert statuses == ["PASS", "FAIL", "PASS"]
    assert result.status == "FAIL"


def test_case_passes_only_if_no_step_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "execute_step", MagicMock())
    case = make_case(2)
    result = runner.run_test_case(MagicMock(), case, make_config(tmp_path), fail_fast=False)
    assert result.status == "PASS"


def test_screenshot_captured_on_failure_when_enabled(monkeypatch, tmp_path):
    def fake_execute(page, step, config, case_properties, api_context):
        raise AssertionFailedError("boom")
    monkeypatch.setattr(runner, "execute_step", fake_execute)

    page = MagicMock()
    case = make_case(1)
    result = runner.run_test_case(page, case, make_config(tmp_path, screenshot_on_failure=True), fail_fast=True)

    page.screenshot.assert_called_once()
    assert result.step_results[0].screenshot_path != ""


def test_no_screenshot_attempt_when_disabled(monkeypatch, tmp_path):
    def fake_execute(page, step, config, case_properties, api_context):
        raise AssertionFailedError("boom")
    monkeypatch.setattr(runner, "execute_step", fake_execute)

    page = MagicMock()
    case = make_case(1)
    runner.run_test_case(page, case, make_config(tmp_path, screenshot_on_failure=False), fail_fast=True)
    page.screenshot.assert_not_called()


def test_unexpected_non_framework_error_behaves_same_as_framework_error(monkeypatch, tmp_path):
    """A bug worth pinning down: an unexpected (non-FrameworkError) exception
    should be handled the same way as a FrameworkError - fail-fast still
    skips remaining steps, and the case is still marked FAIL. Regression
    test for an inconsistency found while writing this suite."""
    def fake_execute(page, step, config, case_properties, api_context):
        if step.row_id == 2:
            raise ValueError("something unrelated to the framework broke")
    monkeypatch.setattr(runner, "execute_step", fake_execute)

    case = make_case(3)
    result = runner.run_test_case(MagicMock(), case, make_config(tmp_path), fail_fast=True)

    statuses = [s.status for s in result.step_results]
    assert statuses == ["PASS", "FAIL", "SKIPPED"]
    assert result.status == "FAIL"
