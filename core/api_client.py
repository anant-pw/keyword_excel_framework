"""
Small, framework-owned API testing layer. Deliberately NOT built on
requests/httpx - keywords/api_keywords.py issues calls through
ctx.page.context.request, Playwright's own APIRequestContext, because it's
scoped to the SAME browser context as the UI steps in that case. That
means:
  - a session loaded via UseSession (see core/session_manager.py) is
    already authenticated for API calls in the same case, no extra login
  - an API call that sets a session cookie (e.g. a login endpoint) is
    immediately visible to the next Navigate/Click step, same context
  - "set up state via API, verify it via UI" - the pattern most real
    hybrid frameworks are actually built around - falls out for free,
    rather than needing a second client with its own cookie jar kept in
    sync by hand
No separate HTTP dependency, no cookie-syncing code to maintain.

extract_json_path() lives here rather than in keywords/api_keywords.py
because it's pure - no Playwright dependency - so it's unit-testable
without a browser (see tests/unit/test_api_client.py), same reasoning as
core/session_manager.py and core/parallel.py.
"""
from dataclasses import dataclass, field
from typing import Any

from core.exceptions import InvalidTestDataError


@dataclass
class ApiCallContext:
    """Per-case, mutable - created once per test case in
    tests/runner.py::run_test_case alongside CasePropertyStore, and
    threaded through StepContext the same way (including into composite
    keywords, which share both). Holds the most recent API response so a
    following VerifyStatusCode/SaveJsonPath/VerifyResponseContains step
    can act on it without re-issuing the call. A fresh instance per case
    means parallel workers and separate cases never share a response."""
    last_response: object = None      # playwright.sync_api.APIResponse, or None before any call
    last_body_json: Any = None        # parsed JSON body, or None if the body wasn't valid JSON
    last_body_text: str = ""          # raw response text - always set, JSON or not
    default_headers: dict = field(default_factory=dict)
    # Set/merged by ApiSetHeader, applied to every Api* call for the rest of
    # this case (not just the next one) - matches how a real auth token, once
    # obtained, applies to every following call rather than one at a time.
    # No dedicated "clear" keyword yet; headers live for the case's lifetime.


def extract_json_path(data: Any, path: str) -> Any:
    """path is dot-separated keys with an optional [N] index per segment,
    e.g. 'data.items[0].id'. Raises InvalidTestDataError with a message
    naming exactly which segment failed, rather than letting a raw
    KeyError/IndexError/TypeError surface - this runs mid-test and the
    message is what ends up in the report."""
    if not path:
        raise InvalidTestDataError("SaveJsonPath: Test Data (the JSON path) is empty")

    current = data
    for segment in path.split("."):
        if not segment:
            continue
        key, _, index_part = segment.partition("[")
        if key:
            if not isinstance(current, dict):
                raise InvalidTestDataError(
                    f"SaveJsonPath: '{path}' expected an object at '{key}' but found {type(current).__name__}"
                )
            if key not in current:
                raise InvalidTestDataError(f"SaveJsonPath: key '{key}' not found in response (path '{path}')")
            current = current[key]
        if index_part:
            index_str = index_part.rstrip("]")
            if not index_str.isdigit():
                raise InvalidTestDataError(f"SaveJsonPath: bad index '[{index_part}' in path '{path}'")
            index = int(index_str)
            if not isinstance(current, list):
                raise InvalidTestDataError(
                    f"SaveJsonPath: '{path}' expected a list at index [{index}] but found {type(current).__name__}"
                )
            if index >= len(current):
                raise InvalidTestDataError(
                    f"SaveJsonPath: index [{index}] out of range (length {len(current)}) in path '{path}'"
                )
            current = current[index]
    return current
