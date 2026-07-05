from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


WARTA_URL = "https://eagent.warta.pl"


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
            print("Ищу кнопку Sprzedaż...")

            page.get_by_text("Sprzedaż", exact=True).wait_for(timeout=15000)
            page.get_by_text("Sprzedaż", exact=True).click()

            print("Кнопка Sprzedaż нажата.")

        except PlaywrightTimeoutError:
            print("Не нашёл элемент Sprzedaż по тексту.")
            print("Пробую другой способ...")

            try:
                page.locator("a:has-text('Sprzedaż')").first.click(timeout=10000)
                print("Кнопка Sprzedaż нажата вторым способом.")
            except Exception as error:
                print("Не удалось нажать Sprzedaż.")
                print("Ошибка:")
                print(error)

        input("Нажмите Enter, чтобы закрыть браузер...")
        browser.close()


if __name__ == "__main__":
    main()