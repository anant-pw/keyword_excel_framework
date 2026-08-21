"""
Unit tests for the data-driven (DataSource column) expansion in
core/excel_reader.py - one Test Scenario definition, run once per labeled
row of a companion data sheet in the SAME workbook. See the module
docstring on core/excel_reader.py for the column schema.
"""
import openpyxl
import pytest

from core.excel_reader import read_test_suite
from core.exceptions import InvalidTestDataError

STEPS_HEADER = ["TestCase ID", "Test Scenario", "Test Case Description", "Keyword/Action",
                "LocatorType", "LocatorValue", "Test Data", "Expected Output", "Suite", "DataSource"]


def _write_workbook(tmp_path, step_rows, data_sheet_name=None, data_header=None, data_rows=None,
                     filename="Sheet.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TestSteps"
    ws.append(STEPS_HEADER)
    for row in step_rows:
        ws.append(row)

    if data_sheet_name is not None:
        data_ws = wb.create_sheet(data_sheet_name)
        if data_header is not None:
            data_ws.append(data_header)
        for row in (data_rows or []):
            data_ws.append(row)

    path = tmp_path / filename
    wb.save(path)
    return path


def _basic_case(scenario="Login Test", data_source="LoginCreds"):
    """A 1-step case referencing a DataSource on its only (=first) row."""
    return [[1, scenario, "log in", "Type", "css", "#user", "$username", "", "Smoke", data_source]]


def test_scenario_without_data_source_is_unaffected(tmp_path):
    rows = [[1, "Flow", "click it", "Click", "css", "#x", "", "", "Smoke", ""]]
    path = _write_workbook(tmp_path, rows)
    cases = read_test_suite(str(path))
    assert len(cases) == 1
    assert cases[0].test_scenario == "Flow"
    assert cases[0].data_row == {}


def test_data_driven_expands_into_one_case_per_row(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["Label", "username", "password"],
        data_rows=[
            ["Valid login", "demo", "demo123"],
            ["Empty password", "demo", ""],
        ],
    )
    cases = read_test_suite(str(path))

    assert [c.test_scenario for c in cases] == [
        "Login Test [Valid login]",
        "Login Test [Empty password]",
    ]
    assert cases[0].data_row == {"username": "demo", "password": "demo123"}
    assert cases[1].data_row == {"username": "demo", "password": ""}
    # Label itself is not carried into data_row - it's consumed for naming only
    assert "Label" not in cases[0].data_row


def test_expanded_cases_share_the_same_steps(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["Label", "username"],
        data_rows=[["Row A", "a"], ["Row B", "b"]],
    )
    cases = read_test_suite(str(path))
    assert cases[0].steps == cases[1].steps  # same step objects, different data_row


def test_missing_data_source_sheet_raises(tmp_path):
    path = _write_workbook(tmp_path, _basic_case(data_source="DoesNotExist"))
    with pytest.raises(InvalidTestDataError, match="DoesNotExist"):
        read_test_suite(str(path))


def test_data_source_sheet_without_label_column_raises(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["username", "password"],  # no Label
        data_rows=[["demo", "demo123"]],
    )
    with pytest.raises(InvalidTestDataError, match="Label"):
        read_test_suite(str(path))


def test_data_source_sheet_with_no_data_columns_raises(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["Label"],  # Label only, nothing to capture
        data_rows=[["Row A"]],
    )
    with pytest.raises(InvalidTestDataError, match="no data columns"):
        read_test_suite(str(path))


def test_data_source_sheet_with_zero_data_rows_raises(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["Label", "username"],
        data_rows=[],
    )
    with pytest.raises(InvalidTestDataError, match="zero data rows"):
        read_test_suite(str(path))


def test_data_source_row_missing_label_raises(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["Label", "username"],
        data_rows=[["Valid login", "demo"], ["", "someone"]],
    )
    with pytest.raises(InvalidTestDataError, match="Label is required on every row"):
        read_test_suite(str(path))


def test_duplicate_labels_raise(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["Label", "username"],
        data_rows=[["Same Label", "a"], ["Same Label", "b"]],
    )
    with pytest.raises(InvalidTestDataError, match="duplicate Label"):
        read_test_suite(str(path))


def test_invalid_variable_name_column_raises(tmp_path):
    path = _write_workbook(
        tmp_path, _basic_case(),
        data_sheet_name="LoginCreds",
        data_header=["Label", "user name"],  # space - not a valid $variable
        data_rows=[["Row A", "demo"]],
    )
    with pytest.raises(InvalidTestDataError, match="not a valid \\$variable name|isn't a valid"):
        read_test_suite(str(path))


def test_only_first_row_of_scenario_is_consulted_for_data_source(tmp_path):
    """DataSource is a scenario-level attribute - it doesn't need repeating
    on every row (unlike Suite), and a value on a LATER row is ignored."""
    rows = [
        [1, "Login Test", "log in", "Type", "css", "#user", "$username", "", "Smoke", "LoginCreds"],
        [2, "Login Test", "submit", "Click", "css", "#submit", "", "", "Smoke", ""],
    ]
    path = _write_workbook(
        tmp_path, rows,
        data_sheet_name="LoginCreds",
        data_header=["Label", "username"],
        data_rows=[["Row A", "demo"]],
    )
    cases = read_test_suite(str(path))
    assert len(cases) == 1
    assert cases[0].test_scenario == "Login Test [Row A]"
    assert len(cases[0].steps) == 2


def test_suite_filter_applies_before_expansion(tmp_path):
    """A data-driven scenario whose steps don't match the requested suite
    is dropped entirely, same as a non-data-driven scenario - it never
    reaches the DataSource sheet at all."""
    rows = [[1, "Login Test", "log in", "Type", "css", "#user", "$username", "", "Regression", "LoginCreds"]]
    path = _write_workbook(
        tmp_path, rows,
        data_sheet_name="LoginCreds",
        data_header=["Label", "username"],
        data_rows=[["Row A", "demo"]],
    )
    cases = read_test_suite(str(path), suite_filter="Smoke")
    assert cases == []
