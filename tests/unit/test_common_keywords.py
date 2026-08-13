"""
Unit tests for core/common_keywords.py (registration/collision detection)
and the composite-keyword execution path in tests/runner.py (nesting,
shared CasePropertyStore, recursion guard) - all without a real browser.
"""
import openpyxl
from unittest.mock import MagicMock
import pytest

from core.common_keywords import CommonKeywordRegistry, CommonKeywordCollisionError
from core.config_loader import RunConfig
from core.exceptions import AssertionFailedError
import tests.runner as runner_module

HEADER = ["TestCase ID", "Test Scenario", "Test Case Description", "Keyword/Action",
          "LocatorType", "LocatorValue", "Test Data", "Expected Output", "Suite"]


def _write_common_file(path, scenario_name, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TestSteps"
    ws.append(HEADER)
    for row in rows:
        ws.append(row)
    wb.save(path)


# ---- Registry / collision tests ----

def test_registers_scenario_as_lookup_key(tmp_path):
    common_dir = tmp_path / "common"
    common_dir.mkdir()
    _write_common_file(common_dir / "login.xlsx", "LoginFlow", [
        [1, "LoginFlow", "step", "Navigate", "", "", "http://x", "", "Smoke"],
    ])
    registry = CommonKeywordRegistry()
    registry.load(str(common_dir), builtin_keyword_names=set())
    assert "LoginFlow" in registry
    assert "loginflow" in registry  # case-insensitive
    assert registry.get("LoginFlow").test_scenario == "LoginFlow"


def test_missing_common_dir_does_not_raise(tmp_path):
    registry = CommonKeywordRegistry()
    registry.load(str(tmp_path / "does_not_exist"), builtin_keyword_names=set())
    assert "Anything" not in registry


def test_duplicate_scenario_name_across_files_raises(tmp_path):
    common_dir = tmp_path / "common"
    common_dir.mkdir()
    rows = [[1, "SharedName", "step", "Navigate", "", "", "http://x", "", "Smoke"]]
    _write_common_file(common_dir / "a.xlsx", "SharedName", rows)
    _write_common_file(common_dir / "b.xlsx", "SharedName", rows)
    registry = CommonKeywordRegistry()
    with pytest.raises(CommonKeywordCollisionError, match="defined in both"):
        registry.load(str(common_dir), builtin_keyword_names=set())


def test_collision_with_builtin_keyword_name_raises(tmp_path):
    common_dir = tmp_path / "common"
    common_dir.mkdir()
    _write_common_file(common_dir / "a.xlsx", "Click", [
        [1, "Click", "step", "Navigate", "", "", "http://x", "", "Smoke"],
    ])
    registry = CommonKeywordRegistry()
    with pytest.raises(CommonKeywordCollisionError, match="collides with a built-in keyword"):
        registry.load(str(common_dir), builtin_keyword_names={"click"})


# ---- Execution tests (composite nesting, shared properties, recursion guard) ----

def make_config(tmp_path):
    return RunConfig(report_dir=str(tmp_path), screenshot_on_failure=False,
                      properties_dir=str(tmp_path / "properties"), common_dir=str(tmp_path / "common"))


@pytest.fixture(autouse=True)
def isolate_common_registry(monkeypatch):
    """runner.common_registry is module-global - swap in a fresh empty one
    per test so tests don't leak composite keywords into each other."""
    fresh = CommonKeywordRegistry()
    monkeypatch.setattr(runner_module, "common_registry", fresh)
    return fresh


def test_composite_keyword_executes_nested_and_reports_children(monkeypatch, tmp_path):
    from core.excel_reader import TestCase, TestStep

    composite_case = TestCase(test_scenario="LoginFlow", steps=[
        TestStep(row_id=101, test_scenario="LoginFlow", description="inner step 1",
                 keyword="Click", locator_type="css", locator_value="#a", test_data="",
                 expected_output="", suite=""),
    ])
    registry = CommonKeywordRegistry()
    registry._entries["loginflow"] = (composite_case, "login.xlsx")
    monkeypatch.setattr(runner_module, "common_registry", registry)
    monkeypatch.setattr(runner_module, "execute_step", MagicMock())  # inner step passes

    calling_case = TestCase(test_scenario="Profile Check", steps=[
        TestStep(row_id=1, test_scenario="Profile Check", description="log in first",
                 keyword="LoginFlow", locator_type="", locator_value="", test_data="",
                 expected_output="", suite="Smoke"),
    ])
    result = runner_module.run_test_case(MagicMock(), calling_case, make_config(tmp_path), fail_fast=True)

    assert result.status == "PASS"
    assert result.step_results[0].children[0].description == "inner step 1"


def test_composite_failure_propagates_to_parent_and_respects_fail_fast(monkeypatch, tmp_path):
    from core.excel_reader import TestCase, TestStep

    composite_case = TestCase(test_scenario="LoginFlow", steps=[
        TestStep(row_id=101, test_scenario="LoginFlow", description="inner fails",
                 keyword="Click", locator_type="css", locator_value="#a", test_data="",
                 expected_output="", suite=""),
    ])
    registry = CommonKeywordRegistry()
    registry._entries["loginflow"] = (composite_case, "login.xlsx")
    monkeypatch.setattr(runner_module, "common_registry", registry)

    def fake_execute(page, step, config, case_properties, api_context):
        raise AssertionFailedError("inner boom")
    monkeypatch.setattr(runner_module, "execute_step", fake_execute)

    calling_case = TestCase(test_scenario="Profile Check", steps=[
        TestStep(row_id=1, test_scenario="Profile Check", description="log in",
                 keyword="LoginFlow", locator_type="", locator_value="", test_data="",
                 expected_output="", suite="Smoke"),
        TestStep(row_id=2, test_scenario="Profile Check", description="should be skipped",
                 keyword="Click", locator_type="css", locator_value="#b", test_data="",
                 expected_output="", suite="Smoke"),
    ])
    result = runner_module.run_test_case(MagicMock(), calling_case, make_config(tmp_path), fail_fast=True)

    assert result.status == "FAIL"
    assert result.step_results[0].status == "FAIL"
    assert result.step_results[1].status == "SKIPPED"  # parent fail-fast triggered by composite failure


def test_recursion_guard_prevents_self_call(monkeypatch, tmp_path):
    from core.excel_reader import TestCase, TestStep

    # "Loopy" calls itself
    composite_case = TestCase(test_scenario="Loopy", steps=[
        TestStep(row_id=101, test_scenario="Loopy", description="calls itself",
                 keyword="Loopy", locator_type="", locator_value="", test_data="",
                 expected_output="", suite=""),
    ])
    registry = CommonKeywordRegistry()
    registry._entries["loopy"] = (composite_case, "loop.xlsx")
    monkeypatch.setattr(runner_module, "common_registry", registry)

    calling_case = TestCase(test_scenario="Caller", steps=[
        TestStep(row_id=1, test_scenario="Caller", description="calls Loopy",
                 keyword="Loopy", locator_type="", locator_value="", test_data="",
                 expected_output="", suite="Smoke"),
    ])
    result = runner_module.run_test_case(MagicMock(), calling_case, make_config(tmp_path), fail_fast=True)

    assert result.status == "FAIL"
    inner = result.step_results[0].children[0]
    assert inner.status == "FAIL"
    assert "recursive" in inner.message.lower()
