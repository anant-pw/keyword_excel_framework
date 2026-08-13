"""
Pure logic for the storage_state session-reuse feature - kept separate
from tests/runner.py's Playwright/multiprocessing wiring so it's testable
without a browser (see tests/unit/test_session_manager.py), same pattern
as core/parallel.py.

The real scenario this exists for: log in once, then run several
independent cases (Dashboard/Payment/Settings) reusing that one session
instead of logging in per case.

A test case opts into a saved session by making its FIRST step the
UseSession keyword (Test Data = session name, defaults to "default" if
blank). That step is a context-creation directive, not something a
browser can execute mid-case - Playwright's storage_state is a
new_context() argument, so the runner must read it BEFORE calling
driver.new_page(), then run only the REMAINING steps against that
pre-authenticated context. extract_session_directive() does that split.

This is NOT independent of parallel execution: both tests/runner.py's
sequential path (_run_sequential) and per-worker parallel path
(_run_worker_chunk) call extract_session_directive() before their own
driver.new_page() call, so a case using a saved session behaves
identically whether it lands on the sequential run or on worker 3 of 5 -
one shared helper, two call sites, deliberately kept from drifting apart.

Asymmetry worth knowing: UseSession's Test Data is read literally, NOT
through CasePropertyStore.resolve() - there's no CasePropertyStore yet at
extraction time (it's created per-case inside run_test_case(), after the
context already exists). So UseSession's session name can't reference a
$var from a properties file. SaveSession has no such restriction - it's a
normal step, executed through the usual execute_step()/case_properties
path, so its Test Data can be $var-resolved like any other step.
"""
from dataclasses import replace
from pathlib import Path

from core.exceptions import SessionStateError

USE_SESSION_KEYWORD = "usesession"
SAVE_SESSION_KEYWORD = "savesession"
DEFAULT_SESSION_NAME = "default"


def extract_session_directive(test_case):
    """If test_case's first step is UseSession, returns
    (session_name, directive_step, case_with_that_step_removed).
    Otherwise returns (None, None, test_case) unchanged.

    Only the first step is ever inspected - excel_reader.read_test_suite
    already rejects a UseSession step appearing anywhere else in a case at
    sheet-load time, so a case reaching this function either has it at
    index 0 or not at all."""
    if not test_case.steps or test_case.steps[0].keyword.strip().lower() != USE_SESSION_KEYWORD:
        return None, None, test_case
    directive = test_case.steps[0]
    session_name = directive.test_data.strip() or DEFAULT_SESSION_NAME
    return session_name, directive, replace(test_case, steps=test_case.steps[1:])


def session_state_path(session_dir: str, session_name: str) -> Path:
    return Path(session_dir) / f"{session_name}.json"


def preflight_check_sessions(test_cases: list, session_dir: str) -> None:
    """Called once before any browser launches (see tests/runner.py::main).
    Collects every UseSession reference across the whole run and raises
    ONE error listing every missing file, rather than letting a run get
    partway through - possibly after other workers already opened
    browsers - before failing on case 4's typo'd session name."""
    missing = []
    for test_case in test_cases:
        session_name, _, _ = extract_session_directive(test_case)
        if session_name is None:
            continue
        path = session_state_path(session_dir, session_name)
        if not path.exists():
            missing.append((test_case.test_scenario, session_name, str(path)))

    if missing:
        details = "; ".join(f"'{scenario}' wants session '{name}' ({path})" for scenario, name, path in missing)
        raise SessionStateError(
            f"{len(missing)} test case(s) reference a session with no saved storage_state file: "
            f"{details}. Run the case that has a SaveSession step first, or check the session name."
        )
