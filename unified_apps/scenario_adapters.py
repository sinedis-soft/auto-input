"""Integrated automation adapters used by the unified Bitrix router.

The adapters intentionally reuse automation logic from the older raw projects, but they
are controlled by the new unified UI instead of launching the old GUI windows.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

LogCallback = Callable[[str], None]
StateCallback = Callable[[str], None]
DataCallback = Callable[[dict], None]


ASKO_INSURED_LEGAL_FIELDS = {
    "legal_entity": "ext-comp-1564",
    "resident": "ext-comp-1565",
    "id": "ext-comp-1740",
    "search_button": "ext-gen1244",
    "selected_company": "ext-comp-1544",
    "name": "ext-comp-1539",
    "country": "ext-comp-1561",
    "address": "ext-comp-1572",
}


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
        self._temporary_profiles: list[Path] = []

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

        for profile in self._temporary_profiles:
            try:
                shutil.rmtree(profile)
            except OSError:
                pass

        self._temporary_profiles.clear()

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

        elif self.stage == "main_filled_wait_operator_next":
            self._open_insured_list_add()
            self._fill_legal_insured()

        elif self.stage == "insured_add_opened":
            self._fill_legal_insured()

        elif self.stage == "insured_filled":
            self.state(
                "ASKO: застрахованное юрлицо уже заполнено. "
                "Проверьте подтянутые данные в ASKO. Следующий этап пока не автоматизирован."
            )

        else:
            self.state(
                "ASKO: текущий сценарий уже выполнен. "
                "Для новой сделки нажмите «Новый полис» или «Сбросить сценарий»."
            )

    def _settings_value(self, key: str, default: str = "") -> str:
        return str(self.settings.get(key, default) or "")

    def _extract_deal_with_company_phone(self, module, result: dict, webhook: str):
        """
        Новый asko_bitrix_filler.extract_deal должен принимать webhook:
            extract_deal(result, webhook=webhook)

        Это нужно, чтобы внутри ASKO-модуля получить DEAL.COMPANY_ID,
        вызвать crm.company.get и взять PHONE из компании.
        """
        try:
            return module.extract_deal(result, webhook=webhook)
        except TypeError:
            self.log(
                "ASKO: asko_bitrix_filler.extract_deal() не принимает webhook. "
                "Телефон из COMPANY.PHONE и ИД ASKO могут быть получены неправильно. "
                "Обновите asko_bitrix_filler.py."
            )
            return module.extract_deal(result)

    def _extract_first_multifield_value_fallback(self, value) -> str:
        if not value:
            return ""

        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result = str(item.get("VALUE") or "").strip()
                    if result:
                        return result

                if isinstance(item, str) and item.strip():
                    return item.strip()

        if isinstance(value, dict):
            return str(value.get("VALUE") or "").strip()

        if isinstance(value, str):
            return value.strip()

        return ""

    def _complete_deal_company_data(self, module, result: dict, webhook: str) -> None:
        """
        Добирает телефон, название компании и ИД компании ASKO из карточки компании Bitrix.

        Причина: старые версии asko_bitrix_filler.extract_deal() брали
        UF_CRM_1705057253559 из сделки, хотя поле находится в компании.
        Здесь адаптер страхуется и сам читает crm.company.get по DEAL.COMPANY_ID.
        """
        if not self.deal:
            return

        company_id = str(result.get("COMPANY_ID") or "").strip()

        if not company_id or company_id == "0":
            if not getattr(self.deal, "phone_source", ""):
                self.deal.phone_source = "DEAL.COMPANY_ID пустой"
            return

        need_phone = not str(getattr(self.deal, "phone", "") or "").strip()
        need_name = not str(getattr(self.deal, "company_name", "") or "").strip()
        need_asko_id = not str(getattr(self.deal, "asko_company_id", "") or "").strip()

        if not (need_phone or need_name or need_asko_id):
            return

        try:
            company = module.bitrix_call(webhook, "crm.company.get", {"id": company_id}) or {}
        except Exception as exc:
            if not getattr(self.deal, "phone_source", ""):
                self.deal.phone_source = f"crm.company.get ошибка: {exc}"
            self.log(f"ASKO: не удалось прочитать компанию Bitrix ID {company_id}: {exc}")
            return

        if need_phone:
            extractor = getattr(module, "extract_first_multifield_value", None)
            if callable(extractor):
                phone = extractor(company.get("PHONE"))
            else:
                phone = self._extract_first_multifield_value_fallback(company.get("PHONE"))

            self.deal.phone = phone
            self.deal.phone_source = "COMPANY.PHONE" if phone else "COMPANY.PHONE пустой"

        if need_name:
            self.deal.company_name = str(company.get("TITLE") or "").strip()

        if need_asko_id:
            bitrix_fields = getattr(module, "BITRIX_FIELDS", {}) or {}
            asko_field = bitrix_fields.get("asko_company_id", "UF_CRM_1705057253559")
            self.deal.asko_company_id = str(company.get(asko_field) or "").strip()

    def _fetch_deal(self) -> None:
        module = self._load_module()
        webhook = self._settings_value("bitrix_webhook_url")

        self.log(f"ASKO: получаю сделку Bitrix24 ID {self.deal_id}...")
        result = module.bitrix_call(webhook, "crm.deal.get", {"id": self.deal_id})

        self.deal = self._extract_deal_with_company_phone(module, result, webhook)
        self._complete_deal_company_data(module, result, webhook)

        preview = {
            "deal_id": self.deal.deal_id,
            "Компания": getattr(self.deal, "company_name", ""),
            "Источник телефона": getattr(self.deal, "phone_source", ""),
            "ИД в ASKO KZ": getattr(self.deal, "asko_company_id", ""),
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

        if self.deal.phone:
            self.log(
                "ASKO: телефон для мобильного номера получен: "
                f"{self.deal.phone} "
                f"({getattr(self.deal, 'phone_source', 'источник не указан')})"
            )
        else:
            self.log(
                "ASKO: телефон не найден. "
                "Проверьте COMPANY_ID в сделке и PHONE в карточке компании Bitrix24."
            )

        if getattr(self.deal, "asko_company_id", ""):
            self.log(f"ASKO: ИД компании для застрахованного получен: {self.deal.asko_company_id}")
        else:
            self.log(
                "ASKO: ИД компании в ASKO KZ не найден. "
                "Проверьте поле Bitrix UF_CRM_1705057253559."
            )

        self.stage = "deal_loaded"
        self.state("ASKO: данные сделки получены.")

    def _chrome_options(self, profile: Path):
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--lang=ru-RU")
        options.add_argument(f"--user-data-dir={profile}")

        return options

    def _cleanup_chrome_profile(self, profile: Path) -> None:
        stale_paths = [
            profile / "DevToolsActivePort",
            profile / "SingletonLock",
            profile / "SingletonSocket",
            profile / "SingletonCookie",
            profile / "LOCK",
            profile / "Default" / "LOCK",
        ]

        for stale_path in stale_paths:
            try:
                if stale_path.is_dir():
                    shutil.rmtree(stale_path)
                elif stale_path.exists():
                    stale_path.unlink()
            except OSError:
                self.log(
                    f"ASKO: Chrome profile занят, не удалось удалить {stale_path.name}. "
                    "Попробую запасной профиль."
                )

    def _make_driver_with_profile(self, profile: Path):
        from selenium import webdriver

        profile.mkdir(parents=True, exist_ok=True)
        self._cleanup_chrome_profile(profile)

        return webdriver.Chrome(options=self._chrome_options(profile))

    def _short_error(self, exc: Exception) -> str:
        return str(exc).splitlines()[0]

    def _switch_to_asko_browser_tab(self) -> None:
        if not self.driver:
            return

        for handle in self.driver.window_handles:
            self.driver.switch_to.window(handle)
            url = self.driver.current_url or ""
            if "asko2.novelty.kz" in url:
                self.log("ASKO: активирована вкладка Chrome с ASKO.")
                return

        self.log("ASKO: вкладка Chrome с ASKO не найдена, использую текущую вкладку.")

    def _make_driver(self):
        from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

        profile = Path(
            self._settings_value(
                "asko_chrome_profile_dir",
                str(ROOT / "asko_bitrix_filler" / "chrome_profile_asko2"),
            )
        )

        try:
            self.log(f"ASKO: запускаю Chrome с профилем {profile}")
            return self._make_driver_with_profile(profile)

        except (SessionNotCreatedException, WebDriverException) as exc:
            fallback_profile = Path(tempfile.mkdtemp(prefix="asko_chrome_profile_"))
            self._temporary_profiles.append(fallback_profile)

            self.log(
                "ASKO: основной Chrome profile не запустился. "
                "Чаще всего он занят открытым Chrome или повреждён. "
                f"Пробую чистый временный профиль: {fallback_profile}. "
                f"Краткая ошибка: {self._short_error(exc)}"
            )

            try:
                return self._make_driver_with_profile(fallback_profile)

            except (SessionNotCreatedException, WebDriverException) as retry_exc:
                raise RuntimeError(
                    "Chrome для ASKO не запустился даже с чистым временным профилем. "
                    "Закройте все окна Chrome/Chromedriver и попробуйте снова. "
                    f"Первая ошибка: {self._short_error(exc)}; "
                    f"повторная ошибка: {self._short_error(retry_exc)}"
                ) from retry_exc

    def _open_and_login(self) -> None:
        module = self._load_module()

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.driver:
            self.driver = self._make_driver()

        self.driver.get(module.ASKO_LOGIN_URL)

        wait = WebDriverWait(self.driver, 25)

        self._set_input(
            wait.until(EC.presence_of_element_located((By.ID, "tfSystemLogin"))),
            self._settings_value("asko_login"),
        )

        self._set_input(
            wait.until(EC.presence_of_element_located((By.ID, "tfSystemPassword"))),
            self._settings_value("asko_password"),
        )

        wait.until(EC.element_to_be_clickable((By.ID, "btSystemLogin1"))).click()

        self.stage = "logged_in"
        self.state("ASKO: вход выполнен или ожидается загрузка кабинета.")

    def _open_new_policy(self) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.driver:
            self._open_and_login()

        self._switch_to_asko_browser_tab()

        self._click_text_or_id("Полис ОГПО", "ext-gen238")

        try:
            self._click_text_or_id("Новый полис", "ext-gen277")
        except Exception:
            self._click_text_or_id("ОС ГПО BTC", "ext-gen1026")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        self.stage = "policy_opened"
        self.state("ASKO: форма нового полиса открыта.")

    def _ensure_policy_form_opened(self) -> None:
        module = self._load_module()

        if not self.driver:
            self._open_and_login()

        self._switch_to_asko_browser_tab()

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait

            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.ID, module.ASKO_MAIN_FIELDS["blank_number"]))
            )
            self.stage = "policy_opened"
            self.log("ASKO: форма нового полиса уже открыта.")
            return
        except Exception:
            pass

        self.state("ASKO: перехожу на вкладку Полис ОГПО перед вводом данных...")
        self._open_new_policy()

    def _fill_asko(self) -> None:
        module = self._load_module()

        if not self.deal:
            self._fetch_deal()

        self._ensure_policy_form_opened()

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
        ]

        for key, value in pairs:
            self._safe_set(module.ASKO_MAIN_FIELDS[key], value)

        self._select_asko_period(module.ASKO_MAIN_FIELDS["term"], term_text)

        self.stage = "main_filled_wait_operator_next"
        self.state(
            "ASKO: основные поля полиса заполнены. "
            "Проверьте данные и вручную нажмите «Далее» в ASKO. "
            "После перехода нажмите «Далее» в приложении, чтобы добавить застрахованное юрлицо."
        )

    def _open_insured_list_add(self) -> None:
        """
        Открывает блок «Список застрахованных» и нажимает «Добавить».
        По снимкам ASKO кнопка добавления застрахованного — ext-gen282.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.driver:
            self._open_and_login()

        self._switch_to_asko_browser_tab()

        self.state("ASKO: открываю «Список застрахованных» → «Добавить»...")

        try:
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "ext-gen282"))
            ).click()
        except Exception:
            xpath = (
                "//a[normalize-space(.)='Добавить' "
                "or .//*[normalize-space(.)='Добавить']]"
            )
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            ).click()

        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, ASKO_INSURED_LEGAL_FIELDS["legal_entity"]))
        )

        self.stage = "insured_add_opened"
        self.state("ASKO: форма добавления застрахованного открыта.")

    def _fill_legal_insured(self) -> None:
        """
        Заполняет застрахованного как юридическое лицо.

        Логика ASKO:
        1. Включить «Юридическое лицо» ext-comp-1564.
        2. Выключить «Резидент/Гражданин РК» ext-comp-1565, если включён.
        3. Вставить ИД в ext-comp-1740.
        4. Обязательно нажать кнопку «поиск» ext-gen1244.
        5. Дождаться результата поиска.
        6. Выбрать найденного клиента.
        7. Проверить, что подтянулись выбранный клиент, наименование и страна.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.deal:
            self._fetch_deal()

        if not self.driver:
            self._open_and_login()

        self._switch_to_asko_browser_tab()

        asko_company_id = str(getattr(self.deal, "asko_company_id", "") or "").strip()

        if not asko_company_id:
            raise ValueError(
                "В сделке не найден ИД компании в ASKO. "
                "Проверьте поле Bitrix UF_CRM_1705057253559 и extract_deal() в asko_bitrix_filler.py."
            )

        wait = WebDriverWait(self.driver, 25)

        self.state(f"ASKO: заполняю застрахованное юрлицо по ИД {asko_company_id}...")

        legal_checkbox = wait.until(
            EC.presence_of_element_located((By.ID, ASKO_INSURED_LEGAL_FIELDS["legal_entity"]))
        )

        if not legal_checkbox.is_selected():
            try:
                legal_checkbox.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", legal_checkbox)
            self.log("ASKO: включён режим «Юридическое лицо».")
            self._sleep_short(1.0)

        wait.until(
            EC.presence_of_element_located((By.ID, ASKO_INSURED_LEGAL_FIELDS["id"]))
        )

        try:
            resident_checkbox = wait.until(
                EC.presence_of_element_located((By.ID, ASKO_INSURED_LEGAL_FIELDS["resident"]))
            )
            if resident_checkbox.is_selected():
                try:
                    resident_checkbox.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", resident_checkbox)
                self.log("ASKO: выключен чекбокс «Резидент/Гражданин РК».")
                self._sleep_short(1.0)
        except Exception:
            self.log("ASKO: чекбокс резидентства ext-comp-1565 не найден или недоступен.")

        id_input = wait.until(
            EC.element_to_be_clickable((By.ID, ASKO_INSURED_LEGAL_FIELDS["id"]))
        )

        id_input.click()
        id_input.send_keys(Keys.CONTROL, "a")
        id_input.send_keys(Keys.BACKSPACE)
        id_input.send_keys(asko_company_id)

        self.driver.execute_script(
            """
            const el = arguments[0];
            el.dispatchEvent(new Event("input", {bubbles: true}));
            el.dispatchEvent(new Event("change", {bubbles: true}));
            """,
            id_input,
        )

        self.log(f"ASKO: ИД юрлица введён ← {asko_company_id}")

        self._click_asko_search_button()
        self._click_asko_company_search_result(asko_company_id)
        self._verify_asko_legal_insured_selected(asko_company_id)

        self.stage = "insured_filled"
        self.state(
            f"ASKO: застрахованное юрлицо выбрано по ИД {asko_company_id}. "
            "Проверьте подтянутые данные в ASKO."
        )

    def _sleep_short(self, seconds: float = 0.8) -> None:
        import time
        time.sleep(seconds)

    def _click_asko_search_button(self) -> None:
        """
        Нажимает кнопку «поиск» на форме застрахованного.

        В ASKO это ExtJS-ссылка a#ext-gen1244. Обычный Selenium click()
        иногда не запускает обработчик, поэтому используются несколько способов.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        wait = WebDriverWait(self.driver, 15)
        button_id = ASKO_INSURED_LEGAL_FIELDS["search_button"]

        search_button = wait.until(
            EC.presence_of_element_located((By.ID, button_id))
        )

        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            search_button,
        )
        self._sleep_short(0.3)

        methods = []

        def selenium_click():
            wait.until(EC.element_to_be_clickable((By.ID, button_id))).click()

        def js_click():
            self.driver.execute_script("arguments[0].click();", search_button)

        def action_click():
            ActionChains(self.driver).move_to_element(search_button).pause(0.2).click().perform()

        def cdp_coordinate_click():
            rect = search_button.rect
            x = int(rect["x"] + rect["width"] / 2)
            y = int(rect["y"] + rect["height"] / 2)

            self.driver.execute_cdp_cmd(
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
            )
            self.driver.execute_cdp_cmd(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
            )

        def extjs_fire_click():
            result = self.driver.execute_script(
                """
                const id = arguments[0];
                const el = document.getElementById(id);

                if (!el) {
                    return {ok: false, reason: "element not found"};
                }

                const eventTypes = ["mouseover", "mousedown", "mouseup", "click"];
                for (const eventType of eventTypes) {
                    const ev = new MouseEvent(eventType, {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    });
                    el.dispatchEvent(ev);
                }

                return {ok: true};
                """,
                button_id,
            )

            if not result or not result.get("ok"):
                raise RuntimeError(result)

        methods.append(("обычный Selenium click", selenium_click))
        methods.append(("JS click", js_click))
        methods.append(("ActionChains click", action_click))
        methods.append(("CDP coordinate click", cdp_coordinate_click))
        methods.append(("ExtJS mouse events", extjs_fire_click))

        last_error = None

        for method_name, method in methods:
            try:
                method()
                self.log(f"ASKO: кнопка «поиск» нажата способом: {method_name}")
                self._sleep_short(1.2)
                return
            except Exception as exc:
                last_error = exc
                self.log(f"ASKO: способ нажатия «{method_name}» не сработал: {exc}")

        raise RuntimeError(f"ASKO: не удалось нажать кнопку «поиск». Последняя ошибка: {last_error}")

    def _click_asko_company_search_result(self, asko_company_id: str) -> None:
        """
        После нажатия «поиск» выбирает найденную строку клиента.

        В ASKO/ExtJS результат может появиться:
        - отдельной строкой выпадающего списка;
        - в поле ext-comp-1544 после автоподстановки.

        Поэтому используется комбинированный сценарий.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        wait = WebDriverWait(self.driver, 25)

        def loading_finished(driver) -> bool:
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""
            selected = driver.find_element(
                By.ID,
                ASKO_INSURED_LEGAL_FIELDS["selected_company"],
            )
            selected_value = selected.get_attribute("value") or ""
            return "Загрузка..." not in selected_value and "Загрузка..." not in body_text

        try:
            wait.until(loading_finished)
        except Exception:
            self.log("ASKO: индикатор загрузки результата не исчез за стандартное время.")

        # Сначала ищем реальную видимую строку результата, а не весь body/html.
        js_result = self.driver.execute_script(
            """
            const companyId = String(arguments[0]);
            const candidates = [];

            function visible(el) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none"
                    && style.visibility !== "hidden"
                    && rect.width > 0
                    && rect.height > 0;
            }

            const nodes = Array.from(document.querySelectorAll(
                ".x-combo-list-item, .x-boundlist-item, .x-grid3-row, .x-list-item, " +
                ".x-combo-list-inner div, .x-layer div, .x-menu-list-item, div"
            ));

            for (const el of nodes) {
                if (!visible(el)) {
                    continue;
                }

                const text = (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();

                if (!text.includes(companyId)) {
                    continue;
                }

                // Отбрасываем слишком крупные контейнеры: body-панели тоже содержат ИД из поля ввода.
                const rect = el.getBoundingClientRect();
                const area = rect.width * rect.height;

                if (area > 250000 || rect.height > 120) {
                    continue;
                }

                candidates.push({
                    element: el,
                    text: text,
                    area: area,
                    top: rect.top,
                    left: rect.left
                });
            }

            candidates.sort((a, b) => {
                const aVerified = a.text.includes("Выверен") ? 0 : 1;
                const bVerified = b.text.includes("Выверен") ? 0 : 1;
                if (aVerified !== bVerified) return aVerified - bVerified;
                return a.area - b.area;
            });

            if (!candidates.length) {
                return {ok: false, text: ""};
            }

            const chosen = candidates[0].element;
            chosen.scrollIntoView({block: "center", inline: "center"});
            chosen.click();

            return {ok: true, text: candidates[0].text};
            """,
            asko_company_id,
        )

        if js_result and js_result.get("ok"):
            self.log(f"ASKO: выбран найденный клиент: {js_result.get('text')}")
            return

        # Запасной вариант: XPath по выпадающим элементам.
        option_xpath = (
            "//*["
            "contains(@class, 'x-combo-list-item') "
            "or contains(@class, 'x-boundlist-item') "
            "or contains(@class, 'x-grid3-row') "
            "or contains(@class, 'x-list-item')"
            "]"
            f"[contains(normalize-space(.), '{asko_company_id}')]"
        )

        try:
            option = WebDriverWait(self.driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, option_xpath))
            )
            ActionChains(self.driver).move_to_element(option).click(option).perform()
            self.log(f"ASKO: выбран клиент из выпадающего списка по ИД {asko_company_id}.")
            return
        except Exception:
            pass

        # Запасной вариант: результат уже попал в поле ext-comp-1544.
        selected_input = wait.until(
            EC.presence_of_element_located((By.ID, ASKO_INSURED_LEGAL_FIELDS["selected_company"]))
        )

        selected_value = (selected_input.get_attribute("value") or "").strip()

        if asko_company_id in selected_value:
            selected_input.click()
            selected_input.send_keys(Keys.ENTER)
            self.log(f"ASKO: подтверждён клиент из поля результата: {selected_value}")
            return

        raise RuntimeError(f"ASKO: после нажатия «поиск» клиент с ИД {asko_company_id} не найден.")

    def _verify_asko_legal_insured_selected(self, asko_company_id: str) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        wait = WebDriverWait(self.driver, 25)

        def selected(driver) -> bool:
            selected_value = (
                driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["selected_company"])
                .get_attribute("value")
                or ""
            ).strip()
            name_value = (
                driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["name"])
                .get_attribute("value")
                or ""
            ).strip()
            country_value = (
                driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["country"])
                .get_attribute("value")
                or ""
            ).strip()

            return asko_company_id in selected_value and bool(name_value) and bool(country_value)

        try:
            wait.until(selected)
        except Exception:
            selected_value = (
                self.driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["selected_company"])
                .get_attribute("value")
                or ""
            ).strip()
            name_value = (
                self.driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["name"])
                .get_attribute("value")
                or ""
            ).strip()
            country_value = (
                self.driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["country"])
                .get_attribute("value")
                or ""
            ).strip()

            raise RuntimeError(
                "ASKO: клиент не подтверждён после поиска. "
                f"Ожидали ИД {asko_company_id}. "
                f"Результат: {selected_value!r}; "
                f"Наименование: {name_value!r}; "
                f"Страна: {country_value!r}."
            )

        selected_value = (
            self.driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["selected_company"])
            .get_attribute("value")
            or ""
        ).strip()
        name_value = (
            self.driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["name"])
            .get_attribute("value")
            or ""
        ).strip()
        country_value = (
            self.driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["country"])
            .get_attribute("value")
            or ""
        ).strip()
        address_value = (
            self.driver.find_element(By.ID, ASKO_INSURED_LEGAL_FIELDS["address"])
            .get_attribute("value")
            or ""
        ).strip()

        self.log(
            "ASKO: юрлицо подтверждено. "
            f"Результат: {selected_value}; "
            f"Наименование: {name_value}; "
            f"Страна: {country_value}; "
            f"Адрес: {address_value or 'не заполнен'}"
        )

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
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not term_text:
            return

        wait = WebDriverWait(self.driver, 15)

        ext_result = self.driver.execute_script(
            """
            const id = arguments[0];
            const text = arguments[1];

            if (!window.Ext || !Ext.getCmp) {
                return {ok: false, reason: "ExtJS не найден"};
            }

            const cmp = Ext.getCmp(id);
            if (!cmp) {
                return {ok: false, reason: "Компонент ExtJS не найден: " + id};
            }

            const store = cmp.getStore ? cmp.getStore() : null;
            let record = null;
            let index = -1;

            if (store) {
                const displayField = cmp.displayField || "text";
                const valueField = cmp.valueField || "value";

                index = store.findBy(function(rec) {
                    const displayValue = String(rec.get(displayField) || "").trim();
                    const value = String(rec.get(valueField) || "").trim();
                    return displayValue === text || value === text;
                });

                if (index >= 0) {
                    record = store.getAt(index);
                }
            }

            const oldValue = cmp.getValue ? cmp.getValue() : null;

            if (record) {
                const valueField = cmp.valueField || cmp.displayField || "value";
                const newValue = record.get(valueField);

                if (cmp.setValue) {
                    cmp.setValue(newValue);
                }

                if (cmp.fireEvent) {
                    cmp.fireEvent("select", cmp, record, index);
                    cmp.fireEvent("change", cmp, newValue, oldValue);
                    cmp.fireEvent("blur", cmp);
                }

                if (cmp.onSelect) {
                    try {
                        cmp.onSelect(record, index);
                    } catch (e) {}
                }

                return {ok: true, mode: "record", value: String(newValue)};
            }

            if (cmp.setValue) {
                cmp.setValue(text);
            }

            if (cmp.fireEvent) {
                cmp.fireEvent("change", cmp, text, oldValue);
                cmp.fireEvent("select", cmp, null, -1);
                cmp.fireEvent("blur", cmp);
            }

            return {ok: true, mode: "text", value: text};
            """,
            element_id,
            term_text,
        )

        if ext_result and ext_result.get("ok"):
            try:
                element = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
                element.click()
                element.send_keys(Keys.TAB)
            except Exception:
                pass

            self.log(f"ASKO: Период страхования выбран через ExtJS ← {term_text}")
            return

        self.log(f"ASKO: ExtJS-выбор периода не сработал: {ext_result}")

        element = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
        element.click()

        try:
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.BACKSPACE)
            element.send_keys(term_text)
        except Exception:
            pass

        option_xpath = (
            f"//*[contains(@class, 'x-combo-list-item') "
            f"or contains(@class, 'x-boundlist-item') "
            f"or contains(@class, 'x-list-item') "
            f"or self::div]"
            f"[normalize-space(.)='{term_text}']"
        )

        option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))

        ActionChains(self.driver).move_to_element(option).click(option).perform()

        try:
            element = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
            element.send_keys(Keys.TAB)
        except Exception:
            pass

        self.driver.execute_script(
            """
            const el = document.getElementById(arguments[0]);
            if (el) {
                el.dispatchEvent(new Event("input", {bubbles: true}));
                el.dispatchEvent(new Event("change", {bubbles: true}));
                el.dispatchEvent(new Event("blur", {bubbles: true}));
            }
            """,
            element_id,
        )

        self.log(f"ASKO: Период страхования выбран кликом из списка ← {term_text}")

    def _safe_set(self, element_id: str, value) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if value is None or str(value) == "":
            return

        try:
            element = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.ID, element_id))
            )
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
                WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.ID, element_id))
                ).click()
                return
            except Exception:
                pass

        xpath = f"//*[normalize-space(text())='{text}' or contains(normalize-space(.), '{text}')]"

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        ).click()


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