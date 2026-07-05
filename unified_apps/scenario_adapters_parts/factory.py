"""Factory for scenario adapters."""

from __future__ import annotations

from .asko import AskoIntegratedAdapter
from .base import BaseScenarioAdapter, DataCallback, LogCallback, StateCallback
from .warta import WartaIntegratedAdapter


def build_adapter(
    scenario_key: str,
    settings: dict,
    log: LogCallback,
    state: StateCallback,
    data: DataCallback,
) -> BaseScenarioAdapter:
    if scenario_key == "warta_poland":
        return WartaIntegratedAdapter(settings, log, state, data)

    if scenario_key == "asko_kazakhstan":
        return AskoIntegratedAdapter(settings, log, state, data)

    raise ValueError(f"Неизвестный сценарий: {scenario_key}")