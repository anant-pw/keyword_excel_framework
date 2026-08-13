"""
Scans common/*.xlsx at startup and registers each Test Scenario found as a
callable composite keyword - usable directly in Keyword/Action with no
special addressing syntax (no filename, no pipe/colon delimiters). A
composite keyword is a named, reusable sequence of steps (e.g. a shared
login flow) executed against the SAME CasePropertyStore as the calling
case, so a LoadProperties step earlier in the case is visible inside the
composite automatically - no parameter-passing mechanism needed.

The Suite column in a common/ file is not used for filtering - a composite
runs whenever it's called, regardless of which suite the calling case
belongs to. Loading a common file therefore always passes suite_filter=None
to read_test_suite.

Startup fails loudly (not silently) on:
  - two common files defining the same Test Scenario name
  - a common scenario name colliding with a built-in keyword name
so a naming collision is caught once, at framework startup, rather than
producing a confusing "which one actually ran" surprise mid test-run.
"""
from pathlib import Path

from core.excel_reader import read_test_suite
from core.exceptions import FrameworkError
from core.logger import get_logger

logger = get_logger("common_keywords")


class CommonKeywordCollisionError(FrameworkError):
    pass


class CommonKeywordRegistry:
    """Instance-based (not module-global) so tests can build an isolated
    registry instead of mutating shared state between test runs."""

    def __init__(self):
        self._entries: dict = {}  # lowercased scenario name -> (TestCase, source_filename)

    def load(self, common_dir: str, builtin_keyword_names) -> None:
        common_path = Path(common_dir)
        if not common_path.exists():
            logger.info(f"No common/ directory at {common_path} - skipping composite keyword registration")
            return

        for file_path in sorted(common_path.glob("*.xlsx")):
            cases = read_test_suite(str(file_path))  # no suite filter - load every scenario as-is
            for case in cases:
                key = case.test_scenario.strip().lower()
                if key in self._entries:
                    _, existing_file = self._entries[key]
                    raise CommonKeywordCollisionError(
                        f"Common scenario '{case.test_scenario}' is defined in both "
                        f"{existing_file} and {file_path.name} - scenario names under "
                        f"common/ must be unique across all files."
                    )
                if key in builtin_keyword_names:
                    raise CommonKeywordCollisionError(
                        f"Common scenario '{case.test_scenario}' (in {file_path.name}) "
                        f"collides with a built-in keyword name - rename one of them."
                    )
                self._entries[key] = (case, file_path.name)
                logger.info(f"Registered composite keyword '{case.test_scenario}' from {file_path.name} "
                            f"({len(case.steps)} step(s))")

    def get(self, keyword_name: str):
        entry = self._entries.get(keyword_name.strip().lower())
        return entry[0] if entry else None

    def __contains__(self, keyword_name: str) -> bool:
        return keyword_name.strip().lower() in self._entries
