import queue
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from bitrix_client import extract_deal_id, normalize_webhook_url, get_deal, prepare_data
from dom_capture import save_capture


class WartaWorker(threading.Thread):
    def __init__(self, log_callback, state_callback):
        super().__init__(daemon=True)
        self.log_callback = log_callback
        self.state_callback = state_callback
        self.commands = queue.Queue()

        self.playwright = None
        self.browser = None
        self.page = None
        self.stage = "idle"
        self.current_data = None
        self.settings = None

    def submit(self, command: str, payload: dict):
        self.commands.put((command, payload))

    def log(self, text: str):
        self.log_callback(text)

    def set_state(self, text: str):
        self.state_callback(text)

    def run(self):
        while True:
            command, payload = self.commands.get()
            try:
                if command == "start_or_continue":
                    self.handle_start_or_continue(payload)
                elif command == "capture":
                    self.handle_capture(payload)
                elif command == "reset":
                    self.stage = "idle"
                    self.current_data = None
                    self.set_state("Сброшено. Можно начать заново.")
                elif command == "shutdown":
                    self.close_all()
                    break
            except Exception as error:
                self.log(f"ОШИБКА: {error}")
                self.set_state("Ошибка. Исправьте данные или сделайте снимок страницы.")

    def close_all(self):
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    def ensure_page(self, settings: dict):
        self.settings = settings

        if self.playwright is None:
            self.playwright = sync_playwright().start()

        if self.browser is None:
            self.browser = self.playwright.chromium.launch(
                headless=False,
                slow_mo=220,
            )
            self.page = self.browser.new_page()
            self.page.goto(settings["warta_url"], wait_until="domcontentloaded")
            self.log("Открыт браузер WARTA.")
            self.try_login(settings)
            self.stage = "wait_2fa"
            self.set_state(
                "Введите 2FA в браузере. После главной страницы нажмите "
                "«Начать / Продолжить» ещё раз."
            )
            return

        if self.page is None:
            self.page = self.browser.new_page()
            self.page.goto(settings["warta_url"], wait_until="domcontentloaded")

    def try_login(self, settings: dict):
        login = settings.get("warta_login", "").strip()
        password = settings.get("warta_password", "").strip()

        if not login or not password:
            self.log("Логин/пароль WARTA не заполнены. Войдите вручную.")
            return

        login_selectors = [
            "input[name='username']",
            "input[name='login']",
            "input[type='text']",
            "input[type='email']",
        ]

        password_selectors = [
            "input[name='password']",
            "input[type='password']",
        ]

        login_ok = False
        for selector in login_selectors:
            try:
                loc = self.page.locator(selector).first
                loc.wait_for(timeout=2500)
                loc.fill(login)
                login_ok = True
                self.log("Логин WARTA введён.")
                break
            except Exception:
                pass

        password_ok = False
        for selector in password_selectors:
            try:
                loc = self.page.locator(selector).first
                loc.wait_for(timeout=2500)
                loc.fill(password)
                password_ok = True
                self.log("Пароль WARTA введён.")
                break
            except Exception:
                pass

        if login_ok and password_ok:
            self.page.keyboard.press("Enter")
            self.log("Форма входа отправлена.")
        else:
            self.log("Автологин не сработал. Войдите вручную.")

    def handle_start_or_continue(self, payload: dict):
        settings = payload["settings"]
        deal_url = payload["deal_url"].strip()

        if self.stage == "idle":
            if not deal_url:
                raise ValueError("Вставьте ссылку на сделку Bitrix24.")

            webhook = normalize_webhook_url(settings.get("bitrix_webhook_url", ""))
            deal_id = extract_deal_id(deal_url)

            self.log(f"Загружаю сделку Bitrix24 ID {deal_id}...")

            deal = get_deal(webhook, deal_id)
            self.current_data = prepare_data(webhook, deal)

            self.log("Данные из Bitrix24:")
            self.log(f"  Номер ТС: {self.current_data['reg_number']}")
            self.log(f"  VIN: {self.current_data['vin']}")
            self.log(f"  Марка/модель: {self.current_data['mark_model']}")
            self.log(f"  Год: {self.current_data['year']}")
            self.log(
                f"  Начало страховки: "
                f"{self.current_data.get('begin_date_warta') or '[не определено]'}"
            )
            self.log(f"  Срок дней: {self.current_data['days'] or '[не определён]'}")
            self.log(
                f"  Страна: "
                f"{self.current_data.get('country_warta') or '[не определена]'}"
            )
            self.log(f"  Фамилия: {self.current_data['surname']}")
            self.log(f"  Имя: {self.current_data['name']}")
            self.log(f"  Дата рождения: {self.current_data.get('birthdate') or '[не определена]'}")

            self.ensure_page(settings)
            return

        if self.stage == "wait_2fa":
            self.log("Продолжаю после 2FA.")
            self.go_to_oc_graniczne()
            self.fill_fast_vehicle_check()
            self.fill_vehicle_basic_after_vin_part_1()
            self.stage = "wait_make_confirm"
            self.set_state(
                "Проверьте и подтвердите выбор Marka в WARTA. "
                "Потом нажмите «Начать / Продолжить»."
            )
            return

        if self.stage == "wait_make_confirm":
            self.fill_vehicle_basic_after_vin_part_2()
            self.stage = "wait_vehicle_manual"
            self.set_state(
                "Выберите руками Paliwo, Model и Typ / Wersja pojazdu według "
                "Info-Ekspert. Потом нажмите «Начать / Продолжить»."
            )
            return

        if self.stage == "wait_vehicle_manual":
            self.fill_client_type()
            self.stage = "wait_citizenship"
            self.set_state(
                "Выберите руками Kraj obywatelstwa. "
                "Потом нажмите «Начать / Продолжить»."
            )
            return

        if self.stage == "wait_citizenship":
            self.fill_person_basic()
            self.fill_insurance_period()
            self.stage = "wait_page3"
            self.set_state(
                "Проверьте имя, дату рождения и Okres ochrony. "
                "Затем перейдите на страницу 3 и нажмите «Начать / Продолжить»."
            )
            return

        if self.stage == "wait_page3":
            self.fill_document_and_consents()
            self.stage = "done"
            self.set_state("Заполнено до согласий/документа. Браузер оставлен открытым.")
            self.log("Готово. Браузер не закрывается.")
            return

        if self.stage == "done":
            self.set_state(
                "Сценарий уже выполнен. Для новой сделки нажмите «Сбросить» "
                "и затем «Начать»."
            )
            return

    def click_text(self, text: str, timeout=20000):
        locator = self.page.get_by_text(text, exact=True)
        locator.wait_for(timeout=timeout)
        locator.click()
        self.log(f"Нажато: {text}")

    def click_selector(self, selector: str, label: str, timeout=20000):
        locator = self.page.locator(selector)
        locator.wait_for(timeout=timeout)
        locator.scroll_into_view_if_needed()
        locator.click()
        self.log(f"Нажато: {label}")

    def fill_selector(
        self,
        selector: str,
        value: str,
        label: str,
        timeout=20000,
        press_enter=False,
        verify=False,
    ):
        if not value:
            raise ValueError(f"Пустое значение для поля: {label}")

        locator = self.page.locator(selector)
        locator.wait_for(timeout=timeout)
        locator.scroll_into_view_if_needed()
        locator.click()
        self.page.wait_for_timeout(300)

        try:
            locator.fill("")
            locator.fill(value)
        except Exception:
            self.page.keyboard.press("Control+A")
            self.page.keyboard.type(value)

        self.page.wait_for_timeout(300)

        if press_enter:
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(500)

        if verify:
            try:
                value_after = locator.input_value().strip()
            except Exception:
                value_after = ""

            if value_after != value:
                raise ValueError(
                    f"Поле '{label}' не заполнилось корректно. "
                    f"Ожидалось: '{value}', фактически: '{value_after}'"
                )

        self.log(f"Заполнено: {label} = {value}")

    def fill_input_near_text(
        self,
        label_contains: str,
        value: str,
        exact_selector: str | None = None,
        verify=False,
    ) -> bool:
        if not value:
            return False

        if exact_selector:
            try:
                self.fill_selector(
                    exact_selector,
                    value,
                    label_contains,
                    timeout=5000,
                    verify=verify,
                )
                return True
            except Exception:
                pass

        script = """
        ({label}) => {
            function visible(el) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style &&
                    style.visibility !== 'hidden' &&
                    style.display !== 'none' &&
                    rect.width > 0 &&
                    rect.height > 0;
            }

            function textOf(el) {
                if (!el) return '';
                return (el.innerText || el.textContent || '')
                    .replace(/\\s+/g, ' ')
                    .trim();
            }

            const inputs = Array.from(
                document.querySelectorAll('input, textarea')
            ).filter(visible);

            const labelLower = label.toLowerCase();

            for (const input of inputs) {
                const box = input.closest('div, label, section, fieldset, tr, td');
                const txt = textOf(box).toLowerCase();

                const attrs = [
                    input.getAttribute('id') || '',
                    input.getAttribute('name') || '',
                    input.getAttribute('placeholder') || '',
                    input.getAttribute('aria-label') || '',
                    input.getAttribute('ng-model') || ''
                ].join(' ').toLowerCase();

                if (txt.includes(labelLower) || attrs.includes(labelLower)) {
                    input.scrollIntoView({block: 'center'});
                    input.focus();
                    return true;
                }
            }

            return false;
        }
        """

        ok = self.page.evaluate(script, {"label": label_contains})

        if not ok:
            self.log(f"Поле не найдено по подписи: {label_contains}")
            return False

        self.page.keyboard.press("Control+A")
        self.page.keyboard.type(value)
        self.page.wait_for_timeout(500)

        if verify:
            value_after = self.page.evaluate(
                "() => document.activeElement ? document.activeElement.value : ''"
            )
            value_after = (value_after or "").strip()

            if value_after != value:
                raise ValueError(
                    f"Поле '{label_contains}' не заполнилось корректно. "
                    f"Ожидалось: '{value}', фактически: '{value_after}'"
                )

        self.log(f"Заполнено по подписи: {label_contains} = {value}")
        self.page.wait_for_timeout(700)
        return True

    def fill_search_near_text(
        self,
        label_contains: str,
        value: str,
        exact_selector: str | None = None,
        verify=False,
    ) -> bool:
        if not value:
            return False

        if exact_selector:
            try:
                self.fill_selector(
                    exact_selector,
                    value,
                    label_contains,
                    timeout=5000,
                    verify=verify,
                )
                return True
            except Exception:
                pass

        return self.fill_input_near_text(
            label_contains,
            value,
            verify=verify,
        )

    def select_text_option_near(self, label_contains: str, option_text: str) -> bool:
        try:
            self.fill_search_near_text(label_contains, option_text)
            self.page.wait_for_timeout(700)
            self.page.get_by_text(option_text, exact=True).click(timeout=5000)
            self.log(f"Выбрано: {label_contains} = {option_text}")
            return True
        except Exception:
            self.log(f"Не удалось выбрать {label_contains} = {option_text}. Выберите вручную.")
            return False

    def go_to_oc_graniczne(self):
        self.click_text("Sprzedaż")
        self.page.wait_for_timeout(1200)

        self.click_text("Komunikacyjne")
        self.page.wait_for_timeout(1500)

        self.click_selector("#options-MOTOR_OCG", "OC graniczne")
        self.page.wait_for_timeout(1000)

        self.click_selector("#customer-needs-analysis-APK_OCG-TAK", "TAK dla OC graniczne")
        self.page.wait_for_timeout(1000)

    def fill_fast_vehicle_check(self):
        data = self.current_data

        self.fill_selector(
            "#fast-input-registration-number",
            data["reg_number"],
            "Numer rejestracyjny",
            verify=True,
        )
        self.click_selector("#fast-input-check", "SPRAWDŹ po numerze")
        self.page.wait_for_timeout(2500)

        self.fill_selector(
            "#fast-input-vin",
            data["vin"],
            "VIN",
            verify=True,
        )
        self.click_selector("#fast-input-check", "SPRAWDŹ po VIN")
        self.page.wait_for_timeout(3500)

    def fill_vehicle_basic_after_vin_part_1(self):
        data = self.current_data

        if data["is_passenger_car"]:
            self.fill_selector(
                "#calculation-vehicle-type-select-search",
                "Samochód osobowy",
                "Rodzaj pojazdu",
            )
            self.page.wait_for_timeout(1200)

            try:
                self.page.get_by_text("Samochód osobowy", exact=True).last.click(timeout=5000)
                self.log("Выбрано из списка: Rodzaj pojazdu = Samochód osobowy")
            except Exception:
                self.log("Не удалось автоматически выбрать Samochód osobowy из списка. Выберите вручную.")

            self.page.wait_for_timeout(1000)

        self.fill_selector(
            "#calculation-vehicle-first-registration-date",
            data["first_registration_date"],
            "Data pierwszej rejestracji",
            press_enter=True,
            verify=True,
        )
        self.page.wait_for_timeout(1000)

        self.fill_selector(
            "#calculation-vehicle-ie-make-select-search",
            data["brand_query"],
            "Marka",
        )
        self.page.wait_for_timeout(1200)

    def fill_vehicle_basic_after_vin_part_2(self):
        data = self.current_data

        self.fill_selector(
            "#calculation-vehicle-ie-production-year-select-search",
            data["year"],
            "Rok produkcji",
            press_enter=True,
        )
        self.page.wait_for_timeout(1000)

    def fill_client_type(self):
        self.select_text_option_near("Rodzaj klienta", "Osoba fizyczna")
        self.page.wait_for_timeout(1000)

    def fill_person_basic(self):
        data = self.current_data

        self.fill_input_near_text("Nazwisko", data["surname"], verify=True)
        self.page.wait_for_timeout(800)

        self.fill_input_near_text("Imię", data["name"], verify=True)
        self.page.wait_for_timeout(800)

        self.fill_input_near_text("Data urodzenia", data["birthdate"], verify=True)
        self.page.wait_for_timeout(800)

    def ensure_other_period_selected(self):
        other_button = self.page.locator("#insurance-period-switch-other")
        other_button.wait_for(timeout=10000)
        other_button.scroll_into_view_if_needed()

        class_attr = other_button.get_attribute("class") or ""
        aria_pressed = other_button.get_attribute("aria-pressed") or ""
        aria_selected = other_button.get_attribute("aria-selected") or ""

        is_selected_before = (
            "active" in class_attr.lower()
            or "selected" in class_attr.lower()
            or aria_pressed.lower() == "true"
            or aria_selected.lower() == "true"
        )

        if is_selected_before:
            self.log("Okres ochrony: INNY уже выбран.")
        else:
            other_button.click()
            self.page.wait_for_timeout(700)
            self.log("Okres ochrony: выбран INNY.")

        date_input = self.page.locator("#insurance-period-begin")
        date_input.wait_for(timeout=10000)
        date_input.scroll_into_view_if_needed()

        if not date_input.is_visible():
            raise ValueError("После выбора INNY поле даты начала страховки не видно.")

        if not date_input.is_enabled():
            raise ValueError("После выбора INNY поле даты начала страховки недоступно.")

        class_attr_after = other_button.get_attribute("class") or ""
        aria_pressed_after = other_button.get_attribute("aria-pressed") or ""
        aria_selected_after = other_button.get_attribute("aria-selected") or ""

        is_selected_after = (
            "active" in class_attr_after.lower()
            or "selected" in class_attr_after.lower()
            or aria_pressed_after.lower() == "true"
            or aria_selected_after.lower() == "true"
        )

        if is_selected_after:
            self.log("Okres ochrony: подтверждено, что INNY выбран.")
        else:
            self.log("Okres ochrony: поле даты доступно; продолжаю заполнение INNY.")

    def fill_insurance_period(self):
        data = self.current_data

        begin_date = data.get("begin_date_warta", "")
        days = data.get("days", "")

        if not begin_date:
            raise ValueError("Нет даты начала страховки для WARTA: begin_date_warta пустое.")

        if not days:
            raise ValueError("Нет срока страхования для WARTA: days пустое.")

        self.ensure_other_period_selected()

        self.fill_selector(
            "#insurance-period-begin",
            begin_date,
            "Początek okresu ochrony",
            press_enter=True,
            verify=True,
        )
        self.page.wait_for_timeout(800)

        self.fill_input_near_text("Liczba dni ochrony", days, verify=True)
        self.page.wait_for_timeout(800)

    def fill_document_and_consents(self):
        data = self.current_data

        if data["passport"]:
            self.fill_input_near_text("Dokument tożsamości", data["passport"], verify=True)
            self.page.wait_for_timeout(800)

            try:
                self.page.get_by_text("Paszport", exact=True).click(timeout=5000)
                self.log("Выбрано: Paszport")
            except Exception:
                self.log("Paszport не выбран автоматически. Выберите вручную.")

        self.log(
            "Согласия: точные selector'ы нужно уточнить снимком страницы 3. "
            "Автоматически не нажимаю спорные согласия."
        )

    def handle_capture(self, payload: dict):
        settings = payload["settings"]
        name = payload.get("name") or "page"

        self.ensure_page(settings)

        paths = save_capture(self.page, name, Path("captures"))

        self.log("Снимок сохранён:")
        for p in paths:
            self.log(f"  {p}")

        self.set_state("Снимок сохранён.")