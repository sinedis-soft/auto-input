"""Common types and base class for scenario adapters."""

from __future__ import annotations

from typing import Callable

LogCallback = Callable[[str], None]
StateCallback = Callable[[str], None]
DataCallback = Callable[[dict], None]


class BaseScenarioAdapter:
    def __init__(self, settings: dict, log: LogCallback, state: StateCallback, data: DataCallback):
        self.settings = settings
        self.log = log
        self.state = state
        self.data = data
        self.deal_id = ""

    def start(self, deal_id: str) -> None:
        self.deal_id = deal_id

    def next_step(self) -> None:
        raise NotImplementedError

    def new_policy(self) -> None:
        self.start(self.deal_id)

    def reset(self) -> None:
        self.state("Сценарий сброшен.")

    def shutdown(self) -> None:
        pass


