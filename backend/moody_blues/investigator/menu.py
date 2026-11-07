"""A fixed list of validated experiments that the Investigator chooses from.

The benchmark compares ways of choosing tests, so every strategy has to choose from the same
list. With a menu the model picks a candidate instead of writing a program, and trusted code runs
the same probe program any other strategy would run for that candidate.

Everything the model reads here is neutral. Scenario ids can name their conditions, so a menu shows
an alias for each one, and aliases are applied only to what is shown: records keep the real ids.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, JsonValue

from moody_blues.contracts.investigation import InvestigationObservation, RunFacts, WorldCard


class MenuItem(BaseModel):
    """One candidate as the model sees it. No scenario id and no expected outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    world_ref: str
    faults: list[dict[str, JsonValue]]


@dataclass(frozen=True, slots=True)
class ExperimentMenu:
    items: tuple[MenuItem, ...]
    programs: Mapping[str, str]  # candidate id -> trusted program
    aliases: Mapping[str, str]  # scenario id -> what the model calls it
    labels: Mapping[str, str] = field(default_factory=dict[str, str])  # candidate id -> stable key

    def __post_init__(self) -> None:
        ids = [item.candidate_id for item in self.items]
        if len(set(ids)) != len(ids) or set(ids) != set(self.programs):
            raise ValueError("a menu needs one program for each distinct candidate")

    def program(self, candidate_id: str) -> str | None:
        return self.programs.get(candidate_id)

    def shown(self, ran: Sequence[str]) -> list[dict[str, JsonValue]]:
        return [
            item.model_dump(mode="json") | {"already_run": item.candidate_id in ran}
            for item in self.items
        ]

    def alias_cards(self, cards: Sequence[WorldCard]) -> list[WorldCard]:
        return [c.model_copy(update={"world_id": self.aliases[c.world_id]}) for c in cards]

    def alias_observation(self, observation: InvestigationObservation) -> InvestigationObservation:
        runs: list[RunFacts] = [
            r.model_copy(update={"world_ref": self.aliases.get(r.world_ref, "world")})
            for r in observation.runs
        ]
        return observation.model_copy(update={"runs": runs})
