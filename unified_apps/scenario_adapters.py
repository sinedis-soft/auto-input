"""Integrated automation adapters used by the unified Bitrix router.

The adapters intentionally reuse automation logic from the older raw projects, but they
are controlled by the new unified UI instead of launching the old GUI windows.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

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


class AskoIntegratedAdapter(BaseScenarioAdapter):
    """Selenium ASKO scenario adapted from asko_bitrix_filler without its old GUI."""

    def __init__(self, settings: dict, log: LogCallback, state: StateCallback, data: DataCallback):
        super().__init__(settings, log, state, data)
        self.driver = None
        self.deal = None
        self.stage = "idle"
        self._module = None

    def _load_module(self):
        if self._module is None:
            path = str(ROOT / "asko_bitrix_filler")
            if path not in sys.path:
                sys.path.insert(0, path)
            import asko_bitrix_filler as module

            self._module = module
        return self._module

    def _run_bg(self, func: Callable[[], None]) -> None:
        threading.Thread(target=self._guarded, args=(func,), daemon=True).start()

    def _guarded(self, func: Callable[[], None]) -> None:
        try:
            func()
        except Exception as exc:
            self.log(f"ASKO ошибка: {exc}")
            self.state(f"ASKO: ошибка. {exc}")

    def start(self, deal_id: str) -> None:
        super().start(deal_id)
        self._run_bg(self._start_flow)

    def next_step(self) -> None:
        self._run_bg(self._next_step)

    def new_policy(self) -> None:
        self._run_bg(self._open_new_policy)

    def reset(self) -> None:
        self.deal = None
        self.stage = "idle"
        self.state("ASKO: сценарий сброшен. Можно начать новый полис.")

    def shutdown(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def _start_flow(self) -> None:
        self._fetch_deal()
        self._open_and_login()
        self._open_new_policy()
        self._fill_asko()

    def _next_step(self) -> None:
        if self.stage == "idle":
            self._start_flow()
        elif self.stage == "deal_loaded":
            self._open_and_login()
            self._open_new_policy()
            self._fill_asko()
        elif self.stage == "logged_in":
            self._open_new_policy()
            self._fill_asko()
        elif self.stage == "policy_opened":
            self._fill_asko()
        else:
            self.state("ASKO: текущий сценарий уже выполнен. Для новой сделки нажмите «Новый полис» или «Сбросить сценарий».")

    def _settings_value(self, key: str, default: str = "") -> str:
        return str(self.settings.get(key, default) or "")

    def _fetch_deal(self) -> None:
        module = self._load_module()
        webhook = self._settings_value("bitrix_webhook_url")
        self.log(f"ASKO: получаю сделку Bitrix24 ID {self.deal_id}...")
        result = module.bitrix_call(webhook, "crm.deal.get", {"id": self.deal_id})
        self.deal = module.extract_deal(result)
        preview = {
            "deal_id": self.deal.deal_id,
            "Номер бланка ASKO": self.deal.policy_number,
            "Госномер": self.deal.reg_number,
            "Дата начала": self.deal.start_date,
            "Телефон": self.deal.phone,
            "Email": self.deal.email,
            "ТС": self.deal.vehicle_model,
            "Год": self.deal.vehicle_year,
            "VIN": self.deal.vin,
            "Премия": self.deal.amount,
            "Валюта": self.deal.currency,
        }
        self.data(preview)
        self.stage = "deal_loaded"
        self.state("ASKO: данные сделки получены.")

    def _make_driver(self):
        module = self._load_module()
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--lang=ru-RU")
        profile = Path(self._settings_value("asko_chrome_profile_dir", str(ROOT / "asko_bitrix_filler" / "chrome_profile_asko2")))
        profile.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile}")
        return webdriver.Chrome(options=options)

    def _open_and_login(self) -> None:
        module = self._load_module()
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.driver:
            self.driver = self._make_driver()
        self.driver.get(module.ASKO_LOGIN_URL)
        wait = WebDriverWait(self.driver, 25)
        self._set_input(wait.until(EC.presence_of_element_located((By.ID, "tfSystemLogin"))), self._settings_value("asko_login"))
        self._set_input(wait.until(EC.presence_of_element_located((By.ID, "tfSystemPassword"))), self._settings_value("asko_password"))
        wait.until(EC.element_to_be_clickable((By.ID, "btSystemLogin1"))).click()
        self.stage = "logged_in"
        self.state("ASKO: вход выполнен или ожидается загрузка кабинета.")

    def _open_new_policy(self) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.driver:
            self._open_and_login()
        self._click_text_or_id("Полис ОГПО", "ext-gen238")
        try:
            self._click_text_or_id("Новый полис", "ext-gen277")
        except Exception:
            self._click_text_or_id("ОС ГПО BTC", "ext-gen1026")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        self.stage = "policy_opened"
        self.state("ASKO: форма нового полиса открыта.")

    def _fill_asko(self) -> None:
        module = self._load_module()
        if not self.deal:
            self._fetch_deal()
        if not self.driver:
            self._open_and_login()
        start_value = ""
        if self.deal.start_date:
            start_date = datetime.strptime(self.deal.start_date, "%d.%m.%Y").date()
            start_value = module.asko_start_datetime(start_date)
        code, phone = module.normalize_phone(self.deal.phone)
        term_text = self._settings_value("asko_term_text", "15 дней")
        pairs = [
            ("blank_number", self.deal.policy_number),
            ("start_datetime", start_value),
            ("payment_type", self._settings_value("asko_payment_type", "Безналичным")),
            ("payment_order", self._settings_value("asko_payment_order", "Единовременно")),
            ("phone_code", code),
            ("phone_number", phone),
            ("email", self.deal.email),
            ("notification_language", self._settings_value("asko_notification_language", "Русский")),
            ("client_form", self._settings_value("asko_client_form", "Физическое лицо")),
            ("note", f"Bitrix deal ID: {self.deal.deal_id}; Госномер: {self.deal.reg_number}; VIN: {self.deal.vin}"),
        ]
        for key, value in pairs:
            self._safe_set(module.ASKO_MAIN_FIELDS[key], value)
        self._select_asko_period(module.ASKO_MAIN_FIELDS["term"], term_text)
        self.stage = "filled"
        self.state("ASKO: основные поля заполнены в новом приложении. Проверьте данные в браузере.")

    def _set_input(self, element, value) -> None:
        from selenium.webdriver.common.keys import Keys

        value = "" if value is None else str(value)
        try:
            element.click()
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.BACKSPACE)
            element.send_keys(value)
            element.send_keys(Keys.TAB)
        except Exception:
            self.driver.execute_script(
                "arguments[0].value=arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
                element,
                value,
            )

    def _select_asko_period(self, element_id: str, term_text: str) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not term_text:
            return
        wait = WebDriverWait(self.driver, 10)
        try:
            element = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
            element.click()
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(term_text)
            option = wait.until(
                EC.element_to_be_clickable((By.XPATH, f"//*[normalize-space(text())='{term_text}' or normalize-space(.)='{term_text}']"))
            )
            option.click()
            self.log(f"ASKO: Период страхования ← {term_text}")
        except Exception:
            self._safe_set(element_id, term_text)
            self.log(f"ASKO: Период страхования установлен вводом текста ← {term_text}")


    def _safe_set(self, element_id: str, value) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if value is None or str(value) == "":
            return
        try:
            element = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.ID, element_id)))
            self._set_input(element, value)
            self.log(f"ASKO: {element_id} ← {value}")
        except Exception as exc:
            self.log(f"ASKO: не заполнено {element_id}: {exc}")

    def _click_text_or_id(self, text: str, element_id: str | None = None) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if element_id:
            try:
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.ID, element_id))).click()
                return
            except Exception:
                pass
        xpath = f"//*[normalize-space(text())='{text}' or contains(normalize-space(.), '{text}')]"
        WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath))).click()


def build_adapter(scenario_key: str, settings: dict, log: LogCallback, state: StateCallback, data: DataCallback) -> BaseScenarioAdapter:
    if scenario_key == "warta_poland":
        return WartaIntegratedAdapter(settings, log, state, data)
    if scenario_key == "asko_kazakhstan":
        return AskoIntegratedAdapter(settings, log, state, data)
    raise ValueError(f"Неизвестный сценарий: {scenario_key}")
