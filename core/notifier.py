"""
Post-run reporting: builds a one-row-per-Test-Scenario .xlsx execution
summary (openpyxl - already a dependency, see core/excel_reader.py) and,
if configured, emails it plus the HTML report to a recipient list, CC'ing
each failed scenario's owner individually (see core/owners_loader.py).

Deliberately does NOT try to host the HTML report anywhere and email a
link to it instead of the file. A "link" is only useful if something
serves the file over HTTP - locally that's a file:// path (useless to a
remote recipient), and in CI a GitHub Actions artifact URL requires the
recipient to be authenticated into the repo and expires with the
retention window. Hosting reports somewhere is real, separate
infrastructure, not a report-formatting detail - so this attaches the
report and summary files directly, which behaves identically whether the
run happened on a laptop or in CI. config.email_report_base_url is left
as an optional escape hatch: set it once reports ARE published somewhere,
and a link is added alongside the attachment, not instead of it.

The SMTP password is never read from config.yaml or owners.yaml - only
from the SMTP_PASSWORD OS/CI environment variable, mirroring how real
secrets already flow into this framework via {{VAR}} tokens (see
core/properties_loader.py's module docstring).
"""
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from core.logger import get_logger
from core.owners_loader import resolve_owner

logger = get_logger("notifier")


def resolve_executed_by() -> str:
    """Best-effort identity of whoever/whatever triggered this run.
    GitHub Actions always sets GITHUB_ACTOR for every run. Jenkins only
    exposes the triggering human via BUILD_USER/BUILD_USER_ID, and only
    when the 'Build User Vars' plugin is installed and its wrapper step is
    used - most Jenkins setups don't have that configured, so a Jenkins
    agent run falls through to the OS user, which is typically a service
    account, not a person. That's a real reporting gap worth knowing
    about rather than a bug: this function can't invent identity data
    Jenkins never exposed."""
    if os.environ.get("GITHUB_ACTOR"):
        return os.environ["GITHUB_ACTOR"]
    if os.environ.get("BUILD_USER"):
        return os.environ["BUILD_USER"]
    if os.environ.get("BUILD_USER_ID"):
        return os.environ["BUILD_USER_ID"]
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"


def _flatten(step_results):
    for s in step_results:
        yield s
        if s.children:
            yield from _flatten(s.children)


def build_summary_workbook(results: list, report_dir: str, run_started: datetime, suite: str,
                            executed_by: str, owners: dict) -> Path:
    """One row per Test Scenario (case), not per step - this is a
    triage/routing artifact for deciding who needs to look at what, not a
    replacement for the HTML report's step-level detail."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"

    headers = ["Test Scenario", "Status", "Owner", "Steps", "Duration (ms)",
               "First Failure Message", "Executed By", "Run Started", "Suite", "Workbook", "Sheet"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for case in results:
        first_fail = next((s.message for s in _flatten(case.step_results) if s.status == "FAIL"), "")
        ws.append([
            case.test_scenario, case.status, resolve_owner(owners, case.test_scenario, warn=False),
            len(case.step_results), case.duration_ms, first_fail,
            executed_by, run_started.strftime("%Y-%m-%d %H:%M:%S"), suite,
            Path(case.source_file).name if getattr(case, "source_file", "") else "Unknown",
            getattr(case, "source_sheet", "") or "Unknown",
        ])

    for col_cells in ws.columns:
        width = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(width + 2, 10), 60)

    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"summary_{run_started.strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(out_path)
    return out_path


def send_report_email(config, results: list, report_path, summary_path,
                       run_started: datetime, suite: str, executed_by: str, owners: dict) -> bool:
    """Send one build-level notification containing the aggregated run results."""
    if not config.email_enabled:
        return False

    failed = sum(1 for r in results if r.status == "FAIL")
    passed = sum(1 for r in results if r.status == "PASS")
    total = len(results)

    if config.email_send_on == "failure_only" and failed == 0:
        logger.info("email.send_on=failure_only and every case passed - skipping notification email.")
        return False

    if not config.email_smtp_host or not config.email_from or not config.email_to:
        logger.warning(
            "email.enabled is true but smtp_host/from_address/to_addresses is incomplete - "
            "skipping notification email."
        )
        return False

    status_word = "FAILED" if failed else "PASSED"
    subject = (
        f"[{status_word}] {suite} run - {total} case(s), "
        f"{failed} failed - run by {executed_by}"
    )

    def _source(case):
        workbook = (
            Path(getattr(case, "source_file", "")).name
            if getattr(case, "source_file", "")
            else "Unknown"
        )
        sheet = getattr(case, "source_sheet", "") or "Unknown"
        return workbook, sheet

    # ------------------------------------------------------------------
    # Build workbook -> sheet -> cases structure for the email.
    # Keep ordering stable while placing failed sheets/cases first.
    # ------------------------------------------------------------------
    grouped = {}
    for case in results:
        workbook, sheet = _source(case)
        grouped.setdefault(workbook, {}).setdefault(sheet, []).append(case)

    def _sheet_sort(item):
        sheet_name, cases = item
        failed_count = sum(1 for case in cases if case.status == "FAIL")
        return (-failed_count, sheet_name.lower())

    def _workbook_sort(item):
        workbook_name, sheets = item
        failed_count = sum(
            1
            for cases in sheets.values()
            for case in cases
            if case.status == "FAIL"
        )
        return (-failed_count, workbook_name.lower())

    # ------------------------------------------------------------------
    # Failed owner CCs: preserve existing behavior but de-duplicate and
    # never duplicate an address already present in To.
    # ------------------------------------------------------------------
    configured_to = []
    seen_to = set()
    for address in config.email_to:
        normalized = str(address).strip()
        key = normalized.lower()
        if normalized and key not in seen_to:
            seen_to.add(key)
            configured_to.append(normalized)

    failed_owners = []
    seen_cc = set()

    if config.email_cc_owners_on_failure:
        for case in results:
            if case.status != "FAIL":
                continue

            owner = resolve_owner(owners, case.test_scenario, warn=False)
            if owner == "Unowned":
                continue

            normalized = str(owner).strip()
            key = normalized.lower()

            if normalized and key not in seen_to and key not in seen_cc:
                seen_cc.add(key)
                failed_owners.append(normalized)

    cc_list = failed_owners

    # ------------------------------------------------------------------
    # Plain-text email body
    # ------------------------------------------------------------------
    body_lines = [
        f"Run started: {run_started.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Executed by: {executed_by}",
        f"Total: {total} | Passed: {passed} | Failed: {failed}",
        "",
        "EXECUTION SUMMARY",
        "=================",
        "",
    ]

    if grouped:
        for workbook, sheets in sorted(grouped.items(), key=_workbook_sort):
            workbook_total = sum(len(cases) for cases in sheets.values())
            workbook_failed = sum(
                1
                for cases in sheets.values()
                for case in cases
                if case.status == "FAIL"
            )
            workbook_passed = workbook_total - workbook_failed

            body_lines.append(
                f"{workbook}  |  Total: {workbook_total} | "
                f"Passed: {workbook_passed} | Failed: {workbook_failed}"
            )

            for sheet, cases in sorted(sheets.items(), key=_sheet_sort):
                sheet_total = len(cases)
                sheet_failed = sum(1 for case in cases if case.status == "FAIL")
                sheet_passed = sheet_total - sheet_failed

                body_lines.append(
                    f"  └─ {sheet}  |  Total: {sheet_total} | "
                    f"Passed: {sheet_passed} | Failed: {sheet_failed}"
                )

            body_lines.append("")

    if config.email_report_base_url:
        body_lines.append(
            f"Report: {config.email_report_base_url.rstrip('/')}/{Path(report_path).name}"
        )

    body_lines.append("Full HTML report and per-scenario Excel summary are attached.")

    # ------------------------------------------------------------------
    # Failure section: workbook -> sheet -> failed cases
    # ------------------------------------------------------------------
    if failed:
        body_lines.extend([
            "",
            "FAILED TEST CASES",
            "=================",
            "",
        ])

        failed_grouped = {}
        for case in results:
            if case.status != "FAIL":
                continue

            workbook, sheet = _source(case)
            failed_grouped.setdefault(workbook, {}).setdefault(sheet, []).append(case)

        for workbook, sheets in sorted(failed_grouped.items(), key=_workbook_sort):
            body_lines.append(f"{workbook}")

            for sheet, cases in sorted(sheets.items(), key=_sheet_sort):
                body_lines.append(f"  {sheet}")

                for case in cases:
                    owner = resolve_owner(
                        owners,
                        case.test_scenario,
                        warn=False,
                    )
                    body_lines.append(
                        f"    • {case.test_scenario}"
                    )
                    body_lines.append(
                        f"      Owner: {owner}"
                    )

                body_lines.append("")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.email_from
    msg["To"] = ", ".join(configured_to)

    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    msg.set_content("\n".join(body_lines))

    if config.email_attach_report and report_path and Path(report_path).exists():
        msg.add_attachment(
            Path(report_path).read_bytes(),
            maintype="text",
            subtype="html",
            filename=Path(report_path).name,
        )

    if config.email_attach_summary and summary_path and Path(summary_path).exists():
        msg.add_attachment(
            Path(summary_path).read_bytes(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=Path(summary_path).name,
        )

    all_recipients = configured_to + cc_list
    password = os.environ.get("SMTP_PASSWORD", "")

    try:
        with smtplib.SMTP(
            config.email_smtp_host,
            config.email_smtp_port,
            timeout=20,
        ) as server:
            server.starttls()

            if config.email_smtp_user:
                server.login(
                    config.email_smtp_user,
                    password,
                )

            server.send_message(
                msg,
                to_addrs=all_recipients,
            )

        logger.info(
            f"Notification email sent to {all_recipients}"
        )
        return True

    except Exception as e:
        logger.error(
            f"Failed to send notification email: {e}"
        )
        return False
