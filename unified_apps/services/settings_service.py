"""Settings loading/saving for unified desktop apps."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_NAME = "BitrixPolicyAutomationHub"
SETTINGS_FILENAME = "bitrix_policy_router.settings.json"
DEV_SETTINGS_FILE = ROOT / "unified_apps" / SETTINGS_FILENAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def external_app_dir() -> Path:
    """Return a writable external directory for app data outside Program Files."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    if is_frozen():
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    return ROOT


def default_asko_chrome_profile_dir() -> Path:
    """Return the default writable Chrome profile directory for ASKO."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME / "chrome_profile_asko2"
    return Path.home() / "AppData" / "Roaming" / APP_NAME / "chrome_profile_asko2"


def settings_file_path() -> Path:
    if is_frozen():
        return external_app_dir() / SETTINGS_FILENAME
    return DEV_SETTINGS_FILE


SETTINGS_FILE = settings_file_path()

DEFAULT_SETTINGS = {
    "bitrix_webhook_url": "",
    "warta_url": "https://eagent.warta.pl",
    "warta_login": "",
    "warta_password": "",
    "asko_login": "",
    "asko_password": "",
    "asko_chrome_profile_dir": str(default_asko_chrome_profile_dir()),
    "asko_payment_type": "Безналичным",
    "asko_payment_order": "Единовременно",
    "asko_notification_language": "Русский",
    "asko_client_form": "Физическое лицо",
    "asko_term_text": "15 дней",
}

ALIASES = {
    "bitrix_webhook": "bitrix_webhook_url",
    "chrome_profile_dir": "asko_chrome_profile_dir",
    "payment_type": "asko_payment_type",
    "payment_order": "asko_payment_order",
    "notification_language": "asko_notification_language",
    "client_form": "asko_client_form",
    "term_text": "asko_term_text",
}


def migrate_settings(raw: dict) -> dict:
    data = DEFAULT_SETTINGS.copy()
    for old_key, new_key in ALIASES.items():
        if new_key not in raw and old_key in raw:
            raw[new_key] = raw[old_key]
    data.update(raw)
    return data


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        return migrate_settings(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    clean = migrate_settings(dict(data))
    SETTINGS_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
