"""Unified Bitrix deal router for insurance automation projects.

The app fetches a Bitrix deal, shows copied data, detects an automation scenario

(WARTA Poland, ASKO Kazakhstan, or a future registered scenario), and runs the
matching integrated adapter inside this application.

"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import requests


if __package__:
    from .scenario_adapters import BaseScenarioAdapter, build_adapter
else:
    from scenario_adapters import BaseScenarioAdapter, build_adapter

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT / "unified_apps" / "bitrix_policy_router.settings.json"

DEFAULT_SETTINGS = {
    "bitrix_webhook_url": "",

    "warta_url": "https://eagent.warta.pl",
    "warta_login": "",
    "warta_password": "",
    "asko_login": "",
    "asko_password": "",
    "asko_chrome_profile_dir": str(ROOT / "asko_bitrix_filler" / "chrome_profile_asko2"),
    "asko_payment_type": "Безналичным",
    "asko_payment_order": "Единовременно",
    "asko_notification_language": "Русский",
    "asko_client_form": "Физическое лицо",
    "asko_term_text": "15 дней",

}

BITRIX_FIELD_INSURANCE_COMPANY = "UF_CRM_1686683031442"
BITRIX_FIELD_INSURANCE_PRODUCT = "UF_CRM_1690539097"
BITRIX_FIELD_POLICY_COUNTRY = "UF_CRM_1700656576088"
BITRIX_FIELD_INSURANCE_TERM = "UF_CRM_1686152209741"

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
    BITRIX_FIELD_INSURANCE_TERM,
]


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str

    adapter_key: str

    keywords: tuple[str, ...]
    required_fields: dict[str, tuple[str, ...]]


SCENARIOS = [
    Scenario(
        key="warta_poland",
        title="WARTA — польское пограничное страхование",

        description="Выполняет интегрированную worker-логику WARTA для OC graniczne.",
        adapter_key="warta_poland",
        keywords=("warta", "poland", "polska", "поль", "oc graniczne"),
        required_fields={
            BITRIX_FIELD_INSURANCE_COMPANY: ("231", "TUiR WARTA S.A."),
            BITRIX_FIELD_INSURANCE_PRODUCT: ("425", "ОСГО ВТС нерезидента"),
        },
    ),
    Scenario(
        key="asko_kazakhstan",
        title="ASKO — казахское пограничное страхование",

        description="Выполняет интегрированную Selenium/Bitrix-логику ASKO.",
        adapter_key="asko_kazakhstan",
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


ASKO_TERM_BY_BITRIX_ID = {
    "585": "15 дней",
    "115": "1 месяц",
    "287": "2 месяца",
    "117": "3 месяца",
    "591": "4 месяца",
    "593": "5 месяцев",
    "119": "6 месяцев",
    "595": "7 месяцев",
    "597": "8 месяцев",
    "603": "9 месяцев",
    "599": "10 месяцев",
    "601": "11 месяцев",
    "121": "12 месяцев",
}

ASKO_TERM_BY_MONTHS = {
    1: "1 месяц",
    2: "2 месяца",
    3: "3 месяца",
    4: "4 месяца",
    5: "5 месяцев",
    6: "6 месяцев",
    7: "7 месяцев",
    8: "8 месяцев",
    9: "9 месяцев",
    10: "10 месяцев",
    11: "11 месяцев",
    12: "12 месяцев",
}


def resolve_asko_term_text(deal: dict, fallback: str = "15 дней") -> str:
    """Return ASKO period text from the Bitrix insurance term field."""
    raw_value = deal.get(BITRIX_FIELD_INSURANCE_TERM)
    text = normalize_bitrix_value(raw_value).strip()
    lowered = text.lower()

    if not text:
        return fallback

    if "605" in text or "другой срок" in lowered:
        raise ValueError("В Bitrix выбран 'Другой срок'. Для ASKO срок нужно указать вручную или в комментарии.")

    if text in ASKO_TERM_BY_BITRIX_ID:
        return ASKO_TERM_BY_BITRIX_ID[text]

    for bitrix_id, asko_text in ASKO_TERM_BY_BITRIX_ID.items():
        if re.search(rf"\b{re.escape(bitrix_id)}\b", text):
            return asko_text

    if "15" in lowered and ("дн" in lowered or "day" in lowered):
        return "15 дней"

    month_match = re.search(
        r"\b(1|2|3|4|5|6|7|8|9|10|11|12)\s*(месяц|месяца|месяцев|month|months)\b",
        lowered,
    )
    if month_match:
        months = int(month_match.group(1))
        return ASKO_TERM_BY_MONTHS.get(months, fallback)

    return fallback


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

        self.geometry("860x620")
        self.minsize(760, 520)
        self.parent = parent
        self.vars = {key: tk.StringVar(value=str(parent.settings.get(key, default))) for key, default in DEFAULT_SETTINGS.items()}
        self._build_ui()

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=16, pady=16)
        bitrix = ttk.Frame(notebook, padding=16)
        warta = ttk.Frame(notebook, padding=16)
        asko = ttk.Frame(notebook, padding=16)
        notebook.add(bitrix, text="Bitrix24")
        notebook.add(warta, text="WARTA")
        notebook.add(asko, text="ASKO")

        self._add_entry(bitrix, 0, "Bitrix24 webhook", "bitrix_webhook_url", secret=True)
        ttk.Label(bitrix, text="Webhook скрыт и не выводится в журнал.", foreground="#666666").grid(row=1, column=1, sticky="w", pady=(4, 0))

        ttk.Label(
            warta,
            text="Здесь меняются логин и пароль для входа в кабинет WARTA. Пароль скрыт и сохраняется только локально.",
            foreground="#666666",
            wraplength=640,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self._add_entry(warta, 1, "WARTA URL", "warta_url")
        self._add_entry(warta, 2, "WARTA login", "warta_login")
        self._add_entry(warta, 3, "WARTA password", "warta_password", secret=True)

        ttk.Label(
            asko,
            text="Здесь меняются логин и пароль для входа в ASKO. Если пароль изменился в страховой, обновите его тут и нажмите «Сохранить настройки».",
            foreground="#666666",
            wraplength=640,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self._add_entry(asko, 1, "ASKO login", "asko_login")
        self._add_entry(asko, 2, "ASKO password", "asko_password", secret=True)
        self._add_entry(asko, 3, "Chrome profile dir", "asko_chrome_profile_dir")
        self._add_entry(asko, 4, "Тип оплаты", "asko_payment_type")
        self._add_entry(asko, 5, "Порядок оплаты", "asko_payment_order")
        self._add_entry(asko, 6, "Язык уведомлений", "asko_notification_language")
        self._add_entry(asko, 7, "Форма клиента", "asko_client_form")
        self._add_entry(asko, 8, "Срок fallback, если в Bitrix пусто", "asko_term_text")

        for frame in (bitrix, warta, asko):
            frame.columnconfigure(1, weight=1)

        buttons = ttk.Frame(self, padding=(16, 0, 16, 16))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Сохранить настройки", command=self.save).pack(side="right", padx=(0, 8))

    def _add_entry(self, parent, row: int, label: str, key: str, secret: bool = False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=8)
        ttk.Entry(parent, textvariable=self.vars[key], show="*" if secret else "").grid(row=row, column=1, sticky="ew", pady=8)

    def save(self):
        for key, var in self.vars.items():
            self.parent.settings[key] = var.get().strip()

        save_settings(self.parent.settings)
        self.parent.set_status("Настройки сохранены. Логины и пароли страховых будут использованы при следующем запуске сценария.")
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
        self.adapter: BaseScenarioAdapter | None = None
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

            if self.adapter:
                self.adapter.shutdown()
                self.adapter = None
            adapter_settings = self.settings.copy()
            asko_term_text = ""
            if scenario and scenario.key == "asko_kazakhstan":
                asko_term_text = resolve_asko_term_text(
                    deal,
                    fallback=self.settings.get("asko_term_text", DEFAULT_SETTINGS["asko_term_text"]),
                )
                adapter_settings["asko_term_text"] = asko_term_text
                self.after(0, self.log, f"ASKO: период страхования из Bitrix — {asko_term_text}")

            if scenario:
                self.adapter = build_adapter(
                    scenario.adapter_key,
                    adapter_settings,
                    self.threadsafe_log,
                    self.threadsafe_state,
                    self.threadsafe_data,
                )
            preview = {
                "ID": deal.get("ID"),
                "TITLE": deal.get("TITLE"),
                "CATEGORY_ID": deal.get("CATEGORY_ID"),
                "STAGE_ID": deal.get("STAGE_ID"),
                "ASSIGNED_BY_ID": deal.get("ASSIGNED_BY_ID"),
                "detected_scenario": scenario.title if scenario else "Не определен автоматически",
                "asko_term_text": asko_term_text,
                "route_fields": {field: normalize_bitrix_value(deal.get(field)) for field in SCENARIO_HINT_FIELDS},
            }
            self.after(0, self._show_deal, preview)

            if scenario and self.adapter:
                self.after(0, self.set_status, f"Сценарий выбран: {scenario.title}. Запускаю первый шаг в новом приложении.")
                self.adapter.start(deal_id)

            else:
                self.after(0, self.set_status, "Сценарий не определен. Добавьте ключевые слова/поля маршрутизации для этой страховой.")
        except Exception as exc:
            self.after(0, self.set_status, f"Не удалось получить сделку. Проверьте ID, webhook и интернет. Детали: {exc}")

    def _show_deal(self, preview: dict):
        self.data_text.delete("1.0", "end")
        self.data_text.insert("end", json.dumps(preview, ensure_ascii=False, indent=2))

    def next_step(self):
        if not self.adapter or not self.selected_scenario:
            messagebox.showwarning("Сценарий не выбран", "Сначала нажмите «Начать» и получите сделку Bitrix24.")
            return
        self.adapter.next_step()

    def new_policy(self):
        if not self.adapter or not self.selected_scenario:
            self.set_status("Новый полис: сначала загрузите сделку, чтобы выбрать WARTA, ASKO или будущий сценарий.")
            return
        self.adapter.new_policy()

    def reset_scenario(self):
        if self.adapter:
            self.adapter.reset()
            self.adapter.shutdown()
        self.adapter = None
        self.selected_scenario = None
        self.deal = None
        self.data_text.delete("1.0", "end")
        self.set_status("Сценарий сброшен. Можно вставить новую сделку Bitrix24.")

    def threadsafe_log(self, text: str):
        self.after(0, self.log, text)

    def threadsafe_state(self, text: str):
        self.after(0, self.set_status, text)

    def threadsafe_data(self, data: dict):
        self.after(0, self._show_deal, data)

    def on_close(self):
        if self.adapter:
            self.adapter.shutdown()
        self.destroy()

if __name__ == "__main__":
    app = RouterApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()

