from __future__ import annotations

import json
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from ..bitrix_policy_router_app import bitrix_call, detect_scenario, extract_deal_id, normalize_bitrix_value, resolve_asko_term_text, SCENARIO_HINT_FIELDS
from ..scenario_adapters import BaseScenarioAdapter, build_adapter
from ..services.log_service import LogService
from ..services.settings_service import DEFAULT_SETTINGS, SETTINGS_FILE, load_settings, save_settings
from .asko_page import AskoPage
from .deal_page import DealPage
from .log_page import LogPage
from .settings_page import SettingsPage
from .warta_page import WartaPage

class WorkerSignals(QObject):
    result = Signal(object); error = Signal(str)


class UiBridge(QObject):
    """Thread-safe bridge from scenario adapter callbacks to Qt UI slots."""

    log_signal = Signal(str)
    state_signal = Signal(str)
    data_signal = Signal(dict)


class Runnable(QRunnable):
    def __init__(self, fn: Callable[[], object]): super().__init__(); self.fn = fn; self.signals = WorkerSignals()
    @Slot()
    def run(self):
        try: self.signals.result.emit(self.fn())
        except Exception as exc: self.signals.error.emit(f"{exc}\n{traceback.format_exc()}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Bitrix Policy Automation Hub — PySide6"); self.resize(1220, 820); self.setMinimumSize(980, 680)
        self.settings = load_settings(); self.log_service = LogService(); self.pool = QThreadPool.globalInstance(); self.adapter: BaseScenarioAdapter | None = None; self.asko_adapter: BaseScenarioAdapter | None = None; self.selected_scenario = None; self.deal = None; self.deal_id = ""; self.current_deal_id = ""; self.current_scenario_key = ""; self.current_adapter_settings: dict = {}
        self.ui_bridge = UiBridge(self)
        self._build_ui(); self._connect(); self.settings_page.set_values(self.settings); self.add_log("Новый PySide6 UI запущен. Старый Tkinter UI оставлен как fallback.")

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root); outer = QVBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        self.top_status = QLabel("Готово. Введите ID сделки или ссылку Bitrix24."); self.top_status.setObjectName("TopStatus"); outer.addWidget(self.top_status)
        splitter = QSplitter(Qt.Vertical); outer.addWidget(splitter, 1)
        main = QWidget(); main_layout = QHBoxLayout(main); main_layout.setContentsMargins(0,0,0,0); main_layout.setSpacing(0)
        self.menu = QListWidget(); self.menu.setObjectName("SideMenu"); self.menu.setFixedWidth(190)
        for title in ["Сделка", "ASKO", "WARTA", "Журнал", "Настройки"]: self.menu.addItem(QListWidgetItem(title))
        self.stack = QStackedWidget(); self.deal_page = DealPage(); self.asko_page = AskoPage(); self.warta_page = WartaPage(); self.log_page = LogPage(); self.settings_page = SettingsPage()
        for page in [self.deal_page, self.asko_page, self.warta_page, self.log_page, self.settings_page]: self.stack.addWidget(page)
        main_layout.addWidget(self.menu); main_layout.addWidget(self.stack, 1); splitter.addWidget(main)
        self.bottom_log = QPlainTextEdit(); self.bottom_log.setReadOnly(True); self.bottom_log.setMaximumBlockCount(500); self.bottom_log.setObjectName("BottomLog"); splitter.addWidget(self.bottom_log); splitter.setSizes([610, 190]); self.menu.setCurrentRow(0)

    def _connect(self):
        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex); self.deal_page.load_requested.connect(self.load_deal)
        self.asko_page.next_requested.connect(self.asko_next_step); self.asko_page.new_policy_requested.connect(self.new_policy); self.asko_page.reset_requested.connect(self.reset_scenario); self.asko_page.close_chrome_requested.connect(self.close_adapter)
        self.warta_page.next_requested.connect(self.next_step); self.warta_page.reset_requested.connect(self.reset_scenario); self.warta_page.close_worker_requested.connect(self.close_adapter)
        self.log_page.clear_requested.connect(self.clear_log); self.log_page.copy_requested.connect(self.copy_log); self.log_page.filter_changed.connect(lambda _v: self.refresh_logs())
        self.settings_page.save_requested.connect(self.save_settings_from_ui)
        self.ui_bridge.log_signal.connect(self.on_adapter_log)
        self.ui_bridge.state_signal.connect(self.on_adapter_state)
        self.ui_bridge.data_signal.connect(self.on_adapter_data)

    def add_log(self, message: str, level: str = "info"):
        rec = self.log_service.add(message, level); self.bottom_log.appendPlainText(rec.format()); self.refresh_logs()

    def refresh_logs(self): self.log_page.set_text(self.log_service.formatted(self.log_page.current_filter()))
    def clear_log(self): self.log_service.clear(); self.bottom_log.clear(); self.refresh_logs()
    def copy_log(self): QGuiApplication.clipboard().setText(self.log_service.formatted(self.log_page.current_filter()))

    def set_status(self, text: str):
        self.top_status.setText(text); self.add_log(text); self.asko_page.set_status(text); self.warta_page.set_status(text)

    def load_deal(self, raw: str):
        self.settings = load_settings(); self.settings_page.set_values(self.settings)
        def work():
            deal_id = extract_deal_id(raw); deal = bitrix_call(self.settings.get("bitrix_webhook_url", ""), "crm.deal.get", {"id": deal_id}); scenario = detect_scenario(deal); asko_term_text = ""
            adapter_settings = self.settings.copy()
            if scenario and scenario.key == "asko_kazakhstan":
                asko_term_text = resolve_asko_term_text(deal, fallback=self.settings.get("asko_term_text", DEFAULT_SETTINGS["asko_term_text"])); adapter_settings["asko_term_text"] = asko_term_text
            return deal_id, deal, scenario, adapter_settings, asko_term_text
        self.set_status("Загружаю сделку Bitrix24..."); runner = Runnable(work); runner.signals.result.connect(self._deal_loaded); runner.signals.error.connect(lambda e: self._error("Не удалось загрузить сделку", e)); self.pool.start(runner)

    def _deal_loaded(self, result):
        deal_id, deal, scenario, adapter_settings, asko_term_text = result; self.deal_id = deal_id; self.current_deal_id = str(deal_id); self.deal = deal; self.selected_scenario = scenario
        self.current_scenario_key = scenario.adapter_key if scenario else "asko_kazakhstan"
        self.current_adapter_settings = adapter_settings
        if self.adapter: self.adapter.shutdown(); self.adapter = None
        self.asko_adapter = None
        if scenario: self.adapter = build_adapter(scenario.adapter_key, adapter_settings, self.ui_bridge.log_signal.emit, self.ui_bridge.state_signal.emit, self.ui_bridge.data_signal.emit)
        if scenario and scenario.adapter_key == "asko_kazakhstan": self.asko_adapter = self.adapter
        preview = self._preview(deal, scenario, asko_term_text); self.deal_page.set_preview(preview)
        self.set_status(f"Сделка {deal_id} загружена. Сценарий: {preview['scenario']}.")

    def _build_scenario_adapter(self, adapter_key: str) -> BaseScenarioAdapter:
        return build_adapter(
            adapter_key,
            self.current_adapter_settings or self.settings.copy(),
            self.ui_bridge.log_signal.emit,
            self.ui_bridge.state_signal.emit,
            self.ui_bridge.data_signal.emit,
        )

    def asko_next_step(self):
        if not self.current_deal_id:
            QMessageBox.warning(self, "Сделка не загружена", "Сначала загрузите сделку Bitrix24.")
            return

        if self.current_scenario_key and self.current_scenario_key != "asko_kazakhstan":
            self.add_log(
                f"ASKO: текущая сделка определена как {self.current_scenario_key}; запуск ASKO отменен.",
                "warning",
            )
            QMessageBox.warning(self, "Не ASKO сценарий", "Текущая сделка не определена как ASKO.")
            return

        adapter_needs_start = (
            self.asko_adapter is None
            or str(getattr(self.asko_adapter, "deal_id", "") or "") != self.current_deal_id
        )

        if adapter_needs_start:
            if self.asko_adapter:
                self.asko_adapter.shutdown()
            self.asko_adapter = self._build_scenario_adapter("asko_kazakhstan")
            self.adapter = self.asko_adapter
            self.add_log(f"ASKO: запускаю сценарий для сделки {self.current_deal_id}")
            self.asko_adapter.start(self.current_deal_id)
            return

        if not str(getattr(self.asko_adapter, "deal_id", "") or ""):
            self.add_log("ASKO: deal_id пустой, next_step не будет вызван.", "error")
            return

        self.add_log(f"ASKO: запускаю сценарий для сделки {self.current_deal_id}")
        self._run_adapter("ASKO Далее", lambda: self.asko_adapter.next_step())

    def _preview(self, deal: dict, scenario, term: str) -> dict:
        route = {field: normalize_bitrix_value(deal.get(field)) for field in SCENARIO_HINT_FIELDS}
        return {"deal_id": deal.get("ID") or self.deal_id, "scenario": scenario.title if scenario else "Не определен", "company": normalize_bitrix_value(deal.get("COMPANY_ID") or deal.get("COMPANY_TITLE") or route.get("UF_CRM_1686683031442")), "phone_source": "Будет уточнен адаптером ASKO через crm.company.get", "phone": normalize_bitrix_value(deal.get("PHONE")), "email": normalize_bitrix_value(deal.get("EMAIL")), "policy_number": normalize_bitrix_value(deal.get("UF_CRM_1686152306664")), "reg_number": normalize_bitrix_value(deal.get("UF_CRM_1686152515152")), "vin": normalize_bitrix_value(deal.get("UF_CRM_1686152604940")), "start_date": normalize_bitrix_value(deal.get("BEGINDATE")), "term": term or normalize_bitrix_value(deal.get("UF_CRM_1686152209741")), "asko_company_id": normalize_bitrix_value(deal.get("UF_CRM_1705057253559")), "premium": normalize_bitrix_value(deal.get("OPPORTUNITY")), "currency": normalize_bitrix_value(deal.get("CURRENCY_ID"))}

    def _run_adapter(self, action: str, fn: Callable[[], None]):
        if not self.adapter: QMessageBox.warning(self, "Сценарий не выбран", "Сначала загрузите сделку Bitrix24."); return
        runner = Runnable(lambda: fn()); runner.signals.error.connect(lambda e: self._error(f"Ошибка действия {action}", e)); self.pool.start(runner)
    def next_step(self): self._run_adapter("Далее", lambda: self.adapter.next_step())
    def new_policy(self): self._run_adapter("Новый полис", lambda: self.adapter.new_policy())
    def reset_scenario(self):
        if self.adapter: self.adapter.reset(); self.adapter.shutdown(); self.adapter = None
        self.selected_scenario = None; self.deal = None; self.current_deal_id = ""; self.current_scenario_key = ""; self.current_adapter_settings = {}; self.asko_adapter = None; self.deal_page.set_preview({}); self.set_status("Сценарий сброшен.")
    def close_adapter(self):
        if self.adapter: self.adapter.shutdown(); self.set_status("Фоновый worker/Chrome закрыт.")
    def save_settings_from_ui(self, values: dict): self.settings.update(values); save_settings(self.settings); self.set_status(f"Настройки сохранены: {SETTINGS_FILE}")
    @Slot(str)
    def on_adapter_log(self, text: str): self.add_log(text)
    @Slot(str)
    def on_adapter_state(self, text: str): self.set_status(text)
    @Slot(dict)
    def on_adapter_data(self, data: dict): self.add_log("Получены данные сценария."); self.deal_page.set_preview({**self._preview(self.deal or {}, self.selected_scenario, self.settings.get('asko_term_text', '')), **self._flatten_data(data)})
    def _flatten_data(self, data: dict) -> dict:
        if not data: return {}
        return {"phone": data.get("phone", ""), "email": data.get("email", ""), "policy_number": data.get("policy_number", ""), "reg_number": data.get("reg_number", ""), "vin": data.get("vin", ""), "start_date": data.get("start_date", ""), "asko_company_id": data.get("asko_company_id", "")}
    def _error(self, title: str, details: str): self.add_log(f"{title}: {details.splitlines()[0]}", "error"); self.top_status.setText(f"{title}: {details.splitlines()[0]}")
    def closeEvent(self, event):
        if self.adapter: self.adapter.shutdown()
        event.accept()
