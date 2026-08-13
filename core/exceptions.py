"""
Custom exception hierarchy for the keyword-driven framework.

Distinct exception types (instead of raising bare Exception everywhere) let
the runner and reporter classify failures correctly - a locator that can't
be resolved is a different kind of problem than a failed assertion, which is
different again from a malformed row in the Excel sheet or a missing
properties file.
"""


class FrameworkError(Exception):
    """Base class for all framework-raised exceptions."""
    pass


class LocatorNotFoundError(FrameworkError):
    """Raised when a locator cannot be resolved to a visible/attached
    element using any of the configured strategies."""
    pass


class KeywordNotImplementedError(FrameworkError):
    """Raised when a keyword referenced in the Excel sheet has no
    registered implementation."""
    pass


class InvalidTestDataError(FrameworkError):
    """Raised when a row in the test sheet is missing mandatory data for
    the keyword it specifies (e.g. Click with no LocatorValue)."""
    pass


class AssertionFailedError(FrameworkError):
    """Raised by assertion-style keywords (VerifyText, ElementDisplayed,
    etc.) when the expected condition is not met. Kept distinct from a
    Playwright/locator error so reports can label it as a genuine test
    failure rather than a framework/environment issue."""
    pass


class UnsupportedSuiteTypeError(FrameworkError):
    """Raised when a test sheet references a Suite the runner doesn't
    recognize. Only Smoke / Sanity / Regression are valid."""
    pass


class PropertiesNotFoundError(FrameworkError):
    """Raised when a LoadProperties step references a .properties file
    that doesn't exist under properties/."""
    pass


class UnresolvedVariableError(FrameworkError):
    """Raised when a $variable or {{VAR}} token can't be resolved - either
    the properties file wasn't loaded yet, or the key genuinely isn't
    defined anywhere (properties file, OS environment, config.yaml)."""
    pass


class SessionStateError(FrameworkError):
    """Raised when a UseSession step references a session name with no
    matching saved storage_state file under session_dir, or when a
    SaveSession step can't write one. Checked as a preflight, before any
    browser launches - see core/session_manager.py."""
    pass


class VariableCaptureError(FrameworkError):
    """Raised when a SaveAs capture is invalid at write time - either the
    name isn't a valid identifier, or it collides with a key already
    loaded via LoadProperties. Kept distinct from UnresolvedVariableError
    (a read-time failure) because this is a write-time failure: it means
    the sheet author asked to save a value under a name that would create
    ambiguity for every later $reference to that name."""
    pass
