import json
from pathlib import Path


SETTINGS_PATH = Path("settings.json")


DEFAULT_SETTINGS = {
    "warta_url": "https://eagent.warta.pl",
    "warta_login": "",
    "warta_password": "",
    "bitrix_webhook_url": ""
}


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return DEFAULT_SETTINGS.copy()

    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_SETTINGS.copy()

    result = DEFAULT_SETTINGS.copy()
    result.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return result


def save_settings(settings: dict) -> None:
    result = DEFAULT_SETTINGS.copy()
    result.update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS})

    if result["bitrix_webhook_url"] and not result["bitrix_webhook_url"].endswith("/"):
        result["bitrix_webhook_url"] += "/"

    SETTINGS_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
