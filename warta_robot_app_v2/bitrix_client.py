import re
from datetime import datetime

import requests


BITRIX_FIELDS = {
    "reg_number": "UF_CRM_1686152485641",
    "country": "UF_CRM_1686152306664",
    "mark_model": "UF_CRM_1686152515152",
    "vehicle_type": "UF_CRM_1686152567597",
    "year": "UF_CRM_1686152614718",
    "vin": "UF_CRM_1686152659867",
    "fuel": "UF_CRM_1686152745455",
    "period": "UF_CRM_1686152209741",
    "begin_date": "UF_CRM_1686152149204",
}


BITRIX_COUNTRY_ID_TO_WARTA_PL = {
    "529": "Armenia",
    "531": "Azerbejdżan",
    "123": "Białoruś",
    "523": "Gruzja",
    "385": "Kazachstan",
    "521": "Mołdawia",
    "383": "Mongolia",
    "125": "Rosja",
    "2253": "Turcja",
    "519": "Ukraina",
    "525": "Uzbekistan",
    "4779": "Zjednoczone Emiraty Arabskie",
    "4785": "Egipt",
    "4791": "Irak",
    "4793": "Iran",
    "4801": "Libia",
    "4811": "Syria",
    "4815": "Stany Zjednoczone",

    "517": "Estonia",
    "527": "Kirgistan",
    "515": "Łotwa",
    "513": "Litwa",
    "247": "Polska",
    "1103": "Czechy",
    "4781": "Bahrajn",
    "4783": "Algieria",
    "4787": "Wielka Brytania",
    "4789": "Izrael",
    "4795": "Jordania",
    "4797": "Kuwejt",
    "4799": "Liban",
    "4803": "Maroko",
    "4805": "Oman",
    "4807": "Katar",
    "4809": "Arabia Saudyjska",
    "4813": "Tunezja",
    "4817": "Jemen",

    # Другая страна — не автозаполняем.
    "411": "",
}


BITRIX_PERIOD_ID_TO_WARTA_DAYS = {
    "115": "30",    # 1 месяц
    "287": "60",    # 2 месяца
    "117": "90",    # 3 месяца
    "119": "180",   # 6 месяцев
    "121": "364",   # 12 месяцев
}


def extract_deal_id(deal_url: str) -> str:
    match = re.search(r"/crm/deal/details/(\d+)/?", deal_url.strip())
    if not match:
        raise ValueError("Не удалось найти ID сделки. Нужна ссылка вида /crm/deal/details/85149/")
    return match.group(1)


def normalize_webhook_url(url: str) -> str:
    url = (url or "").strip()

    if not url:
        raise ValueError("Bitrix24 webhook пустой.")

    if not url.endswith("/"):
        url += "/"

    return url


def bitrix_call(webhook_url: str, method: str, params: dict | None = None):
    response = requests.post(webhook_url + method, json=params or {}, timeout=30)
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            f"Bitrix API error: {data.get('error')} — {data.get('error_description')}"
        )

    return data["result"]


def get_deal(webhook_url: str, deal_id: str) -> dict:
    return bitrix_call(webhook_url, "crm.deal.get", {"id": deal_id})


def get_contact(webhook_url: str, contact_id: str | int) -> dict:
    return bitrix_call(webhook_url, "crm.contact.get", {"id": contact_id})


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def bitrix_country_id_to_warta_pl(value) -> str:
    country_id = clean_text(value)

    if not country_id:
        return ""

    country = BITRIX_COUNTRY_ID_TO_WARTA_PL.get(country_id)

    if country is None:
        raise ValueError(f"Неизвестное значение страны в Bitrix: enum ID {country_id}")

    return country


def bitrix_period_to_warta_days(value) -> str:
    period_id = clean_text(value)

    if not period_id:
        return ""

    days = BITRIX_PERIOD_ID_TO_WARTA_DAYS.get(period_id)

    if days is None:
        raise ValueError(
            f"Неподдерживаемый срок страхования в Bitrix: enum ID {period_id}. "
            "Для Warta сейчас настроены только: 1, 2, 3, 6 и 12 месяцев."
        )

    return days


def bitrix_date_to_warta_date(value) -> str:
    text = clean_text(value)

    if not text:
        return ""

    # Bitrix может вернуть 2026-07-03T00:00:00+03:00
    if "T" in text:
        text = text.split("T")[0]

    # Уже формат Warta: DD-MM-YYYY
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", text):
        return text

    # Стандартный формат Bitrix: YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d-%m-%Y")

    # Возможный формат: DD.MM.YYYY
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        return datetime.strptime(text, "%d.%m.%Y").strftime("%d-%m-%Y")

    raise ValueError(f"Неизвестный формат даты: {value}")


def get_first_multifield_value(contact: dict, field_name: str) -> str:
    values = contact.get(field_name) or []

    if not isinstance(values, list) or not values:
        return ""

    return clean_text(values[0].get("VALUE"))


def prepare_data(webhook_url: str, deal: dict) -> dict:
    contact = {}
    contact_id = deal.get("CONTACT_ID")

    if contact_id:
        try:
            contact = get_contact(webhook_url, contact_id)
        except Exception:
            contact = {}

    reg_number = clean_text(deal.get(BITRIX_FIELDS["reg_number"])).replace(" ", "").upper()
    vin = clean_text(deal.get(BITRIX_FIELDS["vin"])).replace(" ", "").upper()
    mark_model = clean_text(deal.get(BITRIX_FIELDS["mark_model"])).upper()

    year_raw = clean_text(deal.get(BITRIX_FIELDS["year"]))
    year = year_raw.split(".")[0].split(",")[0].strip()

    vehicle_type_raw = clean_text(deal.get(BITRIX_FIELDS["vehicle_type"]))

    period_raw = clean_text(deal.get(BITRIX_FIELDS["period"]))
    days = bitrix_period_to_warta_days(period_raw)

    begin_date_raw = clean_text(deal.get(BITRIX_FIELDS["begin_date"]))
    begin_date_warta = bitrix_date_to_warta_date(begin_date_raw)

    country_raw = clean_text(deal.get(BITRIX_FIELDS["country"]))
    country_warta = bitrix_country_id_to_warta_pl(country_raw)

    # Имя и фамилию берём из стандартного контакта Bitrix24.
    # Пользовательские поля "Фамилия латиницей" и "Имена латиницей" не используем.
    surname = clean_text(contact.get("LAST_NAME")) or clean_text(deal.get("LAST_NAME"))
    name = clean_text(contact.get("NAME")) or clean_text(deal.get("NAME"))

    birthdate_raw = clean_text(contact.get("BIRTHDATE")) or clean_text(deal.get("BIRTHDATE"))
    birthdate_warta = bitrix_date_to_warta_date(birthdate_raw)

    passport = clean_text(contact.get("UF_CRM_CONTACT_1686145698592"))
    email = get_first_multifield_value(contact, "EMAIL")

    result = {
        "reg_number": reg_number,
        "vin": vin,
        "mark_model": mark_model,
        "brand_query": mark_model[:3].strip(),
        "year": year,
        "first_registration_date": f"10-02-{year}" if year else "",
        "vehicle_type_raw": vehicle_type_raw,
        "is_passenger_car": (
            "passenger car" in vehicle_type_raw.lower()
            or "samochód osobowy" in vehicle_type_raw.lower()
        ),
        "period_raw": period_raw,
        "days": days,
        "begin_date_raw": begin_date_raw,
        "begin_date_warta": begin_date_warta,
        "country_raw": country_raw,
        "country_warta": country_warta,
        "surname": surname,
        "name": name,
        "birthdate_raw": birthdate_raw,
        "birthdate": birthdate_warta,
        "passport": passport,
        "email": email,
    }

    missing = []
    for key, label in [
        ("reg_number", "номер ТС"),
        ("vin", "VIN"),
        ("mark_model", "марка и модель"),
        ("year", "год выпуска"),
        ("country_warta", "страна"),
        ("days", "срок страхования"),
        ("begin_date_warta", "начало действия страховки"),
        ("surname", "фамилия клиента"),
        ("name", "имя клиента"),
        ("birthdate", "дата рождения клиента"),
    ]:
        if not result[key]:
            missing.append(label)

    if missing:
        raise ValueError("В сделке/контакте не заполнены обязательные поля: " + ", ".join(missing))

    if len(vin) != 17:
        raise ValueError(f"VIN должен содержать 17 символов, сейчас: {vin}")

    return result