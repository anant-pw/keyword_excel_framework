"""
Entry point for a test run.

    python tests/runner.py                          # uses config.yaml as-is
    python tests/runner.py --suite Smoke             # override suite
    python tests/runner.py --suite Regression --headed
    python tests/runner.py --sheet-name ParallelDemo --workers 3
    python tests/runner.py --sheet-name SessionDemo

Failure behavior by Suite (run-level, since Suite is a per-step field now -
every step in a filtered case already matches the requested suite):
    Smoke                -> fail-fast: stop the test case on first step failure
    Sanity / Regression  -> continue-on-failure: run all steps, mark case
                             failed at the end if any step failed

Composite keywords: a Keyword/Action value that matches a Test Scenario
registered from common/*.xlsx is executed as a nested sequence against the
SAME CasePropertyStore as the calling case (see core/common_keywords.py).
A composite is always internally strict (its own steps stop at the first
failure) regardless of the calling suite - it's a reusable atomic unit, not
a place to make suite-level fail-fast/continue decisions.
"""
import argparse
import concurrent.futures
import multiprocessing as mp
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import keywords  # noqa: F401  (import triggers @keyword registration)
from core.config_loader import load_config
from core.driver_factory import DriverFactory
from core.excel_reader import read_test_suite
from core.keyword_engine import execute_step, registered_keywords
from core.common_keywords import CommonKeywordRegistry
from core.parallel import distribute_round_robin
from core.properties_loader import CasePropertyStore
from core.api_client import ApiCallContext
from core.session_manager import extract_session_directive, preflight_check_sessions, session_state_path
from core.exceptions import FrameworkError
from core.logger import get_logger, current_log_file
from core.report_generator import generate_html_report, CaseResult, StepResult

logger = get_logger("runner")

FAIL_FAST_SUITES = {"smoke"}

# Populated by main() before any test case runs. A module-level default
# (empty registry) means composite keywords are simply never found if a
# caller uses run_test_case()/_execute_steps() directly without going
# through main() first - e.g. in unit tests - rather than crashing.
common_registry = CommonKeywordRegistry()


def _capture_failure_screenshot(page, config, row_id: int) -> str:
    if not config.screenshot_on_failure:
        return ""
    shot_dir = Path(config.report_dir) / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / f"row{row_id}_FAILURE.png"
    try:
        page.screenshot(path=str(shot_path))
        return str(shot_path)
    except Exception as screenshot_err:
        logger.warning(f"Could not capture failure screenshot: {screenshot_err}")
        return ""


def _open_case_context(driver, test_case, config):
    """Shared by both the sequential and per-worker parallel paths (see
    core/session_manager.py's module docstring) so a case using
    UseSession behaves identically no matter which path runs it. Returns
    (context, page, effective_test_case, session_step_result) -
    session_step_result is None for a case that doesn't use a saved
    session; otherwise a synthetic StepResult recording that the session
    was applied, since the UseSession step itself never reaches
    _execute_steps and would otherwise vanish from the report."""
    session_name, directive, effective_case = extract_session_directive(test_case)
    if session_name is None:
        context, page = driver.new_page()
        return context, page, effective_case, None

    path = session_state_path(config.session_dir, session_name)
    context, page = driver.new_page(storage_state_path=str(path))
    session_result = StepResult(
        row_id=directive.row_id, description=directive.description, keyword=directive.keyword,
        locator_value="", test_data=directive.test_data, status="PASS",
        message=f"Session '{session_name}' loaded from {path}", scenario=directive.test_scenario,
    )
    return context, page, effective_case, session_result


def _execute_steps(page, steps, config, case_properties, api_context, fail_fast: bool, call_stack: list) -> list:
    """Runs a sequence of steps - either a whole test case, or a composite
    keyword's internal steps - against a shared CasePropertyStore and
    ApiCallContext (see core/api_client.py - a composite can make an API
    call the calling case then verifies, or vice versa, same as it already
    shares $var state). Returns the list of StepResult objects (including
    SKIPPED entries for any steps skipped due to fail-fast). Composite
    keywords encountered in the sequence recurse into this same function."""
    results = []

    for i, step in enumerate(steps):
        step_start = time.time()

        if step.keyword in common_registry:
            composite_case = common_registry.get(step.keyword)
            scenario_key = composite_case.test_scenario.strip().lower()
            if scenario_key in call_stack:
                chain = " -> ".join(call_stack + [composite_case.test_scenario])
                results.append(StepResult(
                    row_id=step.row_id, description=step.description, keyword=step.keyword,
                    locator_value="", test_data="", status="FAIL",
                    message=f"Recursive common-keyword call detected: {chain}", scenario=step.test_scenario,
                ))
                if fail_fast:
                    _append_skipped(results, steps[i + 1:])
                    break
                continue

            child_results = _execute_steps(
                page, composite_case.steps, config, case_properties, api_context,
                fail_fast=True,  # composites are always strict internally
                call_stack=call_stack + [scenario_key],
            )
            child_failed = any(r.status == "FAIL" for r in child_results)
            results.append(StepResult(
                row_id=step.row_id, description=step.description, keyword=step.keyword,
                locator_value="", test_data="",
                status="FAIL" if child_failed else "PASS",
                message="" if not child_failed else f"Composite '{step.keyword}' failed internally",
                children=child_results, scenario=step.test_scenario,
                duration_ms=int((time.time() - step_start) * 1000),
            ))
            if child_failed and fail_fast:
                logger.info(f"Fail-fast suite - stopping after composite '{step.keyword}' "
                            f"(Scenario='{step.test_scenario}', Row {step.row_id}) failed.")
                _append_skipped(results, steps[i + 1:])
                break
            continue

        try:
            execute_step(page, step, config, case_properties, api_context)
            saved = ""
            if step.save_as:
                # execute_step already stored it via case_properties.capture();
                # resolve() reads it straight back for display, so the report
                # never has to know the value beyond what the store already has.
                saved = f"${step.save_as} = {case_properties.resolve('$' + step.save_as)!r}"
            results.append(StepResult(
                row_id=step.row_id, description=step.description, keyword=step.keyword,
                locator_value=step.locator_value, test_data=step.test_data, status="PASS",
                duration_ms=int((time.time() - step_start) * 1000), saved=saved, scenario=step.test_scenario,
            ))
        except Exception as e:
            # One branch for both FrameworkError and any unanticipated
            # exception - both need identical screenshot + fail-fast/skip
            # handling; only the logged message/level differs. See
            # tests/unit/test_runner_logic.py for the regression test that
            # caught an earlier version where these had drifted apart.
            is_framework_error = isinstance(e, FrameworkError)
            message = str(e) if is_framework_error else f"Unexpected error: {e}"
            screenshot_path = _capture_failure_screenshot(page, config, step.row_id)

            results.append(StepResult(
                row_id=step.row_id, description=step.description, keyword=step.keyword,
                locator_value=step.locator_value, test_data=step.test_data, status="FAIL",
                message=message, screenshot_path=screenshot_path, scenario=step.test_scenario,
                duration_ms=int((time.time() - step_start) * 1000),
            ))
            if is_framework_error:
                logger.error(f"[Row {step.row_id}] Scenario='{step.test_scenario}' Desc='{step.description}' "
                             f"-> {step.keyword} FAILED: {e}")
            else:
                logger.exception(f"[Row {step.row_id}] Scenario='{step.test_scenario}' Desc='{step.description}' "
                                  f"-> {step.keyword} raised an unexpected error")

            if fail_fast:
                logger.info(f"Fail-fast suite - stopping remaining steps in Scenario='{step.test_scenario}'.")
                _append_skipped(results, steps[i + 1:])
                break

    return results


def _append_skipped(results: list, remaining_steps) -> None:
    for step in remaining_steps:
        results.append(StepResult(
            row_id=step.row_id, description=step.description, keyword=step.keyword,
            locator_value=step.locator_value, test_data=step.test_data, status="SKIPPED",
            message="Skipped: prior step failed (fail-fast suite)", scenario=step.test_scenario,
        ))


def run_test_case(page, test_case, config, fail_fast: bool) -> CaseResult:
    result = CaseResult(test_scenario=test_case.test_scenario)
    case_properties = CasePropertyStore(config.properties_dir, config.env_variables)
    api_context = ApiCallContext()
    case_start = time.time()

    result.step_results = _execute_steps(page, test_case.steps, config, case_properties, api_context,
                                          fail_fast, call_stack=[])
    result.status = "FAIL" if any(r.status == "FAIL" for r in result.step_results) else "PASS"
    result.duration_ms = int((time.time() - case_start) * 1000)
    return result


def _run_sequential(test_cases, config, fail_fast) -> list:
    results = []
    with DriverFactory(config) as driver:
        for test_case in test_cases:
            context, page, effective_case, session_result = _open_case_context(driver, test_case, config)
            try:
                logger.info(f"--- Running '{test_case.test_scenario}' ({len(effective_case.steps)} steps) ---")
                result = run_test_case(page, effective_case, config, fail_fast)
                if session_result:
                    result.step_results.insert(0, session_result)
                results.append(result)
                logger.info(f"--- '{test_case.test_scenario}' -> {result.status} ({result.duration_ms}ms) ---")
            finally:
                driver.close_context(context)
    return results


def _run_worker_chunk(indexed_chunk: list, config, fail_fast: bool) -> tuple:
    """Runs one worker's assigned (original_index, TestCase) pairs. Must be
    a module-level function (not a closure/lambda) so ProcessPoolExecutor
    can pickle it. Each worker process gets a fresh Python interpreter -
    `import keywords` at the top of this module re-registers built-in
    keywords automatically, but the common-keyword registry is populated
    per-process here explicitly, since it isn't inherited from the parent
    process's memory. One browser is launched per worker and reused for
    every case in its chunk, mirroring the sequential path's per-run
    (here: per-worker) browser lifecycle.

    Returns (results, this_worker's_log_file_path) - see _run_parallel for
    why the log path has to come back explicitly rather than being
    inferred by the parent process."""
    common_registry.load(config.common_dir, set(registered_keywords()))
    results = []
    with DriverFactory(config) as driver:
        for original_index, test_case in indexed_chunk:
            context, page, effective_case, session_result = _open_case_context(driver, test_case, config)
            try:
                logger.info(f"[worker pid={mp.current_process().pid}] Running '{test_case.test_scenario}' "
                            f"({len(effective_case.steps)} steps)")
                result = run_test_case(page, effective_case, config, fail_fast)
                if session_result:
                    result.step_results.insert(0, session_result)
                results.append((original_index, result))
            finally:
                driver.close_context(context)
    return results, str(current_log_file())


def _run_parallel(test_cases, config, fail_fast, worker_count: int) -> tuple:
    """Returns (case_results_in_sheet_order, worker_log_paths). Each worker
    process writes its OWN log file (see core/logger.py - filename
    includes the PID specifically so parallel workers never collide), so
    the parent process can't just read current_log_file() and get the
    whole picture - it has to collect each worker's path explicitly and
    hand all of them to the report."""
    indexed = list(enumerate(test_cases))
    buckets = [b for b in distribute_round_robin(indexed, worker_count) if b]  # drop empty buckets
    actual_workers = len(buckets)
    logger.info(f"Distributing {len(test_cases)} test case(s) across {actual_workers} worker process(es)")

    ctx = mp.get_context("spawn")  # avoid fork-related issues with Playwright's driver subprocess
    indexed_results = []
    worker_log_paths = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=actual_workers, mp_context=ctx) as executor:
        futures = [executor.submit(_run_worker_chunk, bucket, config, fail_fast) for bucket in buckets]
        for future in concurrent.futures.as_completed(futures):
            chunk_results, worker_log_path = future.result()
            indexed_results.extend(chunk_results)
            worker_log_paths.append(worker_log_path)

    indexed_results.sort(key=lambda pair: pair[0])  # restore original sheet order, not completion order
    return [result for _, result in indexed_results], worker_log_paths


def main():
    parser = argparse.ArgumentParser(description="Run the keyword-driven Excel test suite.")
    parser.add_argument("--suite", choices=["Smoke", "Sanity", "Regression"], default=None,
                         help="Override suite from config.yaml")
    parser.add_argument("--headed", action="store_true", help="Run with a visible browser")
    parser.add_argument("--sheet-file", default=None, help="Override test_sheet_file from config.yaml")
    parser.add_argument("--sheet-name", default=None,
                         help="Override sheet_name from config.yaml - lets one workbook hold several "
                              "independent demo sheets (e.g. TestSteps, ParallelDemo, SessionDemo)")
    parser.add_argument("--workers", type=int, default=None,
                         help="Override workers from config.yaml (>1 runs cases across parallel processes)")
    args = parser.parse_args()

    config = load_config()
    if args.suite:
        config.suite = args.suite
    if args.headed:
        config.headless = False
    if args.sheet_file:
        config.test_sheet_file = args.sheet_file
    if args.sheet_name:
        config.sheet_name = args.sheet_name
    if args.workers:
        config.workers = args.workers

    fail_fast = config.suite.lower() in FAIL_FAST_SUITES
    run_started = datetime.now()
    logger.info(f"=== Run started | Suite={config.suite} | Sheet={config.sheet_name} | Browser={config.browser} "
                f"| Headless={config.headless} | FailFast={fail_fast} ===")
    logger.info(f"Log file: {current_log_file()}")
    logger.info(f"Registered keywords: {registered_keywords()}")

    common_registry.load(config.common_dir, set(registered_keywords()))

    test_cases = read_test_suite(config.test_sheet_file, sheet_name=config.sheet_name, suite_filter=config.suite)
    if not test_cases:
        logger.warning(f"No test cases found for Suite='{config.suite}' in {config.test_sheet_file}")
        return 0

    # Checked once, up front, for every case in the run (sequential or
    # parallel) - a missing session file fails the whole run immediately
    # rather than after some workers have already opened browsers.
    preflight_check_sessions(test_cases, config.session_dir)

    results = []
    if config.workers > 1 and len(test_cases) > 1:
        results, worker_log_paths = _run_parallel(test_cases, config, fail_fast, config.workers)
        log_paths = [str(current_log_file())] + worker_log_paths
    else:
        results = _run_sequential(test_cases, config, fail_fast)
        log_paths = [str(current_log_file())]

    report_path = generate_html_report(results, config.report_dir, run_started, config.suite, config.history_limit,
                                        log_paths=log_paths)
    logger.info(f"Report generated: {report_path}")

    failed_count = sum(1 for r in results if r.status == "FAIL")
    logger.info(f"=== Run complete: {len(results)} case(s), {failed_count} failed ===")
    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
