# Keyword-Driven Playwright Framework (Python)

An Excel-driven UI automation framework: test cases are authored as rows in
a spreadsheet, not as code. QA engineers who don't write Python can add and
maintain test cases; the Python layer only needs to grow when a genuinely
new keyword is needed.

## Architecture

```
config/config.yaml          - run settings (browser, headless, suite, env vars)
properties/                 - object repository + data indirection, one file
                                per page/module (e.g. login.properties),
                                loaded via the LoadProperties keyword
testsheets/                 - the Excel keyword sheet(s)
  TestSuite.xlsx
common/                     - reusable composite keywords, one Test Scenario
                                per callable name, same schema as testsheets/
  login_flow.xlsx
testdata/                   - actual test INPUT files (csv/pdf/images a test
                                reads or uploads) - not locators or credentials
core/
  config_loader.py           - typed config access
  logger.py                   - per-run file + console logging
  excel_reader.py             - parses .xlsx into TestCase/TestStep objects
  properties_loader.py        - parses .properties files; CasePropertyStore
                                 resolves $name references, scoped per test case
  locator_resolver.py         - LocatorType/LocatorValue -> Playwright Locator,
                                 incl. "any" fallback chain
  common_keywords.py          - scans common/*.xlsx, registers each Test
                                 Scenario as a callable composite keyword
  driver_factory.py           - Playwright browser/context/page lifecycle
  keyword_engine.py           - keyword registry + dispatcher (decorator-based)
  report_generator.py         - HTML report, run-history tracking, nested
                                 composite-step rendering
  exceptions.py                - typed exception hierarchy
keywords/
  browser_keywords.py          - Navigate, Back, Forward, Refresh, alerts, windows
  element_keywords.py          - Click, Type, SelectDropdown, Hover, Check/Uncheck
  assertion_keywords.py        - VerifyText, ElementDisplayed, VerifyURL, VerifyTitle
  utility_keywords.py          - LoadProperties, Wait, WaitForElement, Screenshot
tests/
  runner.py                    - entry point: reads Excel, executes, reports
  unit/                        - pytest self-tests for the framework's own
                                   core modules (no browser needed)
conftest.py                  - project-root import path for pytest
reports/
  history/run_history.json    - rolling log of recent run summaries
  report_<ts>.html
logs/                        - one timestamped log file per run
```

## Test sheet columns

| Column | Meaning |
|---|---|
| TestCase ID | Groups rows into one test case |
| Test Scenario | Short display name for the case |
| Test Case Description | What the case verifies (documentation) |
| StepNo | Execution order within the test case |
| Keyword/Action | Must match a registered keyword (see list below) |
| LocatorType | `id` \| `css` \| `xpath` \| `text` \| `role` \| `testid` \| `placeholder` \| `name` \| `any` |
| LocatorValue | Locator value, a `$name` reference, or a JSON object of strategies when LocatorType=`any` |
| Test Data | Input value / URL / expected text - also accepts a `$name` reference |
| Expected Output | Human-readable description (documentation only, not evaluated) |
| Suite | `Smoke` \| `Sanity` \| `Regression` - drives failure behavior, see below |
| Priority | `High` \| `Medium` \| `Low` - for selective runs (not yet wired into the CLI) |
| Enabled | `TRUE`/`FALSE` - disable a step without deleting it |
| Comments | Free text |

`DependsOn` was deliberately left out - see "Design decisions" below.

## Properties files and the `$name` / `{{VAR}}` indirection

Both **LocatorValue and Test Data** accept a bare `$name` reference, resolved
from whatever `properties/*.properties` file the case's `LoadProperties` step
loaded. This is the mechanism that keeps literal locators *and* literal
credentials out of the sheet entirely - not just LocatorValue.

```
# properties/login.properties
usernameField=input[name='username']
passwordField=input[name='password']
loginButton=button::Log in
demoUsername={{username}}
demoPassword={{password}}
```

```
# testsheets/TestSuite.xlsx
Keyword/Action=LoadProperties, Test Data=login
Keyword/Action=Type, LocatorType=css, LocatorValue=$usernameField, Test Data=$demoUsername
Keyword/Action=Type, LocatorType=css, LocatorValue=$passwordField, Test Data=$demoPassword
```

`{{VAR}}` (used *inside* a `.properties` file, not directly in the sheet)
resolves from OS environment variables first, `config.yaml env_variables`
second. In CI, set the real values as environment variables/secrets - the
config.yaml block is a local/demo fallback only, never a place for real
credentials.

### The `any` LocatorType - fallback locator chain

```json
{"testid": "login-submit", "css": "button.submit-btn", "xpath": "//button[text()='Login']"}
```
Strategies are tried in order until one resolves. Use this where markup
differs across environments or an A/B test changes the DOM.

## Failure behavior by Suite

- **Smoke**: fail-fast. First failed step stops the test case; remaining
  steps are marked `SKIPPED`.
- **Sanity / Regression**: continue-on-failure. All steps run regardless of
  earlier failures; the case is marked `FAIL` at the end if any step failed.

Enforced in `tests/runner.py` via `FAIL_FAST_SUITES`.

## Registered keywords

LoadProperties, Navigate, Back, Forward, Refresh, AcceptAlert, DismissAlert,
SwitchToWindow, CloseWindow, Click, ClickByJavaScript, Type, TypeSlowly,
Clear, Hover, SelectDropdown, Check, Uncheck, ScrollIntoView,
ElementDisplayed, ElementNotDisplayed, ElementEnabled, VerifyText,
VerifyTextContains, VerifyURL, VerifyTitle, Wait, WaitForElement, Screenshot.

## Adding a new keyword

```python
# keywords/element_keywords.py
from core.keyword_engine import keyword, StepContext
from core.locator_resolver import resolve_locator

@keyword("DoubleClick")
def double_click(ctx: StepContext) -> None:
    locator = resolve_locator(ctx.page, ctx.step.locator_type, ctx.resolved_locator_value,
                               timeout_ms=ctx.config.default_timeout_ms)
    locator.dblclick(timeout=ctx.config.default_timeout_ms)
```
No registry file to edit by hand - the `@keyword(...)` decorator does it at
import time, and `keywords/__init__.py` already imports every module.

## Parallel execution

```bash
python tests/runner.py --suite Regression --workers 4
```

Test cases are distributed round-robin across `workers` separate OS
**processes** (not threads - Playwright's sync API isn't thread-safe, so
each worker gets its own process, its own `sync_playwright()` instance, and
launches its own browser once, reused for every case in its chunk). Results
are reordered back to original sheet order before the report is generated,
regardless of which worker finished first. `workers: 1` (the default) keeps
the exact original sequential path with zero multiprocessing overhead.

Each worker process gets its own log file (`logs/run_<timestamp>_pid<pid>.log`)
so concurrent workers never interleave writes into one file.

## Composite keywords (common/)

A `Test Scenario` defined in any `.xlsx` under `common/` becomes a callable
keyword, usable directly in `Keyword/Action` - no special file/sheet
addressing syntax. It executes against the **same** `CasePropertyStore` as
the calling case, so a `LoadProperties` step earlier in the case (or inside
the composite itself) is visible wherever it's needed.

```
# common/login_flow.xlsx - Test Scenario "LoginFlow"
LoadProperties -> Navigate -> Type $usernameField/$demoUsername -> ... -> ElementDisplayed
```

```
# testsheets/TestSuite.xlsx
Keyword/Action=LoginFlow          <- runs the whole composite as one step
Keyword/Action=VerifyURL, Test Data=home.html   <- calling case's own steps continue after it
```

Rules worth knowing:
- **Startup fails loudly, not silently**, if two `common/` files define the
  same scenario name, or a scenario name collides with a built-in keyword -
  see `core/common_keywords.py`.
- A composite is **always internally strict** (stops at its own first
  failure) regardless of the calling suite - it's a reusable atomic unit,
  not a place to make suite-level fail-fast/continue decisions. Whether the
  *calling* case stops after a composite fails still follows the calling
  suite's fail-fast/continue rule.
- **Recursion guard**: a composite calling itself (directly or via another
  composite) raises immediately instead of looping.
- The report shows composite calls with a "composite" tag and nests the
  internal steps in a sub-table underneath - you can see exactly which
  internal step broke, not just "LoginFlow: FAIL".

## Self-tests

`tests/unit/` covers the framework's own core modules - no browser, no
`.xlsx` fixtures beyond what each test builds in a `tmp_path`:

```bash
pip install -r requirements.txt
python -m pytest tests/unit/ -v
```

Covers: `properties_loader` ($/​{{VAR}} resolution, per-case isolation),
`excel_reader` (Test Scenario grouping, comma-suite matching, column
validation), `locator_resolver` (strategy dispatch, the `any` fallback
chain), the fail-fast/continue-on-failure branch in `runner.py`,
`common_keywords` (registration, collision detection, nested execution,
recursion guard), and `parallel` (round-robin distribution, original-order
reassembly after out-of-order completion). One of these tests caught a
real bug during development - an unexpected (non-`FrameworkError`)
exception wasn't getting the same screenshot/skip handling as a
`FrameworkError` - now pinned down as a regression test.

## Running

```bash
pip install -r requirements.txt
python -m playwright install chromium

python tests/runner.py                          # uses suite from config.yaml
python tests/runner.py --suite Smoke
python tests/runner.py --suite Regression --headed
python tests/runner.py --sheet-file testsheets/OtherSuite.xlsx
```

Reports land in `reports/report_<timestamp>.html` - a run-history chart and
table across the last `history_limit` runs, plus an accordion per test case
(click to expand steps). Failure screenshots save alongside it.

## Design decisions worth knowing (and one deliberately rejected)

- **Rejected: a continuous-flow-per-sheet model** (one long scripted journey
  per sheet, suite tagged per-step rather than per-case) - closer to how a
  real production framework this was modeled on works. Not used here because
  it can't be parallelized (step 40 can depend on step 3's session) and is
  hard to unit-test in isolation. This framework keeps discrete,
  independent `TestCaseID`-grouped cases instead, each getting its own
  browser context - the tradeoff that actually supports parallel execution
  and self-tests, both of which are on the roadmap below.
- **`DependsOn` intentionally omitted** - per project decision, not
  implemented in this pass.
- **Properties are scoped per test case**, not global - `LoadProperties`
  populates a fresh `CasePropertyStore` created for each case, so two
  sheets can each define a `submitButton` locator without colliding.

## Known gaps / next steps

- No cross-step variable capture within a case (e.g. reading a generated ID
  in step 2 and reusing it in step 5) - next up.
- No CI integration wired up yet, and no AI-assisted verdict classification
  (GENUINE_FAIL / FLAKY / ENV_ISSUE / etc.) - both deliberately deferred to
  a later pass.
- Parallel execution splits by test case, not by suite - running cases
  concurrently against a stateful backend could still collide if two cases
  share server-side state (e.g. the same account). Not an issue with this
  framework's local demo pages, but worth knowing before pointing
  `--workers` at a real environment with shared test data.
