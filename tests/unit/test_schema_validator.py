"""
Unit tests for core/schema_validator.py - pure logic, no browser, mirrors
the style of tests/unit/test_api_client.py.
"""
import json
import pytest

from core.schema_validator import load_schema, validate_against_schema
from core.exceptions import InvalidTestDataError, AssertionFailedError

_PRODUCT_SCHEMA = {
    "type": "object",
    "required": ["id", "title", "price"],
    "properties": {
        "id": {"type": "integer"},
        "title": {"type": "string"},
        "price": {"type": "number"},
    },
}


class TestLoadSchema:
    def test_inline_json_schema(self):
        schema = load_schema(json.dumps(_PRODUCT_SCHEMA), "schemas")
        assert schema == _PRODUCT_SCHEMA

    def test_schema_file_prefix_loads_from_dir(self, tmp_path):
        (tmp_path / "product.json").write_text(json.dumps(_PRODUCT_SCHEMA), encoding="utf-8")
        schema = load_schema("schema:product.json", str(tmp_path))
        assert schema == _PRODUCT_SCHEMA

    def test_missing_schema_file_raises(self, tmp_path):
        with pytest.raises(InvalidTestDataError, match="not found"):
            load_schema("schema:nope.json", str(tmp_path))

    def test_schema_prefix_with_no_filename_raises(self, tmp_path):
        with pytest.raises(InvalidTestDataError):
            load_schema("schema:", str(tmp_path))

    def test_malformed_json_file_raises(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")
        with pytest.raises(InvalidTestDataError):
            load_schema("schema:bad.json", str(tmp_path))

    def test_empty_test_data_raises(self):
        with pytest.raises(InvalidTestDataError):
            load_schema("", "schemas")

    def test_invalid_inline_json_raises(self):
        with pytest.raises(InvalidTestDataError):
            load_schema("{not valid", "schemas")


class TestValidateAgainstSchema:
    def test_valid_data_passes(self):
        validate_against_schema({"id": 1, "title": "Widget", "price": 9.99}, _PRODUCT_SCHEMA)  # no raise

    def test_missing_required_field_raises_assertion_error(self):
        with pytest.raises(AssertionFailedError, match="price"):
            validate_against_schema({"id": 1, "title": "Widget"}, _PRODUCT_SCHEMA)

    def test_wrong_type_raises_assertion_error(self):
        with pytest.raises(AssertionFailedError):
            validate_against_schema({"id": "not-an-int", "title": "Widget", "price": 9.99}, _PRODUCT_SCHEMA)

    def test_error_message_includes_field_path(self):
        nested_schema = {
            "type": "object",
            "properties": {"booking": {"type": "object", "required": ["firstname"]}},
        }
        with pytest.raises(AssertionFailedError, match="booking"):
            validate_against_schema({"booking": {}}, nested_schema)

    def test_malformed_schema_raises_invalid_test_data_error_not_assertion(self):
        # "type": "not-a-real-type" makes the SCHEMA itself invalid - this
        # must be reported as a contract-file bug (InvalidTestDataError),
        # not as the data under test failing an assertion.
        broken_schema = {"type": "not-a-real-type"}
        with pytest.raises(InvalidTestDataError):
            validate_against_schema({"a": 1}, broken_schema)
