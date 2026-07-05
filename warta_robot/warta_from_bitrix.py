import re
import getpass
import requests
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


WARTA_URL = "https://eagent.warta.pl"


BITRIX_FIELDS = {
    "reg_number": "UF_CRM_1686152485641",
    "mark_model": "UF_CRM_1686152515152",
    "vehicle_type": "UF_CRM_1686152567597",
    "year": "UF_CRM_1686152614718",
    "vin": "UF_CRM_1686152659867",
    "fuel": "UF_CRM_1686152745455",
}


def normalize_webhook_url(url: str) -> str:
    url = url.strip()
    if not url.endswith("/"):
        url += "/"
    return url


def extract_deal_id(deal_url: str) -> str:
    match = re.search(r"/crm/deal/details/(\d+)/?", deal_url)
    if not match:
        raise ValueError("Не смог найти ID сделки в ссылке Bitrix24.")
    return match.group(1)


def bitrix_call(webhook_url: str, method: str, params: dict | None = None) -> dict:
    response = requests.post(
        webhook_url + method,
        json=params or {},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(f"Bitrix API error: {data.get('error')} — {data.get('error_description')}")

    return data["result"]


def get_deal(webhook_url: str, deal_id: str) -> dict:
    return bitrix_call(
        webhook_url,
        "crm.deal.get",
        {"id": deal_id},
    )


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def prepare_vehicle_data(deal: dict) -> dict:
    reg_number = clean_text(deal.get(BITRIX_FIELDS["reg_number"])).replace(" ", "").upper()
    vin = clean_text(deal.get(BITRIX_FIELDS["vin"])).replace(" ", "").upper()
    mark_model = clean_text(deal.get(BITRIX_FIELDS["mark_model"])).upper()
    year = clean_text(deal.get(BITRIX_FIELDS["year"]))

    brand_query = mark_model[:3].strip()

    result = {
        "reg_number": reg_number,
        "vin": vin,
        "mark_model": mark_model,
        "brand_query": brand_query,
        "year": year,
    }

    missing = []

    if not result["reg_number"]:
        missing.append("Numer pojazdu / номер ТС")

    if not result["vin"]:
        missing.append("VIN")

    if not result["mark_model"]:
        missing.append("Marka i model pojazdu")

    if missing:
        raise ValueError("В сделке не заполнены обязательные поля: " + ", ".join(missing))

    if len(result["vin"]) != 17:
        raise ValueError(f"VIN должен быть 17 символов, сейчас: {result['vin']}")

    return result


def click_text(page, text: str, timeout=20000):
    page.get_by_text(text, exact=True).wait_for(timeout=timeout)
    page.get_by_text(text, exact=True).click()
    print(f"Нажато: {text}")


def click_selector(page, selector: str, label: str, timeout=20000):
    page.locator(selector).wait_for(timeout=timeout)
    page.locator(selector).scroll_into_view_if_needed()
    page.locator(selector).click()
    print(f"Нажато: {label}")


def fill_selector(page, selector: str, value: str, label: str, timeout=20000):
    page.locator(selector).wait_for(timeout=timeout)
    page.locator(selector).scroll_into_view_if_needed()
    page.locator(selector).fill("")
    page.locator(selector).fill(value)
    print(f"Заполнено: {label} = {value}")


def try_fill_login(page, login: str, password: str):
    """
    Пытается заполнить логин/пароль.
    Если Warta поменяет форму, можно войти вручную.
    """
    try:
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

        login_filled = False
        for selector in login_selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(timeout=3000)
                locator.fill(login)
                login_filled = True
                print("Логин введён.")
                break
            except Exception:
                pass

        password_filled = False
        for selector in password_selectors:
            locator = page.locator(selector).first
            try:
                locator.wait_for(timeout=3000)
                locator.fill(password)
                password_filled = True
                print("Пароль введён.")
                break
            except Exception:
                pass

        if login_filled and password_filled:
            try:
                page.keyboard.press("Enter")
                print("Отправлена форма входа.")
            except Exception:
                pass
        else:
            print("Не удалось уверенно найти поля логина/пароля. Войдите вручную.")

    except Exception as error:
        print(f"Автозаполнение логина не выполнено: {error}")
        print("Войдите вручную.")


def go_to_oc_graniczne(page):
    click_text(page, "Sprzedaż")
    page.wait_for_timeout(1200)

    click_text(page, "Komunikacyjne")
    page.wait_for_timeout(1500)

    click_selector(page, "#options-MOTOR_OCG", "OC graniczne")
    page.wait_for_timeout(1000)

    click_selector(page, "#customer-needs-analysis-APK_OCG-TAK", "TAK dla OC graniczne")
    page.wait_for_timeout(1000)


def fill_fast_vehicle_check(page, vehicle: dict):
    fill_selector(
        page,
        "#fast-input-registration-number",
        vehicle["reg_number"],
        "Numer rejestracyjny",
    )

    click_selector(page, "#fast-input-check", "SPRAWDŹ po numerze")
    page.wait_for_timeout(2500)

    fill_selector(
        page,
        "#fast-input-vin",
        vehicle["vin"],
        "VIN",
    )

    click_selector(page, "#fast-input-check", "SPRAWDŹ po VIN")
    page.wait_for_timeout(3500)


def find_brand_input_and_fill(page, brand_query: str):
    """
    После проверки VIN Warta показывает дальнейшие поля автомобиля.
    Точный selector поля marki надо подтвердить следующим снимком.
    Поэтому здесь безопасный вариант:
    - ищем input/search, где рядом есть Marka / Model / Wybierz;
    - вводим первые 3 символа;
    - останавливаемся.
    """
    possible_selectors = [
        "input[name*='brand']",
        "input[name*='mark']",
        "input[id*='brand']",
        "input[id*='mark']",
        "input[placeholder='Wybierz']",
        "input[type='search']",
    ]

    for selector in possible_selectors:
        locators = page.locator(selector)
        count = locators.count()

        for i in range(count):
            field = locators.nth(i)
            try:
                if not field.is_visible():
                    continue

                field.scroll_into_view_if_needed()
                field.click()
                field.fill("")
                field.fill(brand_query)
                print(f"В поле марки введено: {brand_query}")
                print(f"Использован selector: {selector}, index={i}")
                return True

            except Exception:
                continue

    print("Не удалось найти поле марки автоматически.")
    print("Сделайте снимок страницы после VIN именно на блоке с маркой/моделью.")
    return False


def main():
    print("ВНИМАНИЕ: не вставляйте пароль и webhook в код. Вводите их только при запуске.")
    print("Также лучше сменить уже опубликованный пароль Warta и перевыпустить webhook Bitrix24.")
    print("")

    bitrix_webhook = normalize_webhook_url(
        getpass.getpass("Bitrix webhook URL: ").strip()
    )

    deal_url = input("Ссылка на сделку Bitrix24: ").strip()
    deal_id = extract_deal_id(deal_url)

    print(f"ID сделки: {deal_id}")
    deal = get_deal(bitrix_webhook, deal_id)
    vehicle = prepare_vehicle_data(deal)

    print("")
    print("Данные из Bitrix24:")
    print(f"Номер ТС: {vehicle['reg_number']}")
    print(f"VIN: {vehicle['vin']}")
    print(f"Марка/модель: {vehicle['mark_model']}")
    print(f"В поле марки будет введено: {vehicle['brand_query']}")
    print(f"Год: {vehicle['year']}")
    print("")

    warta_login = input("Warta login: ").strip()
    warta_password = getpass.getpass("Warta password: ")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=250,
        )

        page = browser.new_page()
        page.goto(WARTA_URL, wait_until="domcontentloaded")

        try_fill_login(page, warta_login, warta_password)

        print("")
        print("Если Warta попросила двухфакторный код — введите его вручную в браузере.")
        input("Когда после 2FA появится главная страница Warta, нажмите Enter здесь...")

        go_to_oc_graniczne(page)
        fill_fast_vehicle_check(page, vehicle)

        print("")
        print("Пробую ввести первые 3 символа марки/модели в поле марки...")
        find_brand_input_and_fill(page, vehicle["brand_query"])

        print("")
        print("Дальше выберите модель и тип топлива вручную.")
        print("Робот остановлен. Финальные действия он не выполняет.")
        input("Нажмите Enter, чтобы закрыть браузер...")

        browser.close()


if __name__ == "__main__":
    main()