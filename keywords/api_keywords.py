"""
API keywords: ApiGet/ApiPost/ApiPut/ApiPatch/ApiDelete issue the call and
store the response on ctx.api_context; VerifyStatusCode/SaveJsonPath/
VerifyResponseContains all act on that same last response, so a case reads
naturally as one call followed by one or more checks/captures on it - no
keyword re-issues a request. ApiSetHeader configures headers (e.g. an auth
token) that every following Api* call in the case sends automatically. See
core/api_client.py for why this is built on Playwright's own
APIRequestContext instead of requests/httpx.
"""
import json as json_module

from core.keyword_engine import keyword, StepContext
from core.api_client import extract_json_path
from core.schema_validator import load_schema, validate_against_schema
from core.exceptions import InvalidTestDataError, AssertionFailedError
from core.logger import get_logger

logger = get_logger("keywords.api")

_METHODS = {"apiget": "get", "apipost": "post", "apiput": "put", "apipatch": "patch", "apidelete": "delete"}


def _redact(value: str) -> str:
    """Shows enough of a header value to confirm it's present and roughly
    what it is, without putting the full secret in a log file someone
    might screenshot or paste into a bug report. Applies to every header
    logged, not just ones named 'Authorization'/'Cookie' - a custom auth
    scheme's header name won't always match those two."""
    value = str(value)
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def _format_headers(headers) -> str:
    if not headers:
        return "none"
    return ", ".join(f"{k}={_redact(v)}" for k, v in headers.items())


def _do_request(ctx: StepContext, method: str) -> None:
    # resolve_embedded (not the whole-field-only resolve() already applied
    # to ctx.resolved_locator_value) so a captured value can sit inside a
    # larger URL, e.g. '.../booking/$bookingId' - see
    # core/properties_loader.py's resolve_embedded() docstring for why
    # this is opt-in per keyword rather than a global change.
    url = ctx.case_properties.resolve_embedded(ctx.resolved_locator_value)
    if not url:
        raise InvalidTestDataError(f"{ctx.step.keyword} requires the request URL in LocatorValue")

    kwargs = {}
    body_text = ctx.case_properties.resolve_embedded(ctx.resolved_test_data).strip()
    if body_text:
        try:
            kwargs["data"] = json_module.loads(body_text)
        except json_module.JSONDecodeError as e:
            raise InvalidTestDataError(f"{ctx.step.keyword}: Test Data isn't valid JSON ({e}) - got: {body_text}")

    if ctx.api_context.default_headers:
        kwargs["headers"] = ctx.api_context.default_headers

    response = getattr(ctx.page.context.request, method)(url, **kwargs)
    ctx.api_context.last_response = response
    ctx.api_context.last_body_text = response.text()
    try:
        ctx.api_context.last_body_json = response.json()
    except Exception:
        ctx.api_context.last_body_json = None

    logger.info(f"{ctx.step.keyword} {url} -> {response.status} "
                f"(headers sent: {_format_headers(kwargs.get('headers'))})")

    if ctx.step.save_as:
        # Convenience whole-body capture right on the request step, for
        # when you don't need one specific field - SaveJsonPath below is
        # for pulling a single value out instead.
        ctx.case_properties.capture(ctx.step.save_as, ctx.api_context.last_body_text)


@keyword("ApiGet")
def api_get(ctx: StepContext) -> None:
    _do_request(ctx, _METHODS["apiget"])


@keyword("ApiPost")
def api_post(ctx: StepContext) -> None:
    _do_request(ctx, _METHODS["apipost"])


@keyword("ApiPut")
def api_put(ctx: StepContext) -> None:
    _do_request(ctx, _METHODS["apiput"])


@keyword("ApiPatch")
def api_patch(ctx: StepContext) -> None:
    _do_request(ctx, _METHODS["apipatch"])


@keyword("ApiDelete")
def api_delete(ctx: StepContext) -> None:
    _do_request(ctx, _METHODS["apidelete"])


@keyword("ApiSetHeader")
def api_set_header(ctx: StepContext) -> None:
    """Test Data = a JSON object of headers, e.g.
    '{"Cookie": "token=$authToken"}' - resolved with resolve_embedded(),
    so a value captured earlier this case (via SaveJsonPath or any other
    SaveAs-capable keyword) can sit inside the header value rather than
    needing to BE the whole field. Merges into ctx.api_context.
    default_headers, which every following Api* call in this case sends
    automatically - matches how a real client obtains a token once and
    reuses it, rather than re-attaching it per call. No LocatorValue - this
    doesn't hit the network itself."""
    body_text = ctx.case_properties.resolve_embedded(ctx.resolved_test_data).strip()
    if not body_text:
        raise InvalidTestDataError("ApiSetHeader requires a JSON object of headers in Test Data")
    try:
        headers = json_module.loads(body_text)
    except json_module.JSONDecodeError as e:
        raise InvalidTestDataError(f"ApiSetHeader: Test Data isn't valid JSON ({e}) - got: {body_text}")
    if not isinstance(headers, dict):
        raise InvalidTestDataError(f"ApiSetHeader: Test Data must be a JSON OBJECT of headers, got: {body_text}")
    ctx.api_context.default_headers.update({str(k): str(v) for k, v in headers.items()})
    logger.info(f"ApiSetHeader: now sending {_format_headers(ctx.api_context.default_headers)} on every API call")


def _require_prior_call(ctx: StepContext, keyword_name: str) -> None:
    if ctx.api_context.last_response is None:
        raise InvalidTestDataError(
            f"{keyword_name}: no API call has been made yet this case - "
            f"add an ApiGet/ApiPost/ApiPut/ApiPatch/ApiDelete step before this one"
        )


@keyword("VerifyStatusCode")
def verify_status_code(ctx: StepContext) -> None:
    _require_prior_call(ctx, "VerifyStatusCode")
    expected = ctx.resolved_test_data.strip()
    if not expected.lstrip("-").isdigit():
        raise InvalidTestDataError(f"VerifyStatusCode: Test Data must be a status code, got '{expected}'")
    actual = ctx.api_context.last_response.status
    if actual != int(expected):
        raise AssertionFailedError(
            f"Expected status {expected}, got {actual} (body: {ctx.api_context.last_body_text[:300]})"
        )


@keyword("VerifyResponseContains")
def verify_response_contains(ctx: StepContext) -> None:
    """Substring check against the raw response text - works whether or
    not the body is JSON, for a quick sanity check without writing a
    SaveJsonPath expression."""
    _require_prior_call(ctx, "VerifyResponseContains")
    expected = ctx.resolved_test_data
    if expected not in ctx.api_context.last_body_text:
        raise AssertionFailedError(
            f"Expected response to contain '{expected}' - actual body: {ctx.api_context.last_body_text[:300]}"
        )


@keyword("SaveJsonPath")
def save_json_path(ctx: StepContext) -> None:
    """Test Data = a dot/bracket path like 'data.items[0].id' into the
    last response's JSON body. SaveAs = the variable name to capture it
    under - resolved by the same $var mechanism every other SaveAs-capable
    keyword uses (see core/properties_loader.py), so a later UI step's
    LocatorValue or Test Data can reference the value directly. This is
    the 'API generates it, UI verifies it' half of the hybrid pattern."""
    if not ctx.step.save_as:
        raise InvalidTestDataError("SaveJsonPath requires a SaveAs column value")
    _require_prior_call(ctx, "SaveJsonPath")
    if ctx.api_context.last_body_json is None:
        raise InvalidTestDataError(
            f"SaveJsonPath: last API response wasn't valid JSON - body: {ctx.api_context.last_body_text[:300]}"
        )
    value = extract_json_path(ctx.api_context.last_body_json, ctx.resolved_test_data.strip())
    ctx.case_properties.capture(ctx.step.save_as, str(value))


@keyword("VerifyJsonSchema")
def verify_json_schema(ctx: StepContext) -> None:
    """'Schema testing' / lightweight 'contract testing' - see
    core/schema_validator.py for the distinction from Pact-style
    consumer/provider contracts. Test Data is either an inline JSON
    Schema, or 'schema:<filename>.json' to load a reusable contract file
    from config.schema_dir. Validates the last API response's JSON body -
    same 'no prior call' guard as VerifyStatusCode/SaveJsonPath."""
    _require_prior_call(ctx, "VerifyJsonSchema")
    if ctx.api_context.last_body_json is None:
        raise InvalidTestDataError(
            f"VerifyJsonSchema: last API response wasn't valid JSON - body: {ctx.api_context.last_body_text[:300]}"
        )
    schema = load_schema(ctx.resolved_test_data, ctx.config.schema_dir)
    validate_against_schema(ctx.api_context.last_body_json, schema)
