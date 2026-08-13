"""
Resolves a (LocatorType, LocatorValue) pair from a test step into a live
Playwright Locator.

Supported LocatorType values:
    id, css, xpath, text, role, testid, placeholder, name
    "any"  -> LocatorValue is a JSON object mapping strategy -> value, tried
              in insertion order until one resolves to a visible/attached
              element. Useful when the same element needs different
              selectors across environments or A/B'd markup.

Example "any" LocatorValue:
    {"testid": "login-submit", "css": "button.submit-btn", "xpath": "//button[text()='Login']"}
"""
import json
from playwright.sync_api import Page, Locator, TimeoutError as PWTimeoutError

from core.exceptions import LocatorNotFoundError
from core.logger import get_logger

logger = get_logger("locator_resolver")

_SIMPLE_STRATEGIES = {
    "id": lambda page, value: page.locator(f"#{value}"),
    "css": lambda page, value: page.locator(value),
    "xpath": lambda page, value: page.locator(f"xpath={value}"),
    "text": lambda page, value: page.get_by_text(value, exact=False),
    "role": lambda page, value: page.get_by_role(
        value.split("::")[0], name=value.split("::", 1)[1] if "::" in value else None
    ),
    "testid": lambda page, value: page.get_by_test_id(value),
    "placeholder": lambda page, value: page.get_by_placeholder(value),
    "name": lambda page, value: page.locator(f"[name='{value}']"),
}


def _build_locator(page: Page, locator_type: str, locator_value: str) -> Locator:
    strategy = _SIMPLE_STRATEGIES.get(locator_type.lower())
    if strategy is None:
        raise LocatorNotFoundError(
            f"Unknown LocatorType '{locator_type}'. Supported: {list(_SIMPLE_STRATEGIES)} or 'any'."
        )
    return strategy(page, locator_value)


def resolve_locator(page: Page, locator_type: str, locator_value: str, timeout_ms: int = 15000) -> Locator:
    """Resolve LocatorType/LocatorValue into a Locator, waiting for it to
    attach. Raises LocatorNotFoundError if nothing resolves within timeout."""
    if locator_type.lower() == "any":
        try:
            strategies = json.loads(locator_value)
        except json.JSONDecodeError as e:
            raise LocatorNotFoundError(
                f"LocatorType 'any' requires LocatorValue to be a JSON object of "
                f"strategy->value. Got: {locator_value!r}"
            ) from e

        last_error = None
        for strat_name, strat_value in strategies.items():
            try:
                locator = _build_locator(page, strat_name, strat_value)
                locator.wait_for(state="attached", timeout=timeout_ms)
                logger.info(f"Resolved element using fallback strategy '{strat_name}' = '{strat_value}'")
                return locator
            except (PWTimeoutError, LocatorNotFoundError) as e:
                last_error = e
                logger.debug(f"Strategy '{strat_name}' did not resolve: {e}")
                continue
        raise LocatorNotFoundError(
            f"None of the strategies {list(strategies.keys())} resolved an element."
        ) from last_error

    locator = _build_locator(page, locator_type, locator_value)
    try:
        locator.wait_for(state="attached", timeout=timeout_ms)
    except PWTimeoutError as e:
        raise LocatorNotFoundError(
            f"Element not found: LocatorType='{locator_type}', LocatorValue='{locator_value}' "
            f"(waited {timeout_ms}ms)"
        ) from e
    return locator
