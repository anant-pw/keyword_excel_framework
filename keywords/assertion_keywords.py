"""Assertion keywords - these raise AssertionFailedError (not a generic
Exception) so the reporter can tell 'test genuinely failed' apart from
'framework/environment problem' in the summary."""
from core.keyword_engine import keyword, StepContext
from core.locator_resolver import resolve_locator
from core.exceptions import AssertionFailedError
from core.logger import get_logger

logger = get_logger("keywords.assertion")


@keyword("ElementDisplayed")
def element_displayed(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    if not locator.is_visible():
        raise AssertionFailedError(
            f"Expected element to be displayed (Locator='{ctx.step.locator_value}') but it was not visible."
        )


@keyword("ElementNotDisplayed")
def element_not_displayed(ctx: StepContext) -> None:
    try:
        resolved = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value, timeout_ms=2000)
        if resolved.is_visible():
            raise AssertionFailedError(
                f"Expected element NOT to be displayed (Locator='{ctx.step.locator_value}') but it was visible."
            )
    except AssertionFailedError:
        raise
    except Exception:
        # Locator not resolving within the short timeout is the expected/passing case here.
        return


@keyword("ElementEnabled")
def element_enabled(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    if not locator.is_enabled():
        raise AssertionFailedError(f"Expected element to be enabled (Locator='{ctx.step.locator_value}').")


@keyword("VerifyText")
def verify_text(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    actual = locator.inner_text().strip()
    expected = ctx.resolved_test_data.strip()
    if actual != expected:
        raise AssertionFailedError(f"VerifyText mismatch: expected '{expected}', got '{actual}'.")


@keyword("VerifyTextContains")
def verify_text_contains(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    actual = locator.inner_text().strip()
    expected = ctx.resolved_test_data.strip()
    if expected not in actual:
        raise AssertionFailedError(f"VerifyTextContains failed: '{expected}' not found in '{actual}'.")


@keyword("VerifyURL")
def verify_url(ctx: StepContext) -> None:
    expected = ctx.resolved_test_data.strip()
    actual = ctx.page.url
    if expected not in actual:
        raise AssertionFailedError(f"VerifyURL failed: expected URL to contain '{expected}', actual URL '{actual}'.")


@keyword("VerifyTitle")
def verify_title(ctx: StepContext) -> None:
    expected = ctx.resolved_test_data.strip()
    actual = ctx.page.title()
    if expected != actual:
        raise AssertionFailedError(f"VerifyTitle failed: expected '{expected}', actual '{actual}'.")
