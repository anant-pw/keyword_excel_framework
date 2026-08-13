"""
Allure reporting adapter for the custom keyword-driven test runner.

The framework does not use pytest as its execution engine, so we generate
Allure 2 result JSON directly from CaseResult / StepResult objects.

The Jenkins Allure plugin consumes the files generated here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Iterable


def _timestamp_ms() -> int:
    import time
    return int(time.time() * 1000)


def _status(status: str) -> str:
    mapping = {
        "PASS": "passed",
        "FAIL": "failed",
        "SKIPPED": "skipped",
    }
    return mapping.get(status.upper(), "broken")


def _history_id(name: str) -> str:
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def _copy_attachment(
    source_path: str,
    results_dir: Path,
    prefix: str,
) -> tuple[str, str] | None:
    if not source_path:
        return None

    source = Path(source_path)

    if not source.exists() or not source.is_file():
        return None

    extension = source.suffix or ".bin"
    attachment_name = f"{prefix}-{uuid.uuid4().hex}{extension}"
    destination = results_dir / attachment_name

    shutil.copy2(source, destination)

    content_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".txt": "text/plain",
        ".log": "text/plain",
        ".json": "application/json",
    }.get(extension.lower(), "application/octet-stream")

    return attachment_name, content_type


def _step_to_allure(step, results_dir: Path, index: int) -> dict:
    start = _timestamp_ms()

    step_result = {
        "name": f"Row {step.row_id}: {step.keyword} - {step.description}",
        "status": _status(step.status),
        "stage": "finished",
        "start": start,
        "stop": start + max(step.duration_ms, 0),
        "steps": [],
        "attachments": [],
    }

    if step.message:
        step_result["statusDetails"] = {
            "message": step.message,
        }

    if step.saved:
        step_result["steps"].append({
            "name": step.saved,
            "status": "passed",
            "stage": "finished",
            "start": start,
            "stop": start,
        })

    # Composite keyword children
    for child_index, child in enumerate(step.children or []):
        step_result["steps"].append(
            _step_to_allure(
                child,
                results_dir,
                index * 1000 + child_index,
            )
        )

    # Failure screenshot
    attachment = _copy_attachment(
        step.screenshot_path,
        results_dir,
        f"row-{step.row_id}-failure",
    )

    if attachment:
        attachment_name, content_type = attachment
        step_result["attachments"].append({
            "name": "Failure Screenshot",
            "source": attachment_name,
            "type": content_type,
        })

    return step_result


def _case_to_allure(case_result, results_dir: Path, suite: str) -> None:
    result_uuid = str(uuid.uuid4())

    start = _timestamp_ms()
    stop = start + max(case_result.duration_ms, 0)

    test_name = case_result.test_scenario

    result = {
        "uuid": result_uuid,
        "historyId": _history_id(f"{suite}:{test_name}"),
        "name": test_name,
        "fullName": f"{suite}::{test_name}",
        "status": _status(case_result.status),
        "stage": "finished",
        "start": start,
        "stop": stop,
        "steps": [
            _step_to_allure(step, results_dir, index)
            for index, step in enumerate(case_result.step_results)
        ],
        "attachments": [],
        "labels": [
            {
                "name": "suite",
                "value": suite,
            },
            {
                "name": "framework",
                "value": "Keyword Framework",
            },
        ],
    }

    if case_result.status == "FAIL":
        failed_step = next(
            (
                step
                for step in case_result.step_results
                if step.status == "FAIL"
            ),
            None,
        )

        if failed_step and failed_step.message:
            result["statusDetails"] = {
                "message": failed_step.message,
            }

    output = results_dir / f"{result_uuid}-result.json"
    output.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )


def generate_allure_results(
    results: Iterable,
    report_dir: str | Path,
    suite: str,
) -> Path:
    """
    Convert the framework's CaseResult objects into Allure 2 result files.

    Existing results are intentionally NOT deleted. This is important because
    Jenkins runs each Excel sheet through a separate runner.py invocation.
    All invocations within the same Jenkins build therefore contribute to the
    same Allure report.
    """
    results_dir = Path(report_dir) / "allure-results"
    results_dir.mkdir(parents=True, exist_ok=True)

    for case_result in results:
        _case_to_allure(case_result, results_dir, suite)

    return results_dir