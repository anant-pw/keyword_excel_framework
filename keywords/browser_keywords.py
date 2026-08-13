"""Browser/navigation-level keywords: Navigate, Back, Forward, Refresh, alerts, windows."""
from core.keyword_engine import keyword, StepContext
from core.exceptions import InvalidTestDataError
from core.logger import get_logger

logger = get_logger("keywords.browser")


@keyword("Navigate")
def navigate(ctx: StepContext) -> None:
    url = ctx.resolved_test_data
    if not url:
        raise InvalidTestDataError("Navigate requires a URL in the Test Data column")
    ctx.page.goto(url, timeout=ctx.config.default_timeout_ms)


@keyword("Back")
def go_back(ctx: StepContext) -> None:
    ctx.page.go_back(timeout=ctx.config.default_timeout_ms)


@keyword("Forward")
def go_forward(ctx: StepContext) -> None:
    ctx.page.go_forward(timeout=ctx.config.default_timeout_ms)


@keyword("Refresh")
def refresh(ctx: StepContext) -> None:
    ctx.page.reload(timeout=ctx.config.default_timeout_ms)


@keyword("AcceptAlert")
def accept_alert(ctx: StepContext) -> None:
    ctx.page.once("dialog", lambda dialog: dialog.accept())


@keyword("DismissAlert")
def dismiss_alert(ctx: StepContext) -> None:
    ctx.page.once("dialog", lambda dialog: dialog.dismiss())


@keyword("SwitchToWindow")
def switch_to_window(ctx: StepContext) -> None:
    """Test Data: 0-based index into context.pages (0 = first/original tab)."""
    index_str = ctx.resolved_test_data or "0"
    index = int(index_str)
    pages = ctx.page.context.pages
    if index >= len(pages):
        raise InvalidTestDataError(f"SwitchToWindow: index {index} out of range, only {len(pages)} window(s) open")
    pages[index].bring_to_front()


@keyword("CloseWindow")
def close_window(ctx: StepContext) -> None:
    ctx.page.close()
