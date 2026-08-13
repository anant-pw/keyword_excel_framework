"""
Loads config/config.yaml into a typed, dot-accessible object so the rest of
the framework never touches raw dict keys / risks a KeyError typo.
"""
from dataclasses import dataclass, field
from pathlib import Path
import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


@dataclass
class RunConfig:
    browser: str = "chromium"          # chromium | firefox | webkit
    headless: bool = True
    base_url: str = ""
    default_timeout_ms: int = 15000
    slow_mo_ms: int = 0
    suite: str = "Regression"          # Smoke | Sanity | Regression
    test_sheet_file: str = "testsheets/TestSuite.xlsx"
    sheet_name: str = "TestSteps"
    properties_dir: str = "properties"
    common_dir: str = "common"
    session_dir: str = "sessions"
    schema_dir: str = "schemas"       # JSON Schema "contract" files - see core/schema_validator.py
    report_dir: str = "reports"
    screenshot_on_failure: bool = True
    viewport_width: int = 1440
    viewport_height: int = 900
    history_limit: int = 10
    workers: int = 1
    env_variables: dict = field(default_factory=dict)


def load_config(path: Path = _CONFIG_PATH) -> RunConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return RunConfig(
        browser=raw.get("browser", "chromium"),
        headless=raw.get("headless", True),
        base_url=raw.get("base_url", ""),
        default_timeout_ms=raw.get("default_timeout_ms", 15000),
        slow_mo_ms=raw.get("slow_mo_ms", 0),
        suite=raw.get("suite", "Regression"),
        test_sheet_file=raw.get("test_sheet_file", "testsheets/TestSuite.xlsx"),
        sheet_name=raw.get("sheet_name", "TestSteps"),
        properties_dir=raw.get("properties_dir", "properties"),
        common_dir=raw.get("common_dir", "common"),
        session_dir=raw.get("session_dir", "sessions"),
        schema_dir=raw.get("schema_dir", "schemas"),
        report_dir=raw.get("report_dir", "reports"),
        screenshot_on_failure=raw.get("screenshot_on_failure", True),
        viewport_width=raw.get("viewport_width", 1440),
        viewport_height=raw.get("viewport_height", 900),
        history_limit=raw.get("history_limit", 10),
        workers=raw.get("workers", 1),
        env_variables=raw.get("env_variables", {}) or {},
    )
