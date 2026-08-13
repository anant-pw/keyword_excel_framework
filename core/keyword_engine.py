"""
Keyword registry + dispatcher.

Every keyword function is registered via the @keyword("Name") decorator in
the keywords/ package. This engine looks the name up in a dict and calls
it - no reflection needed (that's a Java-ism; Python's first-class
functions make this simpler and give a clear error at import time if two
keywords collide on the same name).

Before dispatch, LocatorValue and Test Data both go through
case_properties.resolve() - if a value is a bare "$name" reference, it's
swapped for whatever LoadProperties loaded this case; anything else (a
literal CSS selector, a JSON "any" block, a plain string) passes through
unchanged. This is what keeps literal locators AND literal credentials out
of the sheet - both columns get the same treatment, not just LocatorValue.

Each keyword function has the signature:
    def my_keyword(ctx: StepContext) -> None
and raises AssertionFailedError / LocatorNotFoundError / etc. on failure.
Returning normally = pass.
"""
from dataclasses import dataclass
from playwright.sync_api import Page

from core.config_loader import RunConfig
from core.exceptions import KeywordNotImplementedError
from core.excel_reader import TestStep
from core.properties_loader import CasePropertyStore
from core.api_client import ApiCallContext
from core.logger import get_logger

logger = get_logger("keyword_engine")

_REGISTRY = {}


def keyword(name: str):
    """Decorator that registers a function as the implementation of a
    named keyword (case-insensitive lookup)."""
    def decorator(func):
        key = name.lower()
        if key in _REGISTRY:
            raise RuntimeError(f"Duplicate keyword registration for '{name}' "
                                f"({_REGISTRY[key].__module__} vs {func.__module__})")
        _REGISTRY[key] = func
        return func
    return decorator


@dataclass
class StepContext:
    """Everything a keyword implementation needs, bundled per-step."""
    page: Page
    step: TestStep
    config: RunConfig
    case_properties: CasePropertyStore   # mutated in place by LoadProperties / SaveAs captures
    api_context: ApiCallContext          # mutated in place by ApiGet/ApiPost/etc - see core/api_client.py
    resolved_locator_value: str           # after $var resolution
    resolved_test_data: str               # after $var resolution


def execute_step(page: Page, step: TestStep, config: RunConfig, case_properties: CasePropertyStore,
                  api_context: ApiCallContext) -> None:
    """Look up the keyword for this step and execute it. Raises on failure;
    callers (the runner) decide whether that stops the test case."""
    func = _REGISTRY.get(step.keyword.lower())
    if func is None:
        raise KeywordNotImplementedError(
            f"No implementation registered for keyword '{step.keyword}' "
            f"(Row {step.row_id}, Scenario='{step.test_scenario}'). "
            f"Registered keywords: {sorted(_REGISTRY.keys())}"
        )

    resolved_locator_value = case_properties.resolve(step.locator_value)
    resolved_test_data = case_properties.resolve(step.test_data)

    ctx = StepContext(
        page=page,
        step=step,
        config=config,
        case_properties=case_properties,
        api_context=api_context,
        resolved_locator_value=resolved_locator_value,
        resolved_test_data=resolved_test_data,
    )
    logger.info(f"[Row {step.row_id}] Scenario='{step.test_scenario}' Desc='{step.description}' -> {step.keyword} "
                f"(Locator='{step.locator_value}' -> '{resolved_locator_value}', "
                f"Data='{step.test_data}' -> '{resolved_test_data}')")
    func(ctx)


def registered_keywords() -> list:
    return sorted(_REGISTRY.keys())
