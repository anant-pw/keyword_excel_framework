"""
Unit tests for core/locator_resolver.py - Page/Locator are mocked, no real
browser needed. Verifies strategy dispatch and the "any" fallback chain.
"""
import json
from unittest.mock import MagicMock
import pytest
from playwright.sync_api import TimeoutError as PWTimeoutError

from core.locator_resolver import resolve_locator, _build_locator
from core.exceptions import LocatorNotFoundError


def make_page(locator_mock=None):
    page = MagicMock()
    locator_mock = locator_mock or MagicMock()
    page.locator.return_value = locator_mock
    page.get_by_text.return_value = locator_mock
    page.get_by_role.return_value = locator_mock
    page.get_by_test_id.return_value = locator_mock
    page.get_by_placeholder.return_value = locator_mock
    return page, locator_mock


@pytest.mark.parametrize("locator_type,locator_value,expected_call", [
    ("id", "submit-btn", ("locator", "#submit-btn")),
    ("css", "button.submit", ("locator", "button.submit")),
    ("xpath", "//button", ("locator", "xpath=//button")),
    ("name", "email", ("locator", "[name='email']")),
])
def test_simple_strategy_dispatch(locator_type, locator_value, expected_call):
    page, locator = make_page()
    result = _build_locator(page, locator_type, locator_value)
    method, arg = expected_call
    getattr(page, method).assert_called_once_with(arg)
    assert result is locator


def test_role_strategy_splits_role_and_name():
    page, locator = make_page()
    _build_locator(page, "role", "button::Log in")
    page.get_by_role.assert_called_once_with("button", name="Log in")


def test_role_strategy_without_name():
    page, locator = make_page()
    _build_locator(page, "role", "button")
    page.get_by_role.assert_called_once_with("button", name=None)


def test_unknown_locator_type_raises():
    page, _ = make_page()
    with pytest.raises(LocatorNotFoundError, match="Unknown LocatorType"):
        _build_locator(page, "bogus", "whatever")


def test_resolve_locator_success():
    page, locator = make_page()
    result = resolve_locator(page, "css", "#foo", timeout_ms=1000)
    locator.wait_for.assert_called_once_with(state="attached", timeout=1000)
    assert result is locator


def test_resolve_locator_timeout_raises_locator_not_found():
    page, locator = make_page()
    locator.wait_for.side_effect = PWTimeoutError("timed out")
    with pytest.raises(LocatorNotFoundError, match="Element not found"):
        resolve_locator(page, "css", "#foo", timeout_ms=1000)


class TestAnyFallbackChain:
    def test_first_strategy_resolves(self):
        page, locator = make_page()
        strategies = json.dumps({"css": "#a", "xpath": "//b"})
        result = resolve_locator(page, "any", strategies, timeout_ms=500)
        page.locator.assert_called_once_with("#a")
        assert result is locator

    def test_falls_back_when_first_strategy_times_out(self):
        page = MagicMock()
        css_locator = MagicMock()
        css_locator.wait_for.side_effect = PWTimeoutError("nope")
        xpath_locator = MagicMock()
        page.locator.side_effect = [css_locator, xpath_locator]  # css then xpath calls both use page.locator
        strategies = json.dumps({"css": "#a", "xpath": "//b"})
        result = resolve_locator(page, "any", strategies, timeout_ms=500)
        assert result is xpath_locator

    def test_raises_when_no_strategy_resolves(self):
        page = MagicMock()
        failing_locator = MagicMock()
        failing_locator.wait_for.side_effect = PWTimeoutError("nope")
        page.locator.return_value = failing_locator
        strategies = json.dumps({"css": "#a", "xpath": "//b"})
        with pytest.raises(LocatorNotFoundError, match="None of the strategies"):
            resolve_locator(page, "any", strategies, timeout_ms=500)

    def test_invalid_json_raises(self):
        page, _ = make_page()
        with pytest.raises(LocatorNotFoundError, match="requires LocatorValue to be a JSON"):
            resolve_locator(page, "any", "not valid json", timeout_ms=500)
