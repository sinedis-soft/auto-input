"""WARTA integrated scenario adapter."""

from __future__ import annotations

import sys
from pathlib import Path

from .base import BaseScenarioAdapter, DataCallback, LogCallback, StateCallback

ROOT = Path(__file__).resolve().parents[2]


class WartaIntegratedAdapter(BaseScenarioAdapter):
    """Adapter around WARTA worker logic without opening the old WARTA GUI."""

    def __init__(self, settings: dict, log: LogCallback, state: StateCallback, data: DataCallback):
        super().__init__(settings, log, state, data)
        self.worker = None
        self._ensure_import_path()

    def _ensure_import_path(self) -> None:
        path = str(ROOT / "warta_robot_app_v2")
        if path not in sys.path:
            sys.path.insert(0, path)

    def _ensure_worker(self):
        if self.worker is None:
            from warta_worker import WartaWorker

            self.worker = WartaWorker(log_callback=self.log, state_callback=self.state)
            self.worker.start()
        return self.worker

    def _warta_settings(self) -> dict:
        return {
            "warta_url": self.settings.get("warta_url", ""),
            "warta_login": self.settings.get("warta_login", ""),
            "warta_password": self.settings.get("warta_password", ""),
            "bitrix_webhook_url": self.settings.get("bitrix_webhook_url", ""),
        }

    def start(self, deal_id: str) -> None:
        super().start(deal_id)
        self.state("WARTA: запускаю первый шаг в новом приложении...")
        self.next_step()

    def next_step(self) -> None:
        if not self.deal_id:
            raise ValueError("Сначала загрузите сделку Bitrix24.")

        self._ensure_worker().submit(
            "start_or_continue",
            {
                "settings": self._warta_settings(),
                "deal_url": f"/crm/deal/details/{self.deal_id}/",
            },
        )

    def reset(self) -> None:
        if self.worker:
            self.worker.submit("reset", {})
        super().reset()

    def shutdown(self) -> None:
        if self.worker:
            self.worker.submit("shutdown", {})
            self.worker = None


