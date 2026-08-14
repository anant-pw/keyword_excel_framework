"""
Generates a single-file HTML report from the run results, plus appends a
summary of this run to reports/history/run_history.json so the report can
show a trend across recent runs.

Layout: a collapsible left sidebar with three pages (Results / History /
Logs), swapped client-side with plain JS - no server, still one portable
HTML file. Screenshots and full log file contents are embedded as
base64/text directly into the document for the same reason.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import base64
import html
import json
import os
import re

from core.owners_loader import resolve_owner

# Cap per log file embedded into the report. Debug-level file logs can get
# large on a long run; we keep the TAIL (most recent entries - closest to
# whatever failed) rather than the head, and say so when truncated.
_LOG_EMBED_MAX_BYTES = 2_000_000

# Matches core/logger.py's _FORMAT: "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_LOG_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| (\w+)\s*\|")
# Pulled out of the message itself (see core/keyword_engine.py's per-step log
# line) so a "View in logs" click can filter the Logs page to exactly the
# lines that belong to one step, not just one file.
_LOG_ROW_RE = re.compile(r"\[Row (\d+)\]")
_LOG_SCENARIO_RE = re.compile(r"Scenario='([^']*)'")

_CSS = """
* { box-sizing:border-box; }
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f5f6f8; margin:0; color:#1f2430;}
h1 { font-size:20px; margin:0 0 4px; }
h2 { font-size:15px; margin:0 0 14px; color:#333;}
.layout { display:flex; min-height:100vh; }

/* ---- sidebar ---- */
.sidebar { width:220px; flex-shrink:0; background:#1f2430; color:#cfd4e0; padding:18px 0; transition:width .15s ease; overflow:hidden; }
.sidebar.collapsed { width:44px; }
.sidebar-toggle { cursor:pointer; padding:0 16px 16px; font-size:16px; color:#8b93a8; user-select:none; }
.sidebar-brand { padding:0 18px 16px; font-size:13px; font-weight:700; color:#fff; white-space:nowrap; }
.sidebar.collapsed .sidebar-brand, .sidebar.collapsed .nav-label { display:none; }
.nav-item { padding:11px 18px; cursor:pointer; font-size:13px; white-space:nowrap; display:flex; align-items:center; gap:10px; }
.nav-item:hover { background:#2a3040; color:#fff; }
.nav-item.active { background:#2f5496; color:#fff; }
.nav-icon { width:16px; text-align:center; flex-shrink:0; }

/* ---- main content ---- */
.content { flex:1; padding:24px; min-width:0; }
.page { display:none; }
.page.active { display:block; }
.meta { color:#666; font-size:13px; margin-bottom:20px;}
.summary { display:flex; gap:16px; margin-bottom:20px; }
.card { background:#fff; border-radius:8px; padding:14px 20px; box-shadow:0 1px 3px rgba(0,0,0,.08); min-width:100px;}
.card .num { font-size:26px; font-weight:700;}
.pass .num { color:#1a9c5c;} .fail .num { color:#d13c3c;} .total .num { color:#333;}
.history-card { background:#fff; border-radius:8px; padding:16px 20px; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-bottom:24px;}
.history-card table { width:100%; border-collapse:collapse; font-size:12px;}
.history-card th, .history-card td { text-align:left; padding:6px 10px; border-top:1px solid #eee;}
.case { background:#fff; border-radius:8px; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,.08); overflow:hidden;}
.case-header { padding:12px 18px; cursor:pointer; display:flex; justify-content:space-between; align-items:center;}
.case-header.PASS { border-left:5px solid #1a9c5c;}
.case-header.FAIL { border-left:5px solid #d13c3c;}
.badge { font-size:11px; font-weight:700; padding:3px 8px; border-radius:10px; color:#fff;}
.badge.PASS { background:#1a9c5c;} .badge.FAIL { background:#d13c3c;} .badge.SKIPPED { background:#999;}
table.steps { width:100%; border-collapse:collapse; display:none;}
.case.open table.steps { display:table; }
.steps th, .steps td { text-align:left; padding:8px 18px; font-size:13px; border-top:1px solid #eee; vertical-align:top;}
.steps th { background:#fafafa; font-weight:600;}
.steps tr.FAIL td { background:#fff5f5; }
.steps tr.SKIPPED td { color:#999; }
.desc { font-weight:500; }
.msg { color:#a33; font-family:monospace; font-size:12px; display:block; margin-top:4px;}
.saved { color:#2f7a3c; font-family:monospace; font-size:12px; display:block; margin-top:4px;}
.shot { margin-top:6px; }
.shot img { max-width:220px; border:1px solid #ddd; border-radius:4px; cursor:zoom-in; }
.composite-tag { font-size:10px; color:#2f5496; border:1px solid #b7c6e6; background:#eef2fa; border-radius:8px; padding:1px 6px; margin-left:6px;}
.owner-tag { font-size:10px; color:#8a5a00; border:1px solid #e6c78a; background:#fff6e6; border-radius:10px; padding:3px 8px; margin-left:8px;}
tr.composite-row { cursor:pointer; }
tr.composite-row .arrow { display:inline-block; width:10px; font-size:10px; color:#2f5496; }
tr.nested-wrap { display:none; }
tr.nested-wrap.open { display:table-row; }
tr.log-wrap { display:none; }
tr.log-wrap.open { display:table-row; }
.nested-caption { font-size:11px; font-weight:600; color:#2f5496; padding:6px 12px 2px !important; border-top:none !important; }
table.nested { width:100%; border-collapse:collapse; margin:0 0 4px 0; background:#fafbfc; }
table.nested th, table.nested td { padding:5px 12px; font-size:12px; border-top:1px solid #eee; }
table.nested th { background:#f0f2f5; }
canvas { max-width:100%; }
.log-tag { font-size:10px; color:#6b5fa8; border:1px solid #d3cdee; background:#f3f1fb; border-radius:8px; padding:1px 6px; margin-left:6px;}
tr.log-row .arrow { display:inline-block; width:10px; font-size:10px; color:#6b5fa8; }
pre.step-log { margin:0 12px 8px; padding:10px 12px; background:#1f2430; color:#d6d9e3; font-size:11px; line-height:1.5;
               border-radius:4px; max-height:280px; overflow:auto; white-space:pre-wrap; word-break:break-word; }

/* ---- logs page ---- */
.log-controls { display:flex; gap:10px; align-items:center; margin-bottom:14px; flex-wrap:wrap; }
.log-controls input[type=text] { flex:1; min-width:220px; padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:13px; }
.log-controls label { font-size:12px; color:#555; display:flex; align-items:center; gap:4px; cursor:pointer; user-select:none; }
.log-file { background:#fff; border-radius:8px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); overflow:hidden; }
.log-file-header { padding:10px 16px; background:#2a3040; color:#fff; font-size:12px; font-family:monospace; display:flex; justify-content:space-between; }
.log-file-body { max-height:520px; overflow:auto; font-family:monospace; font-size:11px; line-height:1.6; }
.log-line { padding:1px 16px; white-space:pre-wrap; word-break:break-word; }
.log-line.hidden { display:none; }
.log-line.lvl-ERROR { background:#fff2f2; color:#a33; }
.log-line.lvl-WARNING { background:#fffaf0; color:#a67300; }
.log-line.lvl-DEBUG { color:#888; }
.log-line.flash { animation: flash-bg 1.6s ease; }
@keyframes flash-bg { 0% { background:#fff2a8; } 100% { background:transparent; } }
.log-truncated { font-size:11px; color:#a33; padding:4px 16px; font-style:italic; }
.view-logs-link { font-size:11px; color:#2f5496; text-decoration:none; margin-left:8px; white-space:nowrap; }
.view-logs-link:hover { text-decoration:underline; }

/* ---- failure summary (Results page) ---- */
.failure-summary { background:#fff; border-radius:8px; padding:14px 20px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,.08); border-left:5px solid #d13c3c; }
.failure-summary h3 { margin:0 0 8px; font-size:13px; color:#a33; }
.failure-summary-row { display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-top:1px solid #f0eded; }
.failure-summary-row .count { font-weight:700; color:#a33; flex-shrink:0; margin-left:12px; }
.failure-summary-row .fail-msg { font-family:monospace; color:#555; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

/* ---- screenshot lightbox (in-page, not a new tab - a data: URI opened
   with window.open has no <title>, which is why it showed as an
   "Untitled" tab) ---- */
.lightbox { display:none; position:fixed; inset:0; background:rgba(20,22,30,.88); z-index:1000; align-items:center; justify-content:center; cursor:zoom-out; }
.lightbox.open { display:flex; }
.lightbox img { max-width:92vw; max-height:92vh; border-radius:6px; box-shadow:0 4px 24px rgba(0,0,0,.4); }
"""

_JS = """
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    item.classList.add('active');
    document.getElementById('page-' + item.dataset.page).classList.add('active');
  });
});
document.getElementById('sidebarToggle').addEventListener('click', () => {
  document.getElementById('sidebar').classList.toggle('collapsed');
});
document.querySelectorAll('.case-header').forEach(h => {
  h.addEventListener('click', () => h.parentElement.classList.toggle('open'));
});
document.querySelectorAll('tr.composite-row, tr.log-row').forEach(row => {
  row.addEventListener('click', (e) => {
    e.stopPropagation();
    const detail = row.nextElementSibling;
    if (!detail || !(detail.classList.contains('nested-wrap') || detail.classList.contains('log-wrap'))) return;
    const open = detail.classList.toggle('open');
    const arrow = row.querySelector('.arrow');
    if (arrow) arrow.textContent = open ? '\\u25be' : '\\u25b8';
  });
});
const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightboxImg');
document.querySelectorAll('.shot img').forEach(img => {
  img.addEventListener('click', (e) => {
    e.stopPropagation();
    lightboxImg.src = img.src;
    lightbox.classList.add('open');
  });
});
lightbox.addEventListener('click', () => lightbox.classList.remove('open'));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') lightbox.classList.remove('open'); });

// ---- Logs page: level checkboxes + free-text search, combined with AND.
const logSearch = document.getElementById('logSearch');
const levelBoxes = document.querySelectorAll('.log-level-box');
function applyLogFilter() {
  const q = (logSearch.value || '').toLowerCase();
  const activeLevels = new Set(Array.from(levelBoxes).filter(b => b.checked).map(b => b.value));
  document.querySelectorAll('.log-line').forEach(line => {
    const levelOk = activeLevels.has(line.dataset.level || 'OTHER');
    const textOk = !q || line.textContent.toLowerCase().includes(q);
    line.classList.toggle('hidden', !(levelOk && textOk));
  });
}
if (logSearch) {
  logSearch.addEventListener('input', applyLogFilter);
  levelBoxes.forEach(b => b.addEventListener('change', applyLogFilter));
}

// ---- Step -> Logs correlation. Switches to the Logs page, filters down
// to this step's Row+Scenario, and scrolls/highlights the first match.
document.querySelectorAll('.view-logs-link').forEach(link => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    document.querySelector('.nav-item[data-page="logs"]').click();
    const row = link.dataset.row, scenario = link.dataset.scenario;
    logSearch.value = `[Row ${row}] Scenario='${scenario}'`;
    applyLogFilter();
    const firstMatch = document.querySelector('.log-line:not(.hidden)');
    if (firstMatch) {
      firstMatch.scrollIntoView({block: 'center'});
      firstMatch.classList.add('flash');
      setTimeout(() => firstMatch.classList.remove('flash'), 1600);
    }
  });
});

const bars = document.getElementById('historyChart');
if (bars) {
  const ctx = bars.getContext('2d');
  const data = JSON.parse(bars.dataset.runs);
  const w = bars.width, h = bars.height, n = data.length, barW = w / (n * 1.5);
  ctx.font = '10px sans-serif';
  data.forEach((run, i) => {
    const x = i * (barW * 1.5) + 10;
    const passH = run.total ? (run.passed / run.total) * (h - 20) : 0;
    const failH = run.total ? (run.failed / run.total) * (h - 20) : 0;
    ctx.fillStyle = '#1a9c5c';
    ctx.fillRect(x, h - 15 - passH, barW, passH);
    ctx.fillStyle = '#d13c3c';
    ctx.fillRect(x, h - 15 - passH - failH, barW, failH);
    ctx.fillStyle = '#666';
    ctx.fillText(run.suite.slice(0,3), x, h - 3);
  });
}
"""


@dataclass
class StepResult:
    row_id: int
    description: str
    keyword: str
    locator_value: str
    test_data: str
    status: str          # PASS | FAIL | SKIPPED
    message: str = ""
    screenshot_path: str = ""
    duration_ms: int = 0
    children: list = field(default_factory=list)   # nested StepResults for composite (common/) keywords
    saved: str = ""       # e.g. "$orderId = ORD-4821" when this step's SaveAs captured a value
    scenario: str = ""    # step.test_scenario at execution time - matches exactly what keyword_engine.py
                           # logs, so the report can filter the Logs page down to just this step's lines


@dataclass
class CaseResult:
    test_scenario: str
    status: str = "PASS"  # PASS | FAIL
    step_results: list = field(default_factory=list)
    duration_ms: int = 0
    source_file: str = ""
    source_sheet: str = ""


def _ci_run_id() -> str:
    return os.environ.get("BUILD_TAG", "").strip()


def _aggregate_results_path(report_dir: Path) -> Path:
    return report_dir / ".jenkins_report_results.json"


def _aggregate_logs_path(report_dir: Path) -> Path:
    return report_dir / ".jenkins_report_logs.json"


def _step_from_dict(data: dict) -> StepResult:
    return StepResult(
        row_id=data.get("row_id", 0),
        description=data.get("description", ""),
        keyword=data.get("keyword", ""),
        locator_value=data.get("locator_value", ""),
        test_data=data.get("test_data", ""),
        status=data.get("status", "PASS"),
        message=data.get("message", ""),
        screenshot_path=data.get("screenshot_path", ""),
        duration_ms=data.get("duration_ms", 0),
        children=[_step_from_dict(child) for child in data.get("children", [])],
        saved=data.get("saved", ""),
        scenario=data.get("scenario", ""),
    )


def _load_aggregate_results(report_dir: Path) -> list:
    path = _aggregate_results_path(report_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError):
        return []
    return [
        CaseResult(
            test_scenario=item.get("test_scenario", ""),
            status=item.get("status", "PASS"),
            step_results=[_step_from_dict(step) for step in item.get("step_results", [])],
            duration_ms=item.get("duration_ms", 0),
            source_file=item.get("source_file", ""),
            source_sheet=item.get("source_sheet", ""),
        )
        for item in data
    ]


def _save_aggregate_results(report_dir: Path, results: list) -> None:
    _aggregate_results_path(report_dir).write_text(
        json.dumps([asdict(result) for result in results], indent=2),
        encoding="utf-8",
    )


def _load_aggregate_logs(report_dir: Path) -> list:
    path = _aggregate_logs_path(report_dir)
    if not path.exists():
        return []
    try:
        return [str(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def _save_aggregate_logs(report_dir: Path, log_paths: list) -> None:
    unique = []
    seen = set()
    for path in log_paths:
        normalized = str(Path(path))
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    _aggregate_logs_path(report_dir).write_text(json.dumps(unique, indent=2), encoding="utf-8")


def _append_history(report_dir: Path, run_started: datetime, suite: str, total: int, passed: int, failed: int, limit: int) -> list:
    history_path = report_dir / "history" / "run_history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            history = []

    run_id = _ci_run_id()
    entry = {
        "timestamp": run_started.strftime("%Y-%m-%d %H:%M:%S"),
        "suite": suite,
        "total": total,
        "passed": passed,
        "failed": failed,
        "run_id": run_id,
    }

    if run_id:
        replaced = False
        for index, existing in enumerate(history):
            if existing.get("run_id") == run_id:
                history[index] = entry
                replaced = True
                break
        if not replaced:
            history.append(entry)
    else:
        history.append(entry)

    history = history[-limit:]
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return history


def _embed_screenshot(path_str: str) -> str:
    """Embeds the screenshot as a base64 data URI so the report is a single
    portable file - no separate screenshots/ folder needed to view it."""
    if not path_str:
        return ""
    path = Path(path_str)
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<div class="shot"><img src="data:image/png;base64,{encoded}" alt="failure screenshot"/></div>'


def _render_step_row(s) -> str:
    shot_html = _embed_screenshot(s.screenshot_path)
    msg_html = f"<span class='msg'>{html.escape(s.message)}</span>" if s.message else ""
    saved_html = f"<span class='saved'>{html.escape(s.saved)}</span>" if s.saved else ""
    composite_tag = (
        f"<span class='composite-tag'><span class='arrow'>&#9656;</span> composite: {html.escape(s.keyword)}</span>"
        if s.children else ""
    )
    view_logs_html = (
        f"<a href='#' class='view-logs-link' data-row='{s.row_id}' "
        f"data-scenario='{html.escape(s.scenario, quote=True)}'>view in logs</a>"
        if s.scenario else ""
    )
    row_class = f"{s.status} composite-row" if s.children else s.status
    nested_html = ""
    if s.children:
        nested_rows = "".join(_render_step_row(c) for c in s.children)
        nested_html = (
            f"<tr class='nested-wrap'><td colspan='6'>"
            f"<div class='nested-caption'>Steps from composite '{html.escape(s.keyword)}' "
            f"(Row {s.row_id} - {html.escape(s.description) or 'no description'})</div>"
            f"<table class='nested'>"
            f"<tr><th>Row</th><th>Description</th><th>Keyword</th><th>Locator</th><th>Data</th><th>Result</th></tr>"
            f"{nested_rows}</table></td></tr>"
        )
    main_row = (
        f"<tr class='{row_class}'><td>{s.row_id}</td>"
        f"<td class='desc'>{html.escape(s.description)}{composite_tag}</td>"
        f"<td>{html.escape(s.keyword)}</td><td>{html.escape(s.locator_value)}</td>"
        f"<td>{html.escape(s.test_data)}</td>"
        f"<td>{s.status}{msg_html}{saved_html}{shot_html}{view_logs_html}</td></tr>"
    )
    return main_row + nested_html


def _flatten_fail_steps(step_results: list):
    """Yields every FAIL StepResult, including ones nested inside composite
    keywords - a failure inside a shared common/ step is just as much a
    failure as a top-level one, and the summary should count it."""
    for s in step_results:
        if s.status == "FAIL":
            yield s
        if s.children:
            yield from _flatten_fail_steps(s.children)


def _render_failure_summary(all_results: list) -> str:
    """Groups every FAIL step across the whole run by its message, so a
    failure that repeats across several cases (e.g. the same locator
    timing out in 3 parallel cases) shows up once with a count, instead of
    being buried as 3 separate scroll-and-compare entries. Loosely mirrors
    Allure's 'Categories' view."""
    counts: dict = {}
    for case in all_results:
        for fail_step in _flatten_fail_steps(case.step_results):
            key = fail_step.message or f"{fail_step.keyword} failed (no message)"
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        return ""

    rows = "".join(
        f"<div class='failure-summary-row'>"
        f"<span class='fail-msg' title='{html.escape(msg)}'>{html.escape(msg)}</span>"
        f"<span class='count'>&times;{count}</span></div>"
        for msg, count in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    return (
        f"<div class='failure-summary'><h3>Failure summary "
        f"({sum(counts.values())} failed step(s), {len(counts)} distinct reason(s))</h3>{rows}</div>"
    )


def _read_log_tail(path: Path, max_bytes: int = _LOG_EMBED_MAX_BYTES) -> tuple:
    """Returns (text, truncated). Reads the TAIL of the file when it
    exceeds max_bytes - the end of the log is what's adjacent to whatever
    failed, so it's more useful to keep than the start."""
    try:
        size = path.stat().st_size
    except OSError:
        return "(log file not found - it may have been cleaned up)", False
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            data = f.read()
            return data.decode("utf-8", errors="replace"), True
        return f.read().decode("utf-8", errors="replace"), False


def _render_log_file(path_str: str) -> str:
    path = Path(path_str)
    text, truncated = _read_log_tail(path)
    truncated_html = (
        f"<div class='log-truncated'>Showing last {_LOG_EMBED_MAX_BYTES // 1000}KB - earlier lines omitted.</div>"
        if truncated else ""
    )

    line_htmls = []
    current_level = "OTHER"
    for raw_line in text.splitlines():
        match = _LOG_LINE_RE.match(raw_line)
        if match:
            current_level = match.group(1).strip().upper()
        # else: a continuation line (e.g. a traceback) - keep the level of
        # the log entry it belongs to, so filtering by level doesn't hide
        # half of a multi-line exception.
        row_match = _LOG_ROW_RE.search(raw_line)
        scenario_match = _LOG_SCENARIO_RE.search(raw_line)
        data_attrs = f" data-row='{row_match.group(1)}'" if row_match else ""
        data_attrs += f" data-scenario='{html.escape(scenario_match.group(1), quote=True)}'" if scenario_match else ""
        line_htmls.append(
            f"<div class='log-line lvl-{current_level}' data-level='{current_level}'{data_attrs}>"
            f"{html.escape(raw_line) or '&nbsp;'}</div>"
        )

    return (
        f"<div class='log-file'>"
        f"<div class='log-file-header'><span>{html.escape(path.name)}</span></div>"
        f"{truncated_html}"
        f"<div class='log-file-body'>{''.join(line_htmls)}</div>"
        f"</div>"
    )


def generate_html_report(results: list, report_dir: str, run_started: datetime, suite: str,
                          history_limit: int = 10, log_paths: list = None,
                          executed_by: str = "", owners: dict = None) -> Path:
    """Generate the custom report; under Jenkins, aggregate every sheet run."""
    log_paths = log_paths or []
    owners = owners or {}
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if _ci_run_id():
        all_results = _load_aggregate_results(out_dir)
        all_results.extend(results)
        _save_aggregate_results(out_dir, all_results)

        all_logs = _load_aggregate_logs(out_dir)
        all_logs.extend(log_paths)
        _save_aggregate_logs(out_dir, all_logs)

        report_results = all_results
        report_log_paths = _load_aggregate_logs(out_dir)
    else:
        report_results = results
        report_log_paths = log_paths

    total = len(report_results)
    passed = sum(1 for r in report_results if r.status == "PASS")
    failed = total - passed

    history = _append_history(out_dir, run_started, suite, total, passed, failed, history_limit)

    history_rows = "".join(
        f"<tr><td>{h['timestamp']}</td><td>{html.escape(h['suite'])}</td>"
        f"<td>{h['total']}</td><td>{h['passed']}</td><td>{h['failed']}</td></tr>"
        for h in reversed(history)
    )

    workbook_names = sorted({Path(r.source_file).name if r.source_file else "Unknown" for r in report_results})
    workbook_text = ", ".join(workbook_names)

    rows_html = []
    for r in report_results:
        step_rows = "".join(_render_step_row(s) for s in r.step_results)
        owner = resolve_owner(owners, r.test_scenario, warn=False)
        owner_html = f"<span class='owner-tag'>{html.escape(owner)}</span>" if owner else ""
        source_file = Path(r.source_file).name if r.source_file else "Unknown"
        source_sheet = r.source_sheet or "Unknown"
        source_html = (
            f"<div class='case-source'><strong>Workbook:</strong> {html.escape(source_file)}"
            f"&nbsp;&nbsp;|&nbsp;&nbsp;<strong>Sheet:</strong> {html.escape(source_sheet)}</div>"
        )
        rows_html.append(f"""
        <div class="case">
          <div class="case-header {r.status}">
            <div>
              <div><strong>{html.escape(r.test_scenario)}</strong>{owner_html}</div>
              {source_html}
            </div>
            <span class="badge {r.status}">{r.status}</span>
          </div>
          <table class="steps">
            <tr><th>Row</th><th>Description</th><th>Keyword</th><th>Locator</th><th>Data</th><th>Result</th></tr>
            {step_rows}
          </table>
        </div>""")

    history_json = json.dumps(history)
    logs_html = "".join(_render_log_file(p) for p in report_log_paths) or "<p>No log files recorded for this run.</p>"
    failure_summary_html = _render_failure_summary(report_results)
    log_levels = ["ERROR", "WARNING", "INFO", "DEBUG", "OTHER"]
    level_checkboxes = "".join(
        f"<label><input type='checkbox' class='log-level-box' value='{lvl}' checked> {lvl}</label>"
        for lvl in log_levels
    )

    html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Automation Execution Report - {html.escape(suite)}</title><style>{_CSS}
.case-source {{ font-size:11px; color:#666; margin-top:5px; }}
</style></head>
<body>
<div class="layout">
  <nav class="sidebar" id="sidebar">
    <div class="sidebar-toggle" id="sidebarToggle">&#9776;</div>
    <div class="sidebar-brand">Execution Report</div>
    <div class="nav-item active" data-page="results"><span class="nav-icon">&#9635;</span><span class="nav-label">Results</span></div>
    <div class="nav-item" data-page="history"><span class="nav-icon">&#8635;</span><span class="nav-label">Run history</span></div>
    <div class="nav-item" data-page="logs"><span class="nav-icon">&#9776;</span><span class="nav-label">Logs</span></div>
  </nav>

  <main class="content">
    <h1>Keyword Framework - Execution Report</h1>
    <div class="meta">Run started: {run_started.strftime('%Y-%m-%d %H:%M:%S')} | Suite: {html.escape(suite)} | Executed by: {html.escape(executed_by) if executed_by else 'unknown'}<br>Workbook(s): {html.escape(workbook_text)}</div>

    <div class="page active" id="page-results">
      <div class="summary">
        <div class="card total"><div class="num">{total}</div>Total</div>
        <div class="card pass"><div class="num">{passed}</div>Passed</div>
        <div class="card fail"><div class="num">{failed}</div>Failed</div>
      </div>
      <h2>Test cases (grouped by Test Scenario)</h2>
      {failure_summary_html}
      {"".join(rows_html)}
    </div>

    <div class="page" id="page-history">
      <h2>Run history (last {len(history)})</h2>
      <div class="history-card">
        <canvas id="historyChart" width="480" height="140" data-runs='{history_json}'></canvas>
        <table>
          <tr><th>Timestamp</th><th>Suite</th><th>Total</th><th>Passed</th><th>Failed</th></tr>
          {history_rows}
        </table>
      </div>
    </div>

    <div class="page" id="page-logs">
      <h2>Logs ({len(report_log_paths)} file{'s' if len(report_log_paths) != 1 else ''} - one per process; --workers &gt; 1 means one per worker)</h2>
      <div class="log-controls">
        <input type="text" id="logSearch" placeholder="Search log text, e.g. Row number, keyword, scenario, or sheet..."/>
        {level_checkboxes}
      </div>
      {logs_html}
    </div>
  </main>
</div>

<div class="lightbox" id="lightbox"><img id="lightboxImg" src="" alt="failure screenshot, full size"/></div>
<script>{_JS}</script>
</body></html>"""

    out_path = out_dir / "execution_report.html" if _ci_run_id() else out_dir / f"report_{run_started.strftime('%Y%m%d_%H%M%S')}.html"
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
