"""Unified Bitrix deal router for insurance automation projects.

The app fetches a Bitrix deal, shows copied data, detects an automation scenario
(WARTA Poland, ASKO Kazakhstan, or a future registered scenario), and launches the
matching raw project entry point as the first integration layer.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import requests

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT / "unified_apps" / "bitrix_policy_router.settings.json"

DEFAULT_SETTINGS = {
    "bitrix_webhook_url": "",
    "python_executable": sys.executable,
}

BITRIX_FIELD_INSURANCE_COMPANY = "UF_CRM_1686683031442"
BITRIX_FIELD_INSURANCE_PRODUCT = "UF_CRM_1690539097"
BITRIX_FIELD_POLICY_COUNTRY = "UF_CRM_1700656576088"

SCENARIO_HINT_FIELDS = [
    "TITLE",
    "CATEGORY_ID",
    "STAGE_ID",
    "COMMENTS",
    "UF_CRM_1686152306664",
    "UF_CRM_1686152515152",
    BITRIX_FIELD_INSURANCE_COMPANY,
    BITRIX_FIELD_INSURANCE_PRODUCT,
    BITRIX_FIELD_POLICY_COUNTRY,
]


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    command: list[str]
    keywords: tuple[str, ...]
    required_fields: dict[str, tuple[str, ...]]


SCENARIOS = [
    Scenario(
        key="warta_poland",
        title="WARTA — польское пограничное страхование",
        description="Запускает текущий GUI WARTA Robot App v2 для OC graniczne.",
        command=["warta_robot_app_v2/app.py"],
        keywords=("warta", "poland", "polska", "поль", "oc graniczne"),
        required_fields={
            BITRIX_FIELD_INSURANCE_COMPANY: ("231", "TUiR WARTA S.A."),
            BITRIX_FIELD_INSURANCE_PRODUCT: ("425", "ОСГО ВТС нерезидента"),
        },
    ),
    Scenario(
        key="asko_kazakhstan",
        title="ASKO — казахское пограничное страхование",
        description="Запускает текущий ASKO ← Bitrix24 filler.",
        command=["asko_bitrix_filler/asko_bitrix_filler.py"],
        keywords=("asko", "kazakhstan", "казах", "kz", "огпо"),
        required_fields={
            BITRIX_FIELD_INSURANCE_COMPANY: ("1091", "АО «Страховая Компания «АСКО»", "АСКО"),
            BITRIX_FIELD_INSURANCE_PRODUCT: ("425", "ОСГО ВТС нерезидента"),
            BITRIX_FIELD_POLICY_COUNTRY: ("1101", "КАЗАХСТАН"),
        },
    ),
]


def load_settings() -> dict:
    data = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return data


def save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_deal_id(text: str) -> str:
    value = (text or "").strip()
    match = re.search(r"/crm/deal/details/(\d+)/?", value)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{2,})\b", value)
    if match:
        return match.group(1)
    raise ValueError("Введите ID сделки Bitrix или ссылку вида /crm/deal/details/80519/.")


def bitrix_call(webhook_url: str, method: str, params: dict | None = None) -> dict:
    webhook_url = (webhook_url or "").strip().rstrip("/")
    if not webhook_url:
        raise ValueError("В настройках не указан Bitrix24 webhook.")
    response = requests.post(f"{webhook_url}/{method}.json", json=params or {}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(f"Bitrix24: {payload.get('error')} — {payload.get('error_description')}")
    return payload.get("result") or {}


def normalize_bitrix_value(value) -> str:
    """Return searchable text for Bitrix enum values returned as IDs, dicts or lists."""
    if value is None:
        return ""
    if isinstance(value, dict):
        parts = []
        for key in ("ID", "VALUE", "id", "value"):
            if value.get(key) is not None:
                parts.append(str(value[key]))
        return " ".join(parts)
    if isinstance(value, list):
        return " ".join(normalize_bitrix_value(item) for item in value)
    return str(value)


def field_matches(deal: dict, field_name: str, expected_values: tuple[str, ...]) -> bool:
    actual = normalize_bitrix_value(deal.get(field_name)).lower()
    return any(str(expected).lower() in actual for expected in expected_values)


def detect_scenario(deal: dict) -> Scenario | None:
    for scenario in SCENARIOS:
        if scenario.required_fields and all(
            field_matches(deal, field_name, expected_values)
            for field_name, expected_values in scenario.required_fields.items()
        ):
            return scenario

    text = " ".join(normalize_bitrix_value(deal.get(field, "")) for field in SCENARIO_HINT_FIELDS).lower()
    for scenario in SCENARIOS:
        if any(keyword in text for keyword in scenario.keywords):
            return scenario
    return None


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: "RouterApp"):
        super().__init__(parent)
        self.title("Настройки")
        self.resizable(False, False)
        self.parent = parent
        self.webhook = tk.StringVar(value=parent.settings.get("bitrix_webhook_url", ""))
        self.python = tk.StringVar(value=parent.settings.get("python_executable", sys.executable))
        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Bitrix24 webhook").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(frame, textvariable=self.webhook, width=84, show="*").grid(row=1, column=0, sticky="ew")
        ttk.Label(frame, text="Python executable для запуска старых проектов").grid(row=2, column=0, sticky="w", pady=(14, 6))
        ttk.Entry(frame, textvariable=self.python, width=84).grid(row=3, column=0, sticky="ew")
        ttk.Label(frame, text="Секреты не выводятся в журнал. Webhook хранится локально в JSON.", foreground="#666666").grid(row=4, column=0, sticky="w", pady=(12, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Сохранить настройки", command=self.save).pack(side="right", padx=(0, 8))

    def save(self):
        self.parent.settings["bitrix_webhook_url"] = self.webhook.get().strip()
        self.parent.settings["python_executable"] = self.python.get().strip() or sys.executable
        save_settings(self.parent.settings)
        self.parent.set_status("Настройки сохранены.")
        self.destroy()


class RouterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bitrix Policy Automation Hub")
        self.geometry("1100x760")
        self.minsize(960, 660)
        self.settings = load_settings()
        self.deal_input = tk.StringVar()
        self.status = tk.StringVar(value="Готово. Вставьте ID сделки Bitrix и нажмите «Начать».")
        self.selected_scenario: Scenario | None = None
        self.deal: dict | None = None
        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Центр запуска страховых роботов", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text="Получает сделку Bitrix24, показывает данные и выбирает сценарий WARTA / ASKO / будущие интеграции.").pack(anchor="w", pady=(4, 16))

        entry_card = ttk.LabelFrame(root, text="Сделка Bitrix24")
        entry_card.pack(fill="x")
        row = ttk.Frame(entry_card, padding=12)
        row.pack(fill="x")
        ttk.Label(row, text="ID DEAL BITRIX или ссылка").pack(side="left")
        entry = ttk.Entry(row, textvariable=self.deal_input, width=46)
        entry.pack(side="left", padx=(10, 8), fill="x", expand=True)
        entry.bind("<Control-v>", lambda event: None)
        ttk.Button(row, text="Начать", command=self.start).pack(side="left")
        ttk.Button(row, text="Далее", command=self.next_step).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Новый полис", command=self.new_policy).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Сбросить сценарий", command=self.reset_scenario).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Настройки", command=lambda: SettingsWindow(self)).pack(side="left", padx=(8, 0))

        status_card = ttk.LabelFrame(root, text="Ход работы")
        status_card.pack(fill="x", pady=(16, 0))
        ttk.Label(status_card, textvariable=self.status, wraplength=1000).pack(anchor="w", padx=12, pady=10)

        panes = ttk.PanedWindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(16, 0))
        data_card = ttk.LabelFrame(panes, text="Вводимые данные из Bitrix24")
        log_card = ttk.LabelFrame(panes, text="Журнал")
        panes.add(data_card, weight=2)
        panes.add(log_card, weight=1)
        self.data_text = scrolledtext.ScrolledText(data_card, wrap="word", font=("Consolas", 10), undo=True)
        self.data_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text = scrolledtext.ScrolledText(log_card, wrap="word", font=("Consolas", 10), undo=True)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("Текст в полях можно выделить и скопировать. Ctrl+V в поле сделки работает стандартно.")

    def log(self, text: str):
        self.log_text.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log_text.see("end")

    def set_status(self, text: str):
        self.status.set(text)
        self.log(text)

    def start(self):
        threading.Thread(target=self._load_deal, daemon=True).start()

    def _load_deal(self):
        try:
            deal_id = extract_deal_id(self.deal_input.get())
            self.after(0, self.set_status, f"Загружаю сделку Bitrix24 ID {deal_id}...")
            deal = bitrix_call(self.settings.get("bitrix_webhook_url", ""), "crm.deal.get", {"id": deal_id})
            scenario = detect_scenario(deal)
            self.deal = deal
            self.selected_scenario = scenario
            preview = {
                "ID": deal.get("ID"),
                "TITLE": deal.get("TITLE"),
                "CATEGORY_ID": deal.get("CATEGORY_ID"),
                "STAGE_ID": deal.get("STAGE_ID"),
                "ASSIGNED_BY_ID": deal.get("ASSIGNED_BY_ID"),
                "detected_scenario": scenario.title if scenario else "Не определен автоматически",
                "route_fields": {field: normalize_bitrix_value(deal.get(field)) for field in SCENARIO_HINT_FIELDS},
            }
            self.after(0, self._show_deal, preview)
            if scenario:
                self.after(0, self.set_status, f"Сценарий выбран: {scenario.title}. Нажмите «Далее», чтобы запустить текущий модуль.")
            else:
                self.after(0, self.set_status, "Сценарий не определен. Добавьте ключевые слова/поля маршрутизации для этой страховой.")
        except Exception as exc:
            self.after(0, self.set_status, f"Не удалось получить сделку. Проверьте ID, webhook и интернет. Детали: {exc}")

    def _show_deal(self, preview: dict):
        self.data_text.delete("1.0", "end")
        self.data_text.insert("end", json.dumps(preview, ensure_ascii=False, indent=2))

    def next_step(self):
        if not self.selected_scenario:
            messagebox.showwarning("Сценарий не выбран", "Сначала нажмите «Начать» и получите сделку Bitrix24.")
            return
        self._launch_scenario(self.selected_scenario)

    def new_policy(self):
        if self.selected_scenario:
            self._launch_scenario(self.selected_scenario)
        else:
            self.set_status("Новый полис: сначала загрузите сделку, чтобы выбрать WARTA, ASKO или будущий сценарий.")

    def reset_scenario(self):
        self.selected_scenario = None
        self.deal = None
        self.data_text.delete("1.0", "end")
        self.set_status("Сценарий сброшен. Можно вставить новую сделку Bitrix24.")

    def _launch_scenario(self, scenario: Scenario):
        try:
            python = self.settings.get("python_executable") or sys.executable
            script = ROOT / scenario.command[0]
            if not script.exists():
                raise FileNotFoundError(script)
            subprocess.Popen([python, str(script)], cwd=str(script.parent))
            self.set_status(f"Запущен модуль: {scenario.title}. Сделку можно скопировать из поля данных.")
        except Exception as exc:
            self.set_status(f"Не удалось запустить {scenario.title}. Детали: {exc}")


if __name__ == "__main__":
    RouterApp().mainloop()
