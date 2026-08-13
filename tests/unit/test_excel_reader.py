"""
Unit tests for core/excel_reader.py - builds small workbooks in a tmp_path
fixture rather than depending on testsheets/TestSuite.xlsx, so these don't
break if the sample sheet changes.
"""
import openpyxl
import pytest

from core.excel_reader import read_test_suite
from core.exceptions import InvalidTestDataError

HEADER = ["TestCase ID", "Test Scenario", "Test Case Description", "Keyword/Action",
          "LocatorType", "LocatorValue", "Test Data", "Expected Output", "Suite"]


def _write_sheet(tmp_path, rows, filename="Sheet.xlsx", header=HEADER):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TestSteps"
    ws.append(header)
    for row in rows:
        ws.append(row)
    path = tmp_path / filename
    wb.save(path)
    return path


HEADER_WITH_SAVE_AS = HEADER + ["SaveAs"]


def test_api_get_requires_locator_value_as_url(tmp_path):
    rows = [[1, "Flow", "hit the api", "ApiGet", "", "", "", "", "Smoke"]]
    path = _write_sheet(tmp_path, rows)
    with pytest.raises(InvalidTestDataError):
        read_test_suite(str(path))


def test_api_get_with_url_in_locator_value_is_accepted(tmp_path):
    rows = [[1, "Flow", "hit the api", "ApiGet", "", "https://example.com/orders", "", "", "Smoke"]]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path))
    assert cases[0].steps[0].locator_value == "https://example.com/orders"


def test_save_json_path_save_as_capable(tmp_path):
    rows = [[1, "Flow", "extract order id", "SaveJsonPath", "", "", "data.orderId", "", "Smoke", "orderId"]]
    path = _write_sheet(tmp_path, rows, header=HEADER_WITH_SAVE_AS)
    cases = read_test_suite(str(path))
    assert cases[0].steps[0].save_as == "orderId"


def test_verify_status_code_does_not_require_locator(tmp_path):
    rows = [[1, "Flow", "check status", "VerifyStatusCode", "", "", "200", "", "Smoke"]]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path))
    assert cases[0].steps[0].keyword == "VerifyStatusCode"


def test_save_as_column_absent_defaults_to_empty(tmp_path):
    """Older sheets with no SaveAs column at all must keep working exactly
    as before - save_as defaults to ''."""
    rows = [[1, "Flow", "step a", "Navigate", "", "", "http://x", "", "Smoke"]]
    path = _write_sheet(tmp_path, rows, header=HEADER)
    cases = read_test_suite(str(path))
    assert cases[0].steps[0].save_as == ""


def test_save_as_captured_on_capable_keyword(tmp_path):
    rows = [
        [1, "Flow", "grab order id", "SaveText", "css", "#order-id", "", "", "Smoke", "orderId"],
    ]
    path = _write_sheet(tmp_path, rows, header=HEADER_WITH_SAVE_AS)
    cases = read_test_suite(str(path))
    assert cases[0].steps[0].save_as == "orderId"


def test_save_as_on_non_capable_keyword_raises(tmp_path):
    rows = [
        [1, "Flow", "click it", "Click", "css", "#btn", "", "", "Smoke", "orderId"],
    ]
    path = _write_sheet(tmp_path, rows, header=HEADER_WITH_SAVE_AS)
    with pytest.raises(InvalidTestDataError):
        read_test_suite(str(path))


def test_generate_value_does_not_require_locator(tmp_path):
    """GenerateValue is SaveAs-capable but not locator-required."""
    rows = [
        [1, "Flow", "make a unique id", "GenerateValue", "", "", "uuid:8", "", "Smoke", "shortId"],
    ]
    path = _write_sheet(tmp_path, rows, header=HEADER_WITH_SAVE_AS)
    cases = read_test_suite(str(path))
    assert cases[0].steps[0].save_as == "shortId"


def test_use_session_as_first_step_is_accepted(tmp_path):
    rows = [
        [1, "Dashboard", "reuse login", "UseSession", "", "", "loggedInUser", "", "Smoke"],
        [2, "Dashboard", "go to dashboard", "Navigate", "", "", "http://x/dash", "", "Smoke"],
    ]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path))
    assert cases[0].steps[0].keyword == "UseSession"


def test_use_session_not_first_step_raises(tmp_path):
    rows = [
        [1, "Dashboard", "go to dashboard", "Navigate", "", "", "http://x/dash", "", "Smoke"],
        [2, "Dashboard", "reuse login", "UseSession", "", "", "loggedInUser", "", "Smoke"],
    ]
    path = _write_sheet(tmp_path, rows)
    with pytest.raises(InvalidTestDataError):
        read_test_suite(str(path))


def test_groups_by_test_scenario_not_by_row_id(tmp_path):
    rows = [
        [1, "Login Flow", "step a", "Navigate", "", "", "http://x", "", "Smoke"],
        [2, "Login Flow", "step b", "Click", "css", "#btn", "", "", "Smoke"],
        [3, "Other Flow", "step c", "Navigate", "", "", "http://y", "", "Smoke"],
    ]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path))
    assert [c.test_scenario for c in cases] == ["Login Flow", "Other Flow"]
    assert len(cases[0].steps) == 2
    assert len(cases[1].steps) == 1


def test_steps_ordered_by_row_id_even_if_sheet_order_differs(tmp_path):
    rows = [
        [2, "Flow A", "second", "Click", "css", "#btn", "", "", "Smoke"],
        [1, "Flow A", "first", "Navigate", "", "", "http://x", "", "Smoke"],
    ]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path))
    assert [s.description for s in cases[0].steps] == ["first", "second"]


def test_missing_required_column_raises(tmp_path):
    bad_header = [h for h in HEADER if h != "Suite"]
    rows = [[1, "Flow A", "step", "Navigate", "", "", "http://x", ""]]
    path = _write_sheet(tmp_path, rows, header=bad_header)
    with pytest.raises(InvalidTestDataError, match="Missing required columns"):
        read_test_suite(str(path))


def test_blank_separator_row_is_skipped(tmp_path):
    rows = [
        [1, "Flow A", "step", "Navigate", "", "", "http://x", "", "Smoke"],
        [None, None, None, None, None, None, None, None, None],
        [2, "Flow A", "step2", "Click", "css", "#btn", "", "", "Smoke"],
    ]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path))
    assert len(cases[0].steps) == 2


def test_locator_required_keyword_without_locator_raises(tmp_path):
    rows = [[1, "Flow A", "step", "Click", "css", "", "", "", "Smoke"]]  # Click with blank LocatorValue
    path = _write_sheet(tmp_path, rows)
    with pytest.raises(InvalidTestDataError, match="requires LocatorValue"):
        read_test_suite(str(path))


def test_loadproperties_does_not_require_locator(tmp_path):
    rows = [[1, "Flow A", "step", "LoadProperties", "", "", "login", "", "Smoke"]]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path))  # should not raise
    assert cases[0].steps[0].keyword == "LoadProperties"


def test_single_suite_filter_matches_exact(tmp_path):
    rows = [
        [1, "Flow A", "step", "Navigate", "", "", "http://x", "", "Smoke"],
        [2, "Flow A", "step2", "Click", "css", "#btn", "", "", "Sanity"],
    ]
    path = _write_sheet(tmp_path, rows)
    smoke_cases = read_test_suite(str(path), suite_filter="Smoke")
    assert len(smoke_cases[0].steps) == 1
    assert smoke_cases[0].steps[0].description == "step"


def test_comma_separated_suite_matches_any_listed_suite(tmp_path):
    rows = [
        [1, "Flow A", "shared setup", "Navigate", "", "", "http://x", "", "Sanity,Regression"],
        [2, "Flow A", "sanity only", "Click", "css", "#btn", "", "", "Sanity"],
    ]
    path = _write_sheet(tmp_path, rows)
    sanity_cases = read_test_suite(str(path), suite_filter="Sanity")
    regression_cases = read_test_suite(str(path), suite_filter="Regression")
    assert len(sanity_cases[0].steps) == 2       # both rows match Sanity
    assert len(regression_cases[0].steps) == 1   # only the shared-setup row matches Regression


def test_blank_suite_means_never_runs(tmp_path):
    rows = [[1, "Flow A", "step", "Navigate", "", "", "http://x", "", ""]]
    path = _write_sheet(tmp_path, rows)
    for suite in ("Smoke", "Sanity", "Regression"):
        cases = read_test_suite(str(path), suite_filter=suite)
        assert cases == []


def test_case_dropped_entirely_when_no_steps_match_filter(tmp_path):
    rows = [[1, "Flow A", "step", "Navigate", "", "", "http://x", "", "Smoke"]]
    path = _write_sheet(tmp_path, rows)
    cases = read_test_suite(str(path), suite_filter="Regression")
    assert cases == []
