"""
Unit tests for core/notifier.py. build_summary_workbook() is exercised
directly against a real .xlsx written to tmp_path; send_report_email() has
smtplib.SMTP mocked out - a unit test must never open a real socket.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import openpyxl

from core.notifier import build_summary_workbook, send_report_email, resolve_executed_by
from core.report_generator import CaseResult, StepResult
from core.config_loader import RunConfig


def _config(**overrides):
    cfg = RunConfig()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _results():
    passed = CaseResult(test_scenario="Search Flow", status="PASS", duration_ms=100, step_results=[
        StepResult(row_id=1, description="d", keyword="Click", locator_value="", test_data="", status="PASS"),
    ])
    failed = CaseResult(test_scenario="Api To Ui Handoff", status="FAIL", duration_ms=200, step_results=[
        StepResult(row_id=2, description="d", keyword="VerifyText", locator_value="", test_data="",
                   status="FAIL", message="expected X got Y"),
    ])
    return [passed, failed]


class TestBuildSummaryWorkbook:
    def test_one_row_per_case_with_owner_and_first_failure_message(self, tmp_path):
        owners = {"api to ui handoff": "api-module@example.com"}
        path = build_summary_workbook(_results(), str(tmp_path), datetime(2026, 1, 1, 9, 0, 0),
                                       "Smoke", "alice", owners)
        wb = openpyxl.load_workbook(path)
        rows = {row[0]: row for row in wb.active.iter_rows(min_row=2, values_only=True)}

        assert rows["Search Flow"][1] == "PASS"
        assert rows["Search Flow"][2] == "Unowned"

        failed_row = rows["Api To Ui Handoff"]
        assert failed_row[1] == "FAIL"
        assert failed_row[2] == "api-module@example.com"
        assert failed_row[5] == "expected X got Y"
        assert failed_row[6] == "alice"
        assert failed_row[8] == "Smoke"


class TestSendReportEmail:
    def test_skips_when_disabled(self, tmp_path):
        cfg = _config(email_enabled=False)
        sent = send_report_email(cfg, _results(), tmp_path / "r.html", tmp_path / "s.xlsx",
                                  datetime.now(), "Smoke", "alice", {})
        assert sent is False

    def test_skips_when_failure_only_and_all_passed(self, tmp_path):
        cfg = _config(email_enabled=True, email_send_on="failure_only", email_smtp_host="smtp.example.com",
                       email_from="ci@example.com", email_to=["team@example.com"])
        all_passed = [CaseResult(test_scenario="Search Flow", status="PASS")]
        sent = send_report_email(cfg, all_passed, tmp_path / "r.html", tmp_path / "s.xlsx",
                                  datetime.now(), "Smoke", "alice", {})
        assert sent is False

    def test_skips_when_smtp_config_incomplete(self, tmp_path):
        cfg = _config(email_enabled=True, email_smtp_host="", email_from="ci@example.com",
                       email_to=["team@example.com"])
        sent = send_report_email(cfg, _results(), tmp_path / "r.html", tmp_path / "s.xlsx",
                                  datetime.now(), "Smoke", "alice", {})
        assert sent is False

    @patch("core.notifier.smtplib.SMTP")
    def test_sends_with_attachments_and_ccs_failed_scenario_owner(self, mock_smtp_cls, tmp_path):
        report = tmp_path / "r.html"
        report.write_text("<html></html>", encoding="utf-8")
        summary = tmp_path / "s.xlsx"
        summary.write_bytes(b"fake-xlsx-bytes")

        cfg = _config(email_enabled=True, email_send_on="always", email_smtp_host="smtp.example.com",
                       email_smtp_port=587, email_smtp_user="ci@example.com", email_from="ci@example.com",
                       email_to=["team@example.com"], email_attach_report=True, email_attach_summary=True,
                       email_cc_owners_on_failure=True)
        owners = {"api to ui handoff": "api-module@example.com"}
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        sent = send_report_email(cfg, _results(), report, summary, datetime.now(), "Smoke", "alice", owners)

        assert sent is True
        mock_server.send_message.assert_called_once()
        _, kwargs = mock_server.send_message.call_args
        assert "api-module@example.com" in kwargs["to_addrs"]
        assert "team@example.com" in kwargs["to_addrs"]

    @patch("core.notifier.smtplib.SMTP")
    def test_returns_false_and_does_not_raise_on_smtp_failure(self, mock_smtp_cls, tmp_path):
        cfg = _config(email_enabled=True, email_send_on="always", email_smtp_host="smtp.example.com",
                       email_from="ci@example.com", email_to=["team@example.com"])
        mock_smtp_cls.side_effect = OSError("connection refused")

        sent = send_report_email(cfg, _results(), tmp_path / "r.html", tmp_path / "s.xlsx",
                                  datetime.now(), "Smoke", "alice", {})
        assert sent is False


class TestResolveExecutedBy:
    def test_prefers_github_actor(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTOR", "octocat")
        assert resolve_executed_by() == "octocat"

    def test_falls_back_to_jenkins_build_user(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTOR", raising=False)
        monkeypatch.setenv("BUILD_USER", "jenkins-user")
        assert resolve_executed_by() == "jenkins-user"

    def test_falls_back_to_os_user_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTOR", raising=False)
        monkeypatch.delenv("BUILD_USER", raising=False)
        monkeypatch.delenv("BUILD_USER_ID", raising=False)
        result = resolve_executed_by()
        assert isinstance(result, str) and result != ""
