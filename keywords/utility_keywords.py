"""Utility keywords: property loading, explicit waits, manual screenshot
capture, and runtime value generation."""
import time
import uuid
from datetime import datetime
from pathlib import Path

from core.keyword_engine import keyword, StepContext
from core.locator_resolver import resolve_locator
from core.exceptions import InvalidTestDataError, SessionStateError
from core.session_manager import DEFAULT_SESSION_NAME
from core.logger import get_logger

logger = get_logger("keywords.utility")


@keyword("LoadProperties")
def load_properties(ctx: StepContext) -> None:
    """Test Data = base name of a file under properties/ (no extension),
    e.g. Test Data='login' loads properties/login.properties. Every
    subsequent step in this test case can then reference $key from that
    file in LocatorValue or Test Data. Must run before any step in the
    case uses a $reference."""
    basename = ctx.resolved_test_data
    if not basename:
        raise InvalidTestDataError("LoadProperties requires a properties file base name (no extension) in Test Data")
    ctx.case_properties.load(basename)


@keyword("Wait")
def wait(ctx: StepContext) -> None:
    """Test Data = seconds to wait. Use sparingly - prefer relying on
    Playwright's built-in auto-waiting inside other keywords."""
    try:
        seconds = float(ctx.resolved_test_data)
    except ValueError:
        raise InvalidTestDataError(f"Wait requires a numeric value in Test Data, got '{ctx.resolved_test_data}'")
    time.sleep(seconds)


@keyword("WaitForElement")
def wait_for_element(ctx: StepContext) -> None:
    resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                     timeout_ms=ctx.config.default_timeout_ms)


@keyword("GenerateValue")
def generate_value(ctx: StepContext) -> None:
    """No LocatorValue needed - generates a value locally (nothing to read
    off the page) and captures it under SaveAs. Test Data selects the
    strategy:
        (blank) or "uuid"        -> a full uuid4 string
        "uuid:N"                 -> first N hex chars of a uuid4 (e.g.
                                     "uuid:8" for a short unique suffix -
                                     handy for a throwaway username/email)
        "timestamp"               -> current epoch milliseconds
        "timestamp:<strftime fmt>" -> current time in that format, e.g.
                                     "timestamp:%Y%m%d%H%M%S"
    Typical use: generate a unique username/email before a Type step so a
    registration form doesn't collide across repeated runs, then SaveAs
    that same name is available to a later VerifyText/Type step."""
    if not ctx.step.save_as:
        raise InvalidTestDataError("GenerateValue requires a SaveAs column value")

    strategy = ctx.resolved_test_data.strip() or "uuid"
    kind, _, arg = strategy.partition(":")
    kind = kind.strip().lower()

    if kind == "uuid":
        value = uuid.uuid4().hex
        if arg:
            if not arg.isdigit() or not (1 <= int(arg) <= 32):
                raise InvalidTestDataError(f"GenerateValue 'uuid:N' expects N between 1 and 32, got '{arg}'")
            value = value[: int(arg)]
    elif kind == "timestamp":
        now = datetime.now()
        value = now.strftime(arg) if arg else str(int(now.timestamp() * 1000))
    else:
        raise InvalidTestDataError(
            f"GenerateValue: unknown strategy '{kind}' in Test Data - supported: uuid, uuid:N, "
            f"timestamp, timestamp:<strftime fmt>"
        )

    ctx.case_properties.capture(ctx.step.save_as, value)


@keyword("SaveSession")
def save_session(ctx: StepContext) -> None:
    """Test Data (optional, default 'default') = session name. Writes the
    current context's storage_state (cookies + localStorage) to
    <session_dir>/<name>.json, for a later case's UseSession step to load.
    Test Data goes through the normal $var resolution (unlike UseSession -
    see core/session_manager.py's module docstring for why), so a name can
    come from a properties file if you want one.

    Typically the last step of a dedicated login case run fail-fast (e.g.
    under Smoke) - if login fails, an earlier step raises first and this
    line never runs, so a broken/unauthenticated state is never saved."""
    session_name = ctx.resolved_test_data.strip() or DEFAULT_SESSION_NAME
    out_dir = Path(ctx.config.session_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{session_name}.json"
    try:
        ctx.page.context.storage_state(path=str(path))
    except Exception as e:
        raise SessionStateError(f"SaveSession: could not write session '{session_name}' to {path}: {e}") from e
    logger.info(f"Session '{session_name}' saved to {path}")


@keyword("UseSession")
def use_session(ctx: StepContext) -> None:
    """Never actually dispatched in a normal run - the runner reads a
    UseSession step BEFORE the browser context exists (see
    core/session_manager.extract_session_directive) and strips it from the
    case's steps before execution begins, since storage_state can only be
    supplied at context-creation time. Registered here anyway, as a
    defensive fallback that fails loudly rather than silently: the only
    way to reach this function is a UseSession step INSIDE a composite
    (common/) keyword, where the calling case's context already exists and
    this directive can't do anything - excel_reader's position check
    catches a misplaced UseSession within a single sheet, but a composite
    is a separate sheet at load time, so this is the second line of
    defense for that specific gap."""
    raise InvalidTestDataError(
        "UseSession must be the first step of a top-level test case, not inside a composite "
        "(common/) keyword - it configures the browser context, which already exists by the "
        "time a composite runs."
    )


@keyword("Screenshot")
def screenshot(ctx: StepContext) -> None:
    """Test Data (optional) = filename suffix. Saved under reports/screenshots/."""
    out_dir = Path(ctx.config.report_dir) / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ctx.resolved_test_data or "manual"
    path = out_dir / f"row{ctx.step.row_id}_{suffix}.png"
    ctx.page.screenshot(path=str(path))
    logger.info(f"Screenshot saved: {path}")
