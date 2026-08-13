"""
Loads config/owners.yaml - a Test Scenario -> owner mapping kept
deliberately separate from testsheets/TestSuite.xlsx: who owns a module
changes far more often than the steps that test it, and putting it in the
Excel sheet would mean re-stamping the same owner value onto every row of
that scenario (easy to update inconsistently, no single source of truth).

Kept forgiving at load and lookup time - a missing file or an unmapped
Test Scenario is reported as a warning, never a hard failure, since
ownership is reporting/routing metadata, not test correctness. A typo in
owners.yaml should never be able to fail a green build.
"""
from pathlib import Path
import yaml

from core.logger import get_logger

logger = get_logger("owners_loader")


def load_owners(path: str) -> dict:
    """Returns {test_scenario_lowercased: owner}. A missing or empty file
    is valid - every scenario just resolves as unowned rather than
    raising, since this file is optional infrastructure, not a mandatory
    part of a run."""
    owners_path = Path(path)
    if not owners_path.exists():
        logger.warning(f"Owners file not found at {owners_path} - all scenarios will report as Unowned.")
        return {}
    raw = yaml.safe_load(owners_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("owners", {}) or {}
    return {str(scenario).strip().lower(): str(owner).strip() for scenario, owner in entries.items()}


def resolve_owner(owners: dict, test_scenario: str, warn: bool = True) -> str:
    """warn=False lets a caller that already reported the gap up front
    (see warn_unmapped_scenarios) look up owners repeatedly - e.g. once
    for the HTML report, again for the .xlsx summary, again for the
    email CC list - without logging the same miss three times per run."""
    owner = owners.get((test_scenario or "").strip().lower())
    if owner is None:
        if warn:
            logger.warning(f"No owner mapped for Test Scenario '{test_scenario}' - check config/owners.yaml")
        return "Unowned"
    return owner


def warn_unmapped_scenarios(owners: dict, test_scenarios) -> None:
    """One-shot upfront check: logs every scenario in this run that has no
    owner entry, all at once. Call this once near the start of a run's
    reporting step, then pass warn=False to resolve_owner() everywhere
    else that run."""
    unmapped = sorted({s for s in test_scenarios if (s or "").strip().lower() not in owners})
    if unmapped:
        logger.warning(f"{len(unmapped)} Test Scenario(s) have no owner mapped in config/owners.yaml: {unmapped}")
