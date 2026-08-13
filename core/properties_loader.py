"""
Parses .properties files (key=value, '#' comments, blank lines ignored -
same format as the zip.properties pattern this was modeled on) and exposes
a per-test-case property store that the LoadProperties keyword populates
at runtime.

Two separate substitution mechanisms, deliberately kept distinct:

  $name    - resolved from EITHER properties loaded this test case via a
             LoadProperties step (static, file-backed) OR a value captured
             at runtime via a step's SaveAs column (dynamic, e.g. an order
             ID read off the page). Both are read through the exact same
             $name syntax in LocatorValue/TestData - a later step doesn't
             need to know or care which source a value came from. See
             CasePropertyStore.capture() below for the write side of the
             dynamic half.

  {{VAR}}  - resolved from OS environment first, config.yaml env_variables
             second. Lives INSIDE a .properties file value, not in the
             Excel sheet directly - e.g. demoPassword={{password}}. Real
             secrets should be supplied as OS env vars in CI; the
             config.yaml fallback exists only so this runs out of the box
             for demo purposes.

Why per-test-case scoping instead of one global properties dict: different
sheets/pages define their own locators, and a global namespace risks two
pages both defining "submitButton" and silently colliding. Scoping to the
currently executing test case - loaded explicitly via a LoadProperties
step - keeps each case's namespace deliberate and traceable to one line in
the sheet. The same reasoning extends to captured values: a fresh
CasePropertyStore per case (see tests/runner.py::run_test_case) means a
captured $orderId from case A can never leak into case B, parallel workers
included.

resolve() only substitutes when a field IS exactly "$name" - a locator or
literal containing "$" elsewhere passes through untouched. See
resolve_embedded() below for the opt-in alternative (API URLs/bodies/
headers) that substitutes $name wherever it appears inside a larger
string.
"""
import os
import re
from pathlib import Path

from core.exceptions import PropertiesNotFoundError, UnresolvedVariableError, VariableCaptureError
from core.logger import get_logger

logger = get_logger("properties_loader")

_ENV_TOKEN = re.compile(r"\{\{(\w+)\}\}")
_VAR_REFERENCE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")
_EMBEDDED_VAR_REFERENCE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _resolve_env_tokens(value: str, config_env_variables: dict, source_file: str) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in os.environ:
            return os.environ[key]
        if key in config_env_variables:
            return str(config_env_variables[key])
        raise UnresolvedVariableError(
            f"{source_file}: unresolved {{{{{key}}}}} - not found in OS environment "
            f"or config.yaml env_variables"
        )
    return _ENV_TOKEN.sub(repl, value)


def parse_properties_file(path: Path, config_env_variables: dict) -> dict:
    if not path.exists():
        raise PropertiesNotFoundError(f"Properties file not found: {path}")

    result = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not key:
            continue
        result[key] = _resolve_env_tokens(value, config_env_variables, path.name) if value else value

    logger.info(f"Parsed {len(result)} key(s) from {path.name}")
    return result


class CasePropertyStore:
    """Mutable per-test-case store. The runner creates a fresh instance for
    each test case, so properties loaded while running case A never leak
    into case B.

    Holds two layers under one $name lookup:
      _values    - static, populated only by load() (a LoadProperties step)
      _captured  - dynamic, populated only by capture() (a step whose
                   SaveAs column is set - see keywords/element_keywords.py
                   SaveText/SaveAttribute/SaveValue and
                   keywords/utility_keywords.py GenerateValue)
    resolve() checks _captured first, then _values, but a name can only
    ever exist in one of the two: capture() refuses to shadow a name
    already loaded from a properties file, and load() refuses to load a
    file whose key would shadow an already-captured name. That keeps
    "where did $x come from" a single unambiguous answer per case, even
    though callers of resolve() never have to ask."""

    def __init__(self, properties_dir: str, config_env_variables: dict):
        self._properties_dir = Path(properties_dir)
        self._config_env_variables = config_env_variables
        self._values: dict = {}
        self._captured: dict = {}
        self._loaded_files: list = []

    def load(self, basename: str) -> None:
        path = self._properties_dir / f"{basename}.properties"
        loaded = parse_properties_file(path, self._config_env_variables)
        collisions = set(loaded) & set(self._captured)
        if collisions:
            raise VariableCaptureError(
                f"{path.name} defines {sorted(collisions)} but that name was already "
                f"captured at runtime this case (SaveAs) - rename one of them."
            )
        self._values.update(loaded)
        self._loaded_files.append(basename)

    def capture(self, name: str, value: str) -> None:
        """Stores value under name for later $name resolution. Called by
        SaveAs-capable keywords after they've produced a result (extracted
        text, an attribute, a generated ID). Fails fast - before the value
        is stored - on an invalid identifier or a name collision with a
        properties-file key, rather than silently letting the newer write
        win; a case has exactly one LoadProperties-vs-SaveAs source of
        truth per name."""
        if not _VALID_NAME.match(name or ""):
            raise VariableCaptureError(
                f"Invalid SaveAs name '{name}' - must match {_VALID_NAME.pattern}"
            )
        if name in self._values:
            raise VariableCaptureError(
                f"SaveAs name '{name}' collides with a key already loaded from "
                f"{self._loaded_files} - rename the SaveAs column or the properties key."
            )
        if name in self._captured:
            logger.info(f"'${name}' captured again this case - overwriting previous value.")
        self._captured[name] = value
        logger.info(f"Captured '${name}' = {value!r}")

    def resolve(self, value: str) -> str:
        """If value is exactly '$name', resolve it - checking runtime
        captures first, then loaded properties. Anything else (a literal
        CSS selector, a plain string) passes through unchanged - only a
        bare $name is treated as a reference."""
        if not value:
            return value
        match = _VAR_REFERENCE.match(value.strip())
        if not match:
            return value
        var_name = match.group(1)
        return self._lookup(var_name)

    def resolve_embedded(self, text: str) -> str:
        """Like resolve(), but substitutes every $name occurrence WITHIN a
        larger string - e.g. a REST path 'https://api/booking/$bookingId'
        or a header value '{"Cookie": "token=$authToken"}' - not only when
        the whole field is exactly $name. Used by keywords/api_keywords.py
        for API URLs, JSON bodies, and headers, where a captured value
        commonly needs to sit inside a bigger literal.

        Deliberately a SEPARATE method from resolve(), not a replacement
        for it: resolve() being whole-field-only is intentional for
        LocatorValue/Test Data on UI keywords - a literal CSS selector
        like div[data-id="$foo"] should never have $foo silently swapped
        out from under a locator author who didn't intend a variable
        there. Embedded substitution is opt-in per call site (API
        keywords choose it explicitly), not a global change to how every
        field on every keyword is read."""
        if not text or "$" not in text:
            return text
        def _replace(match: re.Match) -> str:
            return self._lookup(match.group(1), embedded_in=text)
        return _EMBEDDED_VAR_REFERENCE.sub(_replace, text)

    def _lookup(self, var_name: str, embedded_in: str = "") -> str:
        if var_name in self._captured:
            return self._captured[var_name]
        if var_name in self._values:
            return self._values[var_name]
        where = f" (inside '{embedded_in}')" if embedded_in else ""
        raise UnresolvedVariableError(
            f"'${var_name}' referenced{where} but not found in loaded properties "
            f"{self._loaded_files or '(none loaded yet)'} or in values captured so far this case "
            f"(missing a LoadProperties or an earlier SaveAs step?)"
        )
