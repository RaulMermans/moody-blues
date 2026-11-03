"""Shared helpers for World Engine tests. Every world here is a real SQLite file."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from moody_blues.contracts.scenario import FaultSpec, Scenario
from moody_blues.contracts.world import ToolName, ToolResponse
from moody_blues.world.engine import World

ADA: dict[str, JsonValue] = {
    "name": "Ada Lovelace",
    "email": "ada@analytical.example",
    "metadata": {"tier": "platinum"},
}


def make_scenario(
    *, faults: list[dict[str, Any]] | None = None, seeds: bool = True, **overrides: Any
) -> Scenario:
    body: dict[str, Any] = {
        "scenario_id": "test-world",
        "version": "1.0.0",
        "title": "test world",
        "seed": 7,
        "initial_state": {
            "customers": [
                {
                    "customer_id": "cus_seed_grace",
                    "name": "Grace Hopper",
                    "email": "grace@navy.example",
                    "metadata": {"tier": "gold"},
                },
                {
                    "customer_id": "cus_seed_alan",
                    "name": "Alan Turing",
                    "email": "alan@bletchley.example",
                    "client_request_id": "seed-req-alan-0001",
                },
            ]
            if seeds
            else []
        },
        "objective": {"customer": ADA},
        "faults": [FaultSpec.model_validate(f).model_dump(mode="json") for f in faults or []],
    }
    return Scenario.model_validate(body | overrides)


def snapshot(world: World) -> list[dict[str, Any]]:
    with world.view() as view:
        return [c.model_dump(mode="json") for c in view.all_customers()]


def customer_id(response: ToolResponse) -> str:
    assert response.ok, response
    assert response.data is not None
    customer = response.data["customer"]
    assert isinstance(customer, dict)
    cid = customer["customer_id"]
    assert isinstance(cid, str)
    return cid


def create(world: World, **overrides: JsonValue) -> ToolResponse:
    return world.gateway.call(ToolName.CREATE_CUSTOMER, ADA | overrides)


def raw_connection(world: World) -> sqlite3.Connection:
    """An *untrusted-style* raw handle used only to simulate tampering in tests."""
    conn = sqlite3.connect(world.db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def payload(row: sqlite3.Row) -> dict[str, Any]:
    return json.loads(row["payload"])


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    with World(make_scenario(), root_dir=tmp_path) as w:
        yield w


@pytest.fixture
def world_factory(tmp_path: Path) -> Iterator[Any]:
    created: list[World] = []

    def factory(scenario: Scenario | None = None) -> World:
        w = World(scenario or make_scenario(), root_dir=tmp_path)
        created.append(w)
        return w

    yield factory
    for w in created:
        if w.directory.exists():
            w.close()
