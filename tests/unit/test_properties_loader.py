"""
Unit tests for core/properties_loader.py - no browser, no Excel, pure
file-parsing and variable-resolution logic.
"""
import os
import pytest

from core.properties_loader import parse_properties_file, CasePropertyStore
from core.exceptions import PropertiesNotFoundError, UnresolvedVariableError, VariableCaptureError


@pytest.fixture
def properties_file(tmp_path):
    def _make(content: str, name: str = "demo.properties"):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path
    return _make


def test_parses_simple_key_value(properties_file):
    path = properties_file("usernameField=input[name='username']\npasswordField=input[name='password']\n")
    result = parse_properties_file(path, config_env_variables={})
    assert result == {
        "usernameField": "input[name='username']",
        "passwordField": "input[name='password']",
    }


def test_skips_comments_and_blank_lines(properties_file):
    path = properties_file("# a comment\n\nusernameField=foo\n   \n# another\npasswordField=bar\n")
    result = parse_properties_file(path, config_env_variables={})
    assert result == {"usernameField": "foo", "passwordField": "bar"}


def test_missing_file_raises(tmp_path):
    with pytest.raises(PropertiesNotFoundError):
        parse_properties_file(tmp_path / "does_not_exist.properties", config_env_variables={})


def test_env_token_prefers_os_environ(properties_file, monkeypatch):
    monkeypatch.setenv("DEMO_USER", "from_os_environ")
    path = properties_file("demoUsername={{DEMO_USER}}\n")
    result = parse_properties_file(path, config_env_variables={"DEMO_USER": "from_config_fallback"})
    assert result["demoUsername"] == "from_os_environ"


def test_env_token_falls_back_to_config(properties_file, monkeypatch):
    monkeypatch.delenv("DEMO_USER", raising=False)
    path = properties_file("demoUsername={{DEMO_USER}}\n")
    result = parse_properties_file(path, config_env_variables={"DEMO_USER": "from_config_fallback"})
    assert result["demoUsername"] == "from_config_fallback"


def test_unresolved_env_token_raises(properties_file, monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    path = properties_file("secret={{MISSING_VAR}}\n")
    with pytest.raises(UnresolvedVariableError):
        parse_properties_file(path, config_env_variables={})


class TestCasePropertyStore:
    def test_non_dollar_value_passes_through_unchanged(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        assert store.resolve("input[name='username']") == "input[name='username']"
        assert store.resolve("") == ""

    def test_dollar_reference_resolves_after_load(self, tmp_path):
        (tmp_path / "login.properties").write_text("usernameField=input[name='username']\n", encoding="utf-8")
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.load("login")
        assert store.resolve("$usernameField") == "input[name='username']"

    def test_dollar_reference_before_load_raises(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        with pytest.raises(UnresolvedVariableError):
            store.resolve("$usernameField")

    def test_unknown_key_after_load_raises(self, tmp_path):
        (tmp_path / "login.properties").write_text("usernameField=foo\n", encoding="utf-8")
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.load("login")
        with pytest.raises(UnresolvedVariableError):
            store.resolve("$nonExistentKey")

    def test_two_instances_do_not_leak_state(self, tmp_path):
        """Each test case gets its own CasePropertyStore - loading properties
        in one instance must not make them visible in another."""
        (tmp_path / "login.properties").write_text("usernameField=foo\n", encoding="utf-8")
        store_a = CasePropertyStore(str(tmp_path), config_env_variables={})
        store_b = CasePropertyStore(str(tmp_path), config_env_variables={})
        store_a.load("login")
        assert store_a.resolve("$usernameField") == "foo"
        with pytest.raises(UnresolvedVariableError):
            store_b.resolve("$usernameField")


class TestResolveEmbedded:
    """resolve_embedded() - the opt-in substitute-anywhere-in-the-string
    method used by keywords/api_keywords.py for URLs/bodies/headers."""

    def test_substitutes_var_inside_larger_string(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.capture("bookingId", "42")
        assert store.resolve_embedded("https://api.example.com/booking/$bookingId") == "https://api.example.com/booking/42"

    def test_substitutes_multiple_vars(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.capture("authToken", "abc123")
        store.capture("userId", "7")
        result = store.resolve_embedded('{"Cookie": "token=$authToken", "X-User": "$userId"}')
        assert result == '{"Cookie": "token=abc123", "X-User": "7"}'

    def test_plain_string_with_no_dollar_sign_passes_through(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        assert store.resolve_embedded("https://api.example.com/booking") == "https://api.example.com/booking"

    def test_empty_string_passes_through(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        assert store.resolve_embedded("") == ""

    def test_unresolved_embedded_var_raises(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        with pytest.raises(UnresolvedVariableError):
            store.resolve_embedded("https://api.example.com/booking/$missingId")

    def test_checks_captured_before_loaded_same_as_resolve(self, tmp_path):
        (tmp_path / "api.properties").write_text("bookingId=999\n", encoding="utf-8")
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.load("api")
        assert store.resolve_embedded("id=$bookingId") == "id=999"


class TestCapture:
    """Runtime (SaveAs) side of variable resolution, layered on top of the
    static (LoadProperties) side above."""

    def test_captured_value_resolves(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.capture("orderId", "ORD-4821")
        assert store.resolve("$orderId") == "ORD-4821"

    def test_capture_before_any_load_still_resolves(self, tmp_path):
        """Capture must not depend on LoadProperties ever having run."""
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.capture("sessionToken", "abc123")
        assert store.resolve("$sessionToken") == "abc123"

    def test_capture_takes_precedence_check_order_does_not_matter(self, tmp_path):
        """Captured and loaded names are mutually exclusive (collisions are
        rejected on write, tested below) - this just confirms a captured
        value resolves regardless of what else has been loaded."""
        (tmp_path / "login.properties").write_text("usernameField=foo\n", encoding="utf-8")
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.load("login")
        store.capture("orderId", "ORD-1")
        assert store.resolve("$usernameField") == "foo"
        assert store.resolve("$orderId") == "ORD-1"

    def test_capture_invalid_name_raises(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        with pytest.raises(VariableCaptureError):
            store.capture("not a valid name", "x")

    def test_capture_colliding_with_loaded_property_raises(self, tmp_path):
        (tmp_path / "login.properties").write_text("usernameField=foo\n", encoding="utf-8")
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.load("login")
        with pytest.raises(VariableCaptureError):
            store.capture("usernameField", "bar")

    def test_load_colliding_with_captured_name_raises(self, tmp_path):
        (tmp_path / "login.properties").write_text("orderId=foo\n", encoding="utf-8")
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.capture("orderId", "ORD-1")
        with pytest.raises(VariableCaptureError):
            store.load("login")

    def test_recapture_same_name_overwrites(self, tmp_path):
        store = CasePropertyStore(str(tmp_path), config_env_variables={})
        store.capture("orderId", "ORD-1")
        store.capture("orderId", "ORD-2")
        assert store.resolve("$orderId") == "ORD-2"

    def test_two_instances_do_not_leak_captured_state(self, tmp_path):
        store_a = CasePropertyStore(str(tmp_path), config_env_variables={})
        store_b = CasePropertyStore(str(tmp_path), config_env_variables={})
        store_a.capture("orderId", "ORD-1")
        assert store_a.resolve("$orderId") == "ORD-1"
        with pytest.raises(UnresolvedVariableError):
            store_b.resolve("$orderId")
