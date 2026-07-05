from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


WARTA_URL = "https://eagent.warta.pl"

REG_NUMBER = "70KE077"
VIN = "5UX43DP08P9R46065"


def wait_short(page, ms=800):
    page.wait_for_timeout(ms)


def click_visible_text(page, text, timeout=20000):
    page.get_by_text(text, exact=True).wait_for(timeout=timeout)
    page.get_by_text(text, exact=True).click()
    print(f"Нажато: {text}")


def click_selector(page, selector, description, timeout=20000):
    page.locator(selector).wait_for(timeout=timeout)
    page.locator(selector).scroll_into_view_if_needed()
    page.locator(selector).click()
    print(f"Нажато: {description}")


def fill_selector(page, selector, value, description, timeout=20000):
    page.locator(selector).wait_for(timeout=timeout)
    page.locator(selector).scroll_into_view_if_needed()
    page.locator(selector).fill("")
    page.locator(selector).fill(value)
    print(f"Заполнено: {description} = {value}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=300
        )

        page = browser.new_page()
        page.goto(WARTA_URL, wait_until="domcontentloaded")

        print("Открылся браузер.")
        print("Войдите вручную в кабинет Warta.")
        input("После входа и появления главной страницы нажмите Enter здесь...")

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # 1. Верхнее меню Sprzedaż
        click_visible_text(page, "Sprzedaż")
        wait_short(page, 1500)

        # 2. Плитка Komunikacyjne
        click_visible_text(page, "Komunikacyjne")
        wait_short(page, 2000)

        # 3. Продукт OC graniczne
        click_selector(page, "#options-MOTOR_OCG", "OC graniczne")
        wait_short(page, 1000)

        # 4. Ответ TAK именно для OC graniczne
        click_selector(page, "#customer-needs-analysis-APK_OCG-TAK", "TAK для OC graniczne")
        wait_short(page, 1000)

        # 5. Номер регистрации
        fill_selector(
            page,
            "#fast-input-registration-number",
            REG_NUMBER,
            "Numer rejestracyjny"
        )

        # 6. Проверить номер
        click_selector(page, "#fast-input-check", "SPRAWDŹ после номера")
        wait_short(page, 2500)

        # 7. VIN
        fill_selector(
            page,
            "#fast-input-vin",
            VIN,
            "VIN"
        )

        # 8. Проверить VIN
        click_selector(page, "#fast-input-check", "SPRAWDŹ после VIN")
        wait_short(page, 3000)

        print("Сценарий выполнен до проверки VIN.")
        print("Дальше робот ничего не нажимает. Проверьте страницу вручную.")
        input("Нажмите Enter, чтобы закрыть браузер...")

        browser.close()


if __name__ == "__main__":
    main()