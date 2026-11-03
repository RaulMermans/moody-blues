"""Versioned scenario definitions (JSON) and their loader.

Scenario files describe worlds only. They contain no expected verdicts.
"""

from __future__ import annotations

from pathlib import Path

from moody_blues.contracts.scenario import Scenario

SCENARIO_DIR = Path(__file__).resolve().parent


class UnknownScenarioError(LookupError):
    pass


def scenario_ids() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


def load_scenario_file(path: Path) -> Scenario:
    scenario = Scenario.model_validate_json(path.read_text(encoding="utf-8"))
    if scenario.scenario_id != path.stem:
        raise ValueError(f"{path.name}: scenario_id {scenario.scenario_id!r} != file name")
    return scenario


def load_scenario(scenario_id: str) -> Scenario:
    if scenario_id not in scenario_ids():
        raise UnknownScenarioError(
            f"unknown scenario {scenario_id!r}; known: {', '.join(scenario_ids())}"
        )
    return load_scenario_file(SCENARIO_DIR / f"{scenario_id}.json")
