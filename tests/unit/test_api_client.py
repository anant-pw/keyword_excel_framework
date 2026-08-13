"""
Unit tests for core/api_client.py - pure logic, no browser, mirrors the
style of tests/unit/test_session_manager.py and test_parallel.py.
"""
import pytest

from core.api_client import extract_json_path
from core.exceptions import InvalidTestDataError


class TestExtractJsonPath:
    def test_single_key(self):
        assert extract_json_path({"orderId": "ORD-1"}, "orderId") == "ORD-1"

    def test_nested_keys(self):
        data = {"data": {"order": {"id": "ORD-42"}}}
        assert extract_json_path(data, "data.order.id") == "ORD-42"

    def test_list_index(self):
        data = {"items": [{"id": "A"}, {"id": "B"}]}
        assert extract_json_path(data, "items[0].id") == "A"
        assert extract_json_path(data, "items[1].id") == "B"

    def test_bare_list_index_no_trailing_key(self):
        data = {"tags": ["red", "green", "blue"]}
        assert extract_json_path(data, "tags[2]") == "blue"

    def test_missing_key_raises_with_key_name(self, ):
        with pytest.raises(InvalidTestDataError, match="orderId"):
            extract_json_path({"other": 1}, "orderId")

    def test_index_out_of_range_raises(self):
        with pytest.raises(InvalidTestDataError, match="out of range"):
            extract_json_path({"items": [1, 2]}, "items[5]")

    def test_key_on_non_dict_raises(self):
        with pytest.raises(InvalidTestDataError):
            extract_json_path({"items": [1, 2]}, "items.id")

    def test_index_on_non_list_raises(self):
        with pytest.raises(InvalidTestDataError):
            extract_json_path({"items": {"a": 1}}, "items[0]")

    def test_empty_path_raises(self):
        with pytest.raises(InvalidTestDataError):
            extract_json_path({"a": 1}, "")

    def test_returns_non_string_values_as_is(self):
        assert extract_json_path({"count": 42}, "count") == 42
        assert extract_json_path({"active": True}, "active") is True
