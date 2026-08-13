"""
JSON Schema validation ("schema testing") plus a lightweight file-based
form of "contract testing" - a schema saved under schemas/*.json IS the
contract: an agreed response shape the API promises to honor, checked on
every run instead of trusted implicitly after the first manual look.

Deliberately NOT a Pact-style consumer/provider setup - no broker
service, no publish/verify handshake between a consumer team and a
provider team. That's a materially different tool with its own
infrastructure (a Pact Broker), and bolting a fake version of it onto a
keyword-driven Excel framework would be the wrong shape for what this
actually is. What's here is the practice most teams without a broker
already use in production: a schema file under version control, checked
against real responses, catching a breaking API change the same day it
ships instead of whenever someone notices the UI looks wrong.

Kept separate from keywords/api_keywords.py because it's pure - no
Playwright dependency - so it's unit-testable without a browser, same
reasoning as core/api_client.py and core/session_manager.py.
"""
import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema.exceptions import SchemaError, ValidationError

from core.exceptions import InvalidTestDataError, AssertionFailedError

SCHEMA_FILE_PREFIX = "schema:"


def load_schema(test_data: str, schema_dir: str) -> dict:
    """test_data is either:
      - 'schema:<filename>.json' - loads the reusable contract file from
        schema_dir. Use this once the same shape gets checked from more
        than one step/sheet, so the contract lives in exactly one place.
      - an inline JSON Schema string typed directly into the sheet - fine
        for a one-off, sheet-local check that isn't worth a shared file.
    Raises InvalidTestDataError (not AssertionFailedError) for anything
    wrong with the schema itself - a missing/malformed contract file is a
    sheet-authoring bug, not a test finding."""
    text = (test_data or "").strip()
    if not text:
        raise InvalidTestDataError(
            "VerifyJsonSchema requires a schema in Test Data - either inline JSON Schema "
            "or 'schema:<filename>.json' to load one from the schema_dir"
        )
    if text.startswith(SCHEMA_FILE_PREFIX):
        filename = text[len(SCHEMA_FILE_PREFIX):].strip()
        if not filename:
            raise InvalidTestDataError("VerifyJsonSchema: 'schema:' prefix given with no filename after it")
        path = Path(schema_dir) / filename
        if not path.exists():
            raise InvalidTestDataError(f"VerifyJsonSchema: schema file not found: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise InvalidTestDataError(f"VerifyJsonSchema: {path} isn't valid JSON ({e})")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise InvalidTestDataError(
            f"VerifyJsonSchema: Test Data isn't valid JSON Schema and doesn't start with "
            f"'schema:' either ({e})"
        )


def validate_against_schema(data: Any, schema: dict) -> None:
    """Raises AssertionFailedError (the same exception type every other
    Verify* keyword raises, so it fails the step the normal way) with the
    exact path and reason on a mismatch - not jsonschema's raw exception,
    so the report shows something a person reads instead of a library's
    internal repr. A malformed SCHEMA itself (not the data) raises
    InvalidTestDataError instead - that's a contract-file bug, not
    something the API under test did wrong."""
    try:
        jsonschema.validate(instance=data, schema=schema)
    except ValidationError as e:
        path = " -> ".join(str(p) for p in e.absolute_path) or "(root)"
        raise AssertionFailedError(f"Schema validation failed at '{path}': {e.message}")
    except SchemaError as e:
        raise InvalidTestDataError(f"VerifyJsonSchema: the schema itself is invalid: {e.message}")
