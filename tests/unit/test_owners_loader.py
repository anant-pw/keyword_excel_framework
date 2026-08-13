"""
Unit tests for core/owners_loader.py - pure logic, no browser, mirrors the
style of tests/unit/test_schema_validator.py.
"""
from core.owners_loader import load_owners, resolve_owner, warn_unmapped_scenarios


class TestLoadOwners:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert load_owners(str(tmp_path / "nope.yaml")) == {}

    def test_parses_and_lowercases_keys(self, tmp_path):
        f = tmp_path / "owners.yaml"
        f.write_text('owners:\n  "Search Flow": search-module@example.com\n', encoding="utf-8")
        assert load_owners(str(f)) == {"search flow": "search-module@example.com"}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / "owners.yaml"
        f.write_text("", encoding="utf-8")
        assert load_owners(str(f)) == {}

    def test_file_with_no_owners_key_returns_empty_dict(self, tmp_path):
        f = tmp_path / "owners.yaml"
        f.write_text("something_else: true\n", encoding="utf-8")
        assert load_owners(str(f)) == {}


class TestResolveOwner:
    def test_matches_case_insensitively(self):
        owners = {"search flow": "search-module@example.com"}
        assert resolve_owner(owners, "Search Flow") == "search-module@example.com"

    def test_unmapped_scenario_returns_unowned(self):
        assert resolve_owner({}, "Nothing Mapped") == "Unowned"

    def test_warn_false_still_resolves_correctly(self):
        owners = {"search flow": "search-module@example.com"}
        assert resolve_owner(owners, "search flow", warn=False) == "search-module@example.com"
        assert resolve_owner({}, "Nothing Mapped", warn=False) == "Unowned"


def test_warn_unmapped_scenarios_does_not_raise_on_mixed_mapping():
    owners = {"search flow": "search-module@example.com"}
    warn_unmapped_scenarios(owners, ["Search Flow", "Unmapped Scenario"])  # must not raise
