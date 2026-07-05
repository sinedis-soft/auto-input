"""ASKO integrated scenario adapter."""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .base import BaseScenarioAdapter, DataCallback, LogCallback, StateCallback

ROOT = Path(__file__).resolve().parents[2]

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


ASKO_VEHICLE_FIELDS = {
    "reg_number": "ext-comp-1986",
    "registration_certificate": "ext-comp-1988",
    "registration_certificate_issue_date": "ext-comp-1995",
    "vin": "ext-comp-1984",
    "vehicle_year": "ext-comp-1996",
    "registration_region": "ext-comp-1989",
    "registration_country": "ext-comp-1990",
    "search_button": "ext-gen1537",
    "selected_vehicle": "ext-comp-1991",
    "apply_button": "ext-gen1648",
}

ASKO_TEMPORARY_ENTRY_REGION = "Временный въезд (Нерезиденты РК)"

BITRIX_COUNTRY_ID_TO_ASKO_REGISTRATION_COUNTRY = {
    "529": "Армения",
    "123": "РЕСПУБЛИКА БЕЛАРУСЬ / БЕЛОРУСИЯ РЕСПУБЛИКАСЫ",
    "523": "Грузия",
    "527": "КЫРГЫЗСТАН / ҚЫРҒЫСТАН",
    "383": "МОНГОЛИЯ / МОНҒОЛИЯ",
    "125": "РОССИЙСКАЯ ФЕДЕРАЦИЯ / РЕСЕЙ ФЕДЕРАЦИЯСЫ",
    "525": "УЗБЕКИСТАН / ӨЗБЕКСТАН",
}

BITRIX_COUNTRY_VALUE_TO_ASKO_REGISTRATION_COUNTRY = {
    "armenia": "Армения",
    "армен": "Армения",
    "belarus": "РЕСПУБЛИКА БЕЛАРУСЬ / БЕЛОРУСИЯ РЕСПУБЛИКАСЫ",
    "беларус": "РЕСПУБЛИКА БЕЛАРУСЬ / БЕЛОРУСИЯ РЕСПУБЛИКАСЫ",
    "белорус": "РЕСПУБЛИКА БЕЛАРУСЬ / БЕЛОРУСИЯ РЕСПУБЛИКАСЫ",
    "georgia": "Грузия",
    "груз": "Грузия",
    "kyrgyzstan": "КЫРГЫЗСТАН / ҚЫРҒЫСТАН",
    "кыргыз": "КЫРГЫЗСТАН / ҚЫРҒЫСТАН",
    "киргиз": "КЫРГЫЗСТАН / ҚЫРҒЫСТАН",
    "mongolia": "МОНГОЛИЯ / МОНҒОЛИЯ",
    "монгол": "МОНГОЛИЯ / МОНҒОЛИЯ",
    "russia": "РОССИЙСКАЯ ФЕДЕРАЦИЯ / РЕСЕЙ ФЕДЕРАЦИЯСЫ",
    "росси": "РОССИЙСКАЯ ФЕДЕРАЦИЯ / РЕСЕЙ ФЕДЕРАЦИЯСЫ",
    "uzbekistan": "УЗБЕКИСТАН / ӨЗБЕКСТАН",
    "узбе": "УЗБЕКИСТАН / ӨЗБЕКСТАН",
    "tajikistan": "ТАДЖИКИСТАН/ Тәжікстан",
    "тадж": "ТАДЖИКИСТАН/ Тәжікстан",
}

ASKO_DEFAULT_REGISTRATION_COUNTRY = "Другие страны"


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
            root_path = str(ROOT)
            if not getattr(sys, "frozen", False) and root_path not in sys.path:
                sys.path.insert(0, root_path)

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

    def _continue_after_main_policy_fields(self) -> None:
        """Автоматически продолжает ASKO-сценарий после заполнения основных полей."""
        self._open_insured_list_add()
        self._fill_legal_insured()

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
            self._continue_after_main_policy_fields()

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
            "СРТС": getattr(self.deal, "registration_certificate", ""),
            "Дата выдачи СРТС": self._vehicle_certificate_issue_date_value(),
            "Страна регистрации ТС": getattr(self.deal, "vehicle_registration_country", ""),
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

        profile_setting = self._settings_value("asko_chrome_profile_dir", "")
        if profile_setting:
            profile = Path(profile_setting).expanduser()
        elif getattr(sys, "frozen", False):
            profile = Path(sys.executable).resolve().parent / "chrome_profile_asko2"
        else:
            profile = ROOT / "asko_bitrix_filler" / "chrome_profile_asko2"

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
        """
        Открывает вкладку «Полис ОГПО» и форму «Новый полис».

        Важно: ext-gen* в ASKO/ExtJS нестабильны. По актуальному снимку:
        - «Полис ОГПО» = ext-gen234;
        - «Новый полис» = ext-gen273.
        Если ID не сработает, метод переходит к поиску по тексту.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.driver:
            self._open_and_login()

        self._switch_to_asko_browser_tab()

        self._click_text_or_id("Полис ОГПО", "ext-gen234")

        try:
            self._click_text_or_id("Новый полис", "ext-gen273")
        except Exception:
            self._click_text_or_id("ОС ГПО BTC", "ext-gen1026")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        self.stage = "policy_opened"
        self.state("ASKO: форма нового полиса открыта.")

    def _click_text_or_id(self, text: str, element_id: str | None = None) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if element_id:
            try:
                WebDriverWait(self.driver, 1).until(
                    EC.element_to_be_clickable((By.ID, element_id))
                ).click()
                return
            except Exception:
                pass

        xpath = f"//*[normalize-space(text())='{text}' or contains(normalize-space(.), '{text}')]"

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        ).click()

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

        text_pairs = [
            ("blank_number", self.deal.policy_number),
            ("start_datetime", start_value),
            ("phone_code", code),
            ("phone_number", phone),
            ("email", self.deal.email),
        ]

        for key, value in text_pairs:
            self._safe_set(module.ASKO_MAIN_FIELDS[key], value)

        combo_pairs = [
            ("term", term_text, "Период страхования"),
            ("payment_type", self._settings_value("asko_payment_type", "Безналичным"), "Тип оплаты"),
            ("payment_order", self._settings_value("asko_payment_order", "Единовременно"), "Порядок оплаты"),
            (
                "notification_language",
                self._settings_value("asko_notification_language", "Русский"),
                "Язык уведомлений",
            ),
            ("client_form", self._settings_value("asko_client_form", "Физическое лицо"), "Форма клиента"),
        ]

        for key, value, label in combo_pairs:
            self._select_asko_period(module.ASKO_MAIN_FIELDS[key], value, label=label)

        self.stage = "main_filled_wait_operator_next"
        self.state(
            "Основные поля полиса заполнены. Проверьте данные и вручную нажмите “Далее” "
            "в ASKO. После перехода нажмите “Далее” в приложении, чтобы добавить "
            "застрахованное юрлицо."
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

        Кнопка «поиск» в ASKO не запускается надёжно через Selenium, поэтому:
        1. Робот включает юрлицо, снимает резидентство РК и вводит ИД.
        2. Оператор вручную нажимает «поиск» и выбирает найденного клиента.
        3. Робот ждёт, пока поля клиента подтянутся.
        4. Робот просит оператора нажать «Применить».
        5. Робот ждёт, пока слева «Страхователь / Выбрать» сменится на компанию.
        6. Робот автоматически открывает «Список ТС» → «Добавить».
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

        company_name = self._wait_for_manual_asko_company_search_result(asko_company_id)

        self.stage = "legal_insured_wait_operator_apply"
        self.state(
            "ASKO: клиент найден и поля застрахованного заполнены. "
            "Нажмите «Применить» в ASKO. Робот ждёт подтверждение и затем сам откроет «Список ТС» → «Добавить»."
        )

        self._wait_policyholder_applied_then_open_vehicle_add(
            expected_company_name=company_name,
            timeout=240,
        )

        self.stage = "vehicle_add_opened"
        self.state("ASKO: страхователь подтверждён. Открыта форма добавления ТС.")

    def _sleep_short(self, seconds: float = 0.8) -> None:
        import time
        time.sleep(seconds)

    def _wait_for_manual_asko_company_search_result(self, asko_company_id: str, timeout: int = 240) -> str:
        """
        Ждёт ручное действие оператора:
        оператор нажимает «поиск», выбирает клиента из выпадающего списка,
        после чего ASKO подтягивает selected_company/name/country.
        """
        import time

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        self.state(
            f"ASKO: ИД {asko_company_id} введён. "
            "Нажмите «поиск» в ASKO и выберите найденного клиента. Робот ждёт заполнения полей."
        )

        wait = WebDriverWait(self.driver, timeout, poll_frequency=0.8)

        def fields_filled(driver):
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

            if asko_company_id in selected_value and name_value and country_value:
                return name_value

            return False

        try:
            company_name = wait.until(fields_filled)
        except Exception as exc:
            selected_value = self._read_input_value(ASKO_INSURED_LEGAL_FIELDS["selected_company"])
            name_value = self._read_input_value(ASKO_INSURED_LEGAL_FIELDS["name"])
            country_value = self._read_input_value(ASKO_INSURED_LEGAL_FIELDS["country"])
            raise RuntimeError(
                "ASKO: клиент не выбран после ручного поиска. "
                f"Ожидали ИД {asko_company_id}. "
                f"Результат: {selected_value!r}; "
                f"Наименование: {name_value!r}; "
                f"Страна: {country_value!r}."
            ) from exc

        selected_value = self._read_input_value(ASKO_INSURED_LEGAL_FIELDS["selected_company"])
        country_value = self._read_input_value(ASKO_INSURED_LEGAL_FIELDS["country"])
        address_value = self._read_input_value(ASKO_INSURED_LEGAL_FIELDS["address"])

        self.log(
            "ASKO: юрлицо найдено после ручного поиска. "
            f"Результат: {selected_value}; "
            f"Наименование: {company_name}; "
            f"Страна: {country_value}; "
            f"Адрес: {address_value or 'не заполнен'}"
        )

        return str(company_name).strip()

    def _read_input_value(self, element_id: str) -> str:
        from selenium.webdriver.common.by import By

        try:
            return (self.driver.find_element(By.ID, element_id).get_attribute("value") or "").strip()
        except Exception:
            return ""

    def _wait_policyholder_applied_then_open_vehicle_add(
        self,
        expected_company_name: str = "",
        timeout: int = 240,
    ) -> None:
        """
        После ручного нажатия «Применить» ждёт, что в левой панели
        блок «Страхователь» перестанет быть «Выбрать» и станет выбранной компанией.
        Затем автоматически нажимает «Список ТС» → «Добавить».
        """
        import time

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        expected_company_name = (expected_company_name or "").strip()
        start = time.time()
        last_state = ""

        def policyholder_selected(driver):
            nonlocal last_state
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""
            lines = [line.strip() for line in body_text.splitlines() if line.strip()]

            selected_by_company = bool(expected_company_name and expected_company_name in body_text)

            selected_by_block = False
            for index, line in enumerate(lines):
                if line == "Страхователь":
                    nearby = " ".join(lines[index:index + 4])
                    last_state = nearby
                    if "Выбрать" not in nearby:
                        selected_by_block = True
                    break

            if selected_by_company or selected_by_block:
                return True

            if time.time() - start > timeout:
                return False

            return False

        wait = WebDriverWait(self.driver, timeout, poll_frequency=1.0)

        try:
            wait.until(policyholder_selected)
        except Exception as exc:
            raise RuntimeError(
                "ASKO: после нажатия «Применить» страхователь в левой панели не подтвердился. "
                f"Последнее состояние блока: {last_state or 'не определено'}."
            ) from exc

        self.log("ASKO: страхователь подтверждён в левой панели. Открываю «Список ТС» → «Добавить».")
        self._open_vehicle_list_add()

    def _open_vehicle_list_add(self) -> None:
        """
        Открывает «Список ТС» → «Добавить», затем заполняет госномер ТС.

        По текущему экрану ASKO:
        - «Список ТС» → «Добавить» — ext-gen294;
        - поле «Гос номер» — ext-comp-1986;
        - кнопка «поиск» по ТС — ext-gen1537;
        - поле выбранного ТС / результата — ext-comp-1991.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        self._switch_to_asko_browser_tab()

        try:
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "ext-gen294"))
            ).click()
            self.log("ASKO: нажато «Список ТС» → «Добавить» через ext-gen294.")
        except Exception:
            xpath = (
                "//*[contains(normalize-space(.), 'Список ТС')]"
                "/following::*[normalize-space(.)='Добавить'][1]"
            )
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            ).click()
            self.log("ASKO: нажато «Список ТС» → «Добавить» через XPath.")

        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, ASKO_VEHICLE_FIELDS["reg_number"]))
        )

        self.stage = "vehicle_add_opened"
        self._fill_vehicle_reg_number_and_wait_manual_search()

    def _fill_vehicle_reg_number_and_wait_manual_search(self, timeout: int = 240) -> None:
        """
        Заполняет госномер ТС из Bitrix и ждёт ручной поиск/выбор ТС оператором.

        Кнопку «поиск» по ТС оставляем оператору по той же причине, что и поиск юрлица:
        ExtJS-кнопки ASKO нестабильно запускаются через Selenium.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not self.deal:
            self._fetch_deal()

        reg_number = str(getattr(self.deal, "reg_number", "") or "").strip()
        if not reg_number:
            raise RuntimeError("ASKO: в сделке Bitrix не найден госномер ТС reg_number.")

        wait = WebDriverWait(self.driver, 20)
        reg_input = wait.until(
            EC.element_to_be_clickable((By.ID, ASKO_VEHICLE_FIELDS["reg_number"]))
        )

        reg_input.click()
        reg_input.send_keys(Keys.CONTROL, "a")
        reg_input.send_keys(Keys.BACKSPACE)
        reg_input.send_keys(reg_number)

        self.driver.execute_script(
            """
            const el = arguments[0];
            el.dispatchEvent(new Event("input", {bubbles: true}));
            el.dispatchEvent(new Event("change", {bubbles: true}));
            """,
            reg_input,
        )

        self.log(f"ASKO: Гос номер ТС введён ← {reg_number}")
        self.stage = "vehicle_wait_operator_search"
        self.state(
            f"ASKO: госномер ТС {reg_number} введён. "
            "Нажмите «поиск» в ASKO и выберите выпавший автомобиль. Робот ждёт подтверждения выбора."
        )

        self._wait_for_manual_vehicle_search_result(reg_number, timeout=timeout)
        self._fill_vehicle_details_after_selection()

        self.stage = "vehicle_selected"
        self.state(
            "ASKO: автомобиль выбран, СРТС/регион/страна регистрации заполнены; год ТС проверен без остановки сценария. "
            "Проверьте форму ТС и нажмите «Применить» в ASKO."
        )

    def _wait_for_manual_vehicle_search_result(self, reg_number: str, timeout: int = 240) -> None:
        """
        Ждёт, пока оператор вручную нажмёт «поиск» по госномеру и выберет ТС.
        Подтверждаем выбор по полю результата, VIN или другим подтянутым полям формы.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        reg_number_norm = self._normalize_vehicle_reg_number(reg_number)
        wait = WebDriverWait(self.driver, timeout, poll_frequency=0.8)

        def vehicle_selected(driver):
            selected_value = (
                driver.find_element(By.ID, ASKO_VEHICLE_FIELDS["selected_vehicle"])
                .get_attribute("value")
                or ""
            ).strip()
            vin_value = (
                driver.find_element(By.ID, ASKO_VEHICLE_FIELDS["vin"])
                .get_attribute("value")
                or ""
            ).strip()
            certificate_value = (
                driver.find_element(By.ID, ASKO_VEHICLE_FIELDS["registration_certificate"])
                .get_attribute("value")
                or ""
            ).strip()
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""

            combined = " ".join([selected_value, vin_value, certificate_value, body_text])
            combined_norm = self._normalize_vehicle_reg_number(combined)

            # Основной признак: найденный/выбранный автомобиль содержит госномер.
            if reg_number_norm and reg_number_norm in combined_norm:
                return True

            # Запасной признак: после выбора ТС ASKO подтянул VIN или СРТС.
            if vin_value or certificate_value:
                return True

            return False

        try:
            wait.until(vehicle_selected)
        except Exception as exc:
            selected_value = self._read_input_value(ASKO_VEHICLE_FIELDS["selected_vehicle"])
            vin_value = self._read_input_value(ASKO_VEHICLE_FIELDS["vin"])
            certificate_value = self._read_input_value(ASKO_VEHICLE_FIELDS["registration_certificate"])
            raise RuntimeError(
                "ASKO: автомобиль не выбран после ручного поиска. "
                f"Ожидали госномер {reg_number}. "
                f"Результат: {selected_value!r}; "
                f"VIN: {vin_value!r}; "
                f"СРТС: {certificate_value!r}."
            ) from exc

        selected_value = self._read_input_value(ASKO_VEHICLE_FIELDS["selected_vehicle"])
        vin_value = self._read_input_value(ASKO_VEHICLE_FIELDS["vin"])
        certificate_value = self._read_input_value(ASKO_VEHICLE_FIELDS["registration_certificate"])

        self.log(
            "ASKO: ТС найдено после ручного поиска. "
            f"Результат: {selected_value or 'не заполнен'}; "
            f"VIN: {vin_value or 'не заполнен'}; "
            f"СРТС: {certificate_value or 'не заполнен'}"
        )

    def _normalize_vehicle_reg_number(self, value: str) -> str:
        return "".join(ch for ch in str(value or "").upper() if ch.isalnum())

    def _fill_vehicle_details_after_selection(self) -> None:
        """
        Заполняет только поля, которые должны меняться после ручного выбора ТС.

        Не меняем подтянутые ASKO значения: госномер, VIN, выбранный автомобиль,
        тип/марку/модель и прочие поля. Год выпуска только сверяем с Bitrix.
        """
        certificate = str(getattr(self.deal, "registration_certificate", "") or "").strip()
        certificate_issue_date = self._vehicle_certificate_issue_date_value()
        country_value = self._map_vehicle_registration_country(
            getattr(self.deal, "vehicle_registration_country", "")
        )

        self._verify_vehicle_year_matches_bitrix()
        self._safe_set(ASKO_VEHICLE_FIELDS["registration_certificate"], certificate)
        self._safe_set(
            ASKO_VEHICLE_FIELDS["registration_certificate_issue_date"],
            certificate_issue_date,
        )
        self._select_asko_period(
            ASKO_VEHICLE_FIELDS["registration_region"],
            ASKO_TEMPORARY_ENTRY_REGION,
            label="Регион регистрации",
            require_click_confirmation=True,
        )
        self._verify_asko_combo_or_raise(
            ASKO_VEHICLE_FIELDS["registration_region"],
            ASKO_TEMPORARY_ENTRY_REGION,
            "Регион регистрации",
        )
        self._sleep_short(0.5)
        self._select_asko_period(
            ASKO_VEHICLE_FIELDS["registration_country"],
            country_value,
            label="Страна регистрации ТС",
            require_click_confirmation=True,
        )
        self._verify_asko_combo_or_raise(
            ASKO_VEHICLE_FIELDS["registration_country"],
            country_value,
            "Страна регистрации ТС",
        )

        self.log(

            "ASKO: поля ТС после выбора автомобиля обработаны: "
            f"СРТС={certificate or 'пусто'}, "
            f"дата выдачи СРТС={certificate_issue_date or 'пусто'}, "
            f"регион={ASKO_TEMPORARY_ENTRY_REGION}, "
            f"страна={country_value}. Остальные поля ТС не менялись."
        )


    def _vehicle_certificate_issue_date_value(self) -> str:
        """Возвращает дату выдачи СРТС для поля ASKO ext-comp-1995.

        В текущей выгрузке Bitrix отдельного поля даты выдачи СРТС нет,
        поэтому используем дату начала страхования как безопасный заполняемый
        источник вместо того, чтобы оставлять обязательное поле пустым.
        Если extract_deal() позже начнёт отдавать registration_certificate_issue_date,
        оно будет использовано автоматически.
        """
        explicit_value = str(
            getattr(self.deal, "registration_certificate_issue_date", "") or ""
        ).strip()
        if explicit_value:
            return explicit_value

        return str(getattr(self.deal, "start_date", "") or "").strip()

    def _verify_vehicle_year_matches_bitrix(self) -> None:

        """Нефатально сверяет год ASKO с Bitrix, дожидаясь загрузки поля ASKO."""
        import time
        bitrix_year = self._normalize_year(getattr(self.deal, "vehicle_year", ""))

        if not bitrix_year:
            self.log("ASKO: год ТС в Bitrix пустой, сверка ext-comp-1996 пропущена.")
            return

        asko_year = ""
        deadline = time.time() + 15

        while time.time() < deadline:
            asko_year = self._normalize_year(
                self._read_input_value(ASKO_VEHICLE_FIELDS["vehicle_year"])
            )
            if asko_year:
                break
            self._sleep_short(0.5)

        if not asko_year:
            self.log(
                "ASKO: предупреждение — поле года ТС ext-comp-1996 ещё пустое после ожидания. "
                f"В Bitrix UF_CRM_1686152614718 указан год {bitrix_year}. "
                "Робот продолжает заполнение без прерывания."
            )
            return

        if asko_year != bitrix_year:
            self.log(
                "ASKO: предупреждение — год ТС в выбранном автомобиле не совпадает с Bitrix. "
                f"ASKO ext-comp-1996: {asko_year}; "
                f"Bitrix UF_CRM_1686152614718: {bitrix_year}. "
                "Робот продолжает заполнение без прерывания; оператор должен проверить выбранный автомобиль."
            )
            return


        self.log(f"ASKO: год ТС сверен с Bitrix ← {bitrix_year}")

    def _normalize_year(self, value) -> str:
        value = str(value or "")
        digits = "".join(ch for ch in value if ch.isdigit())
        return digits[:4]


    def _map_vehicle_registration_country(self, value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ASKO_DEFAULT_REGISTRATION_COUNTRY

        if raw in BITRIX_COUNTRY_ID_TO_ASKO_REGISTRATION_COUNTRY:
            return BITRIX_COUNTRY_ID_TO_ASKO_REGISTRATION_COUNTRY[raw]

        lowered = raw.lower()
        for needle, mapped in BITRIX_COUNTRY_VALUE_TO_ASKO_REGISTRATION_COUNTRY.items():
            if needle in lowered:
                return mapped

        return ASKO_DEFAULT_REGISTRATION_COUNTRY

    def _select_asko_combo_text(self, element_id: str, text: str, label: str) -> None:
        if not text:
            return

        self._select_asko_period(element_id, text, label=label)
        self.log(f"ASKO: {label} выбран и подтверждён ← {text}")


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

    def _normalize_combo_text(self, value) -> str:
        return " ".join(str(value or "").split()).casefold()

    def _verify_asko_combo_selected(self, element_id: str, expected_text: str) -> bool:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        expected = self._normalize_combo_text(expected_text)
        if not expected:
            return True

        def selected(driver) -> bool:
            values = driver.execute_script(
                """
                const id = arguments[0];
                const values = [];

                function add(value) {
                    if (value !== undefined && value !== null) {
                        const text = String(value).replace(/\\s+/g, " ").trim();
                        if (text) values.push(text);
                    }
                }

                const el = document.getElementById(id);
                if (el) {
                    add(el.value);
                    add(el.getAttribute("value"));
                    add(el.textContent);
                }

                if (window.Ext && Ext.getCmp) {
                    const cmp = Ext.getCmp(id);
                    if (cmp) {
                        if (cmp.getRawValue) add(cmp.getRawValue());
                        if (cmp.getValue) add(cmp.getValue());
                        if (cmp.lastSelectionText) add(cmp.lastSelectionText);

                        const store = cmp.getStore ? cmp.getStore() : null;
                        const value = cmp.getValue ? cmp.getValue() : null;
                        if (store && value !== undefined && value !== null) {
                            const valueField = cmp.valueField || "value";
                            const displayField = cmp.displayField || "text";
                            const index = store.findBy(function(rec) {
                                return String(rec.get(valueField)) === String(value);
                            });
                            if (index >= 0) {
                                const rec = store.getAt(index);
                                add(rec.get(displayField));
                                add(rec.get(valueField));
                            }
                        }
                    }
                }

                return Array.from(new Set(values));
                """,
                element_id,
            ) or []

            return any(self._normalize_combo_text(value) == expected for value in values)

        try:
            WebDriverWait(self.driver, 5).until(selected)
            return True
        except Exception:
            try:
                element = WebDriverWait(self.driver, 1).until(
                    EC.presence_of_element_located((By.ID, element_id))
                )
                current = element.get_attribute("value") or ""
            except Exception:
                current = ""
            self.log(
                f"ASKO: проверка выпадающего списка {element_id} не подтвердила выбор "
                f"{expected_text!r}; сейчас в поле: {current!r}."
            )
            return False


    def _verify_asko_combo_or_raise(self, element_id: str, expected_text: str, label: str) -> None:
        if self._verify_asko_combo_selected(element_id, expected_text):
            self.log(f"ASKO: {label} подтверждён ← {expected_text}")
            return

        raise RuntimeError(
            f"ASKO: {label} не подтвердился после выбора из выпадающего списка. "
            f"Ожидали: {expected_text}"
        )

    def _select_asko_period(
        self,
        element_id: str,
        term_text: str,
        label: str = "Период страхования",
        require_click_confirmation: bool = False,
    ) -> None:
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

        ext_verified = False

        if ext_result and ext_result.get("ok"):
            try:
                element = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
                element.click()
                element.send_keys(Keys.ENTER)
                element.send_keys(Keys.TAB)
            except Exception:
                pass

            ext_verified = self._verify_asko_combo_selected(element_id, term_text)
            if ext_verified and not require_click_confirmation:
                self.log(f"ASKO: {label} выбран через ExtJS ← {term_text}")
                return

            if ext_verified:
                self.log(
                    f"ASKO: {label} установлен через ExtJS, подтверждаю выбор кликом ← {term_text}"
                )
            else:
                self.log(
                    f"ASKO: {label} после ExtJS-выбора не подтвердился, "
                    "повторяю выбор кликом из списка."
                )
        else:
            self.log(f"ASKO: ExtJS-выбор выпадающего списка не сработал: {ext_result}")

        element = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
        element.click()

        try:
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.BACKSPACE)
            element.send_keys(term_text)
        except Exception:
            pass

        clicked_by_js = self.driver.execute_script(
            """
            const expected = String(arguments[0]).replace(/\\s+/g, " ").trim().toLowerCase();

            function visible(el) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none"
                    && style.visibility !== "hidden"
                    && rect.width > 0
                    && rect.height > 0;
            }

            const nodes = Array.from(document.querySelectorAll(
                ".x-combo-list-item, .x-boundlist-item, .x-list-item, " +
                ".x-combo-list-inner div, .x-layer div"
            ));

            const candidates = nodes
                .filter(visible)
                .map(el => ({
                    el,
                    text: (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim(),
                    rect: el.getBoundingClientRect(),
                }))
                .filter(item => item.text.toLowerCase() === expected);

            candidates.sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));

            if (!candidates.length) {
                return false;
            }

            const chosen = candidates[0].el;
            chosen.scrollIntoView({block: "center", inline: "center"});
            chosen.dispatchEvent(new MouseEvent("mousedown", {bubbles: true, cancelable: true, view: window}));
            chosen.click();
            chosen.dispatchEvent(new MouseEvent("mouseup", {bubbles: true, cancelable: true, view: window}));
            return true;
            """,
            term_text,
        )

        if not clicked_by_js:
            option_xpath = (
                f"//*[contains(@class, 'x-combo-list-item') "
                f"or contains(@class, 'x-boundlist-item') "
                f"or contains(@class, 'x-list-item') "
                f"or self::div]"
                f"[normalize-space(.)='{term_text}']"
            )

            try:
                option = wait.until(EC.element_to_be_clickable((By.XPATH, option_xpath)))
                ActionChains(self.driver).move_to_element(option).click(option).perform()
                clicked_by_js = True
            except Exception as exc:
                if ext_verified:
                    self.log(
                        f"ASKO: {label} уже подтверждён через ExtJS; "
                        f"видимый пункт списка не кликнулся: {exc}"
                    )
                else:
                    raise

        try:
            element = wait.until(EC.element_to_be_clickable((By.ID, element_id)))
            element.send_keys(Keys.ENTER)
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

        self._verify_asko_combo_or_raise(element_id, term_text, label)

        if clicked_by_js:
            self.log(f"ASKO: {label} выбран кликом из списка ← {term_text}")
        else:
            self.log(f"ASKO: {label} выбран через ExtJS без видимого клика ← {term_text}")

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


