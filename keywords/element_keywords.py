"""Element interaction keywords: Click, Type, SelectDropdown, Hover, Check/Uncheck,
and the SaveAs-capable read keywords (SaveText/SaveAttribute/SaveValue)."""
from core.keyword_engine import keyword, StepContext
from core.locator_resolver import resolve_locator
from core.exceptions import InvalidTestDataError
from core.logger import get_logger

logger = get_logger("keywords.element")


@keyword("Click")
def click(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    times = int(ctx.resolved_test_data) if ctx.resolved_test_data.isdigit() else 1
    for _ in range(times):
        locator.click(timeout=ctx.config.default_timeout_ms)


@keyword("ClickByJavaScript")
def click_by_javascript(ctx: StepContext) -> None:
    """Clicks via the DOM even if the element isn't visually rendered -
    useful when an element is present but obscured or animating in."""
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.evaluate("el => el.click()")


@keyword("Type")
def type_text(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.fill(ctx.resolved_test_data)


@keyword("TypeSlowly")
def type_slowly(ctx: StepContext) -> None:
    """Character-by-character typing - use when the page has a keystroke
    listener that .fill() would bypass (autocomplete widgets, etc.)."""
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.press_sequentially(ctx.resolved_test_data, delay=50)


@keyword("Clear")
def clear(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.fill("")


@keyword("Hover")
def hover(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.hover(timeout=ctx.config.default_timeout_ms)


@keyword("SelectDropdown")
def select_dropdown(ctx: StepContext) -> None:
    """Test Data is the visible option label to select."""
    if not ctx.resolved_test_data:
        raise InvalidTestDataError("SelectDropdown requires the option label in Test Data")
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.select_option(label=ctx.resolved_test_data)


@keyword("Check")
def check(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.check(timeout=ctx.config.default_timeout_ms)


@keyword("Uncheck")
def uncheck(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.uncheck(timeout=ctx.config.default_timeout_ms)


@keyword("ScrollIntoView")
def scroll_into_view(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.scroll_into_view_if_needed(timeout=ctx.config.default_timeout_ms)


@keyword("SaveText")
def save_text(ctx: StepContext) -> None:
    """Reads the element's inner text and captures it under SaveAs, e.g.
    an order confirmation number rendered on a success page. SaveAs is
    mandatory here - excel_reader already rejects this keyword without one
    at sheet-load time, but the check is repeated so a direct/unit-test
    caller of this function gets the same failure."""
    if not ctx.step.save_as:
        raise InvalidTestDataError("SaveText requires a SaveAs column value")
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    ctx.case_properties.capture(ctx.step.save_as, locator.inner_text().strip())


@keyword("SaveAttribute")
def save_attribute(ctx: StepContext) -> None:
    """Test Data = the attribute name to read (e.g. 'href', 'data-order-id').
    Captures the attribute's value under SaveAs."""
    if not ctx.step.save_as:
        raise InvalidTestDataError("SaveAttribute requires a SaveAs column value")
    if not ctx.resolved_test_data:
        raise InvalidTestDataError("SaveAttribute requires the attribute name in Test Data")
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    value = locator.get_attribute(ctx.resolved_test_data)
    if value is None:
        raise InvalidTestDataError(
            f"SaveAttribute: attribute '{ctx.resolved_test_data}' not present on the element "
            f"(Locator='{ctx.step.locator_value}')"
        )
    ctx.case_properties.capture(ctx.step.save_as, value)


@keyword("SaveValue")
def save_value(ctx: StepContext) -> None:
    """Reads an input/textarea/select's current value (what .input_value()
    returns - NOT visible text) and captures it under SaveAs. Use this for
    a value the page generated INTO a field (e.g. an auto-filled reference
    number), as opposed to SaveText for text rendered as content."""
    if not ctx.step.save_as:
        raise InvalidTestDataError("SaveValue requires a SaveAs column value")
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    ctx.case_properties.capture(ctx.step.save_as, locator.input_value())
