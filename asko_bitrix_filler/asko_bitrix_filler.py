import json, re, threading, time
from dataclasses import dataclass
from datetime import datetime, date, time as dtime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, END
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


ASKO_LOGIN_URL = "https://asko2.novelty.kz/login.html"
CONFIG_FILE = Path.home() / ".asko_bitrix_filler" / "settings.json"
ALMATY_TZ = "Asia/Almaty"

DEFAULT_CONFIG = {
    "asko_login": "",
    "asko_password": "",
    "bitrix_webhook": "",
    "chrome_profile_dir": str(Path.cwd() / "chrome_profile_asko2"),
    "payment_type": "Безналичным",
    "payment_order": "Единовременно",
    "notification_language": "Русский",
    "client_form": "Физическое лицо",
    "term_text": "15 дней",
    "keep_browser_open": True,
}

BITRIX_FIELDS = {
    "start_date": ["UF_CRM_1686152149204", "UF_CRM_1693569516501", "BEGINDATE"],
    "policy_number": "UF_CRM_1694177619522",
    "reg_number": "UF_CRM_1686152485641",
    "company_id": "COMPANY_ID",
    "email_candidates": ["UF_CRM_1686152745455", "UF_CRM_1694352997178"],
    "vehicle_model": "UF_CRM_1686152515152",
    "vehicle_year": "UF_CRM_1686152614718",
    "vin": "UF_CRM_1686152659867",
}

ASKO_MAIN_FIELDS = {
    "blank_number": "ext-comp-1193",
    "start_datetime": "ext-comp-1201",
    "term": "ext-comp-1198",
    "payment_type": "ext-comp-1199",
    "payment_order": "ext-comp-1200",
    "phone_code": "ext-comp-1326",
    "phone_number": "ext-comp-1327",
    "email": "ext-comp-1227",
    "notification_language": "ext-comp-1354",
    "client_form": "ext-comp-1220",
    "note": "ext-comp-1192",
}


@dataclass
class DealData:
    deal_id: str
    policy_number: str
    reg_number: str
    start_date: str
    vehicle_model: str
    vehicle_year: str
    vin: str
    phone: str
    email: str
    amount: str
    currency: str
    raw: dict
    asko_company_id: str = ""
    company_name: str = ""
    phone_source: str = ""


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_deal_id(s):
    s = (s or "").strip()
    m = re.search(r"/crm/deal/details/(\d+)/?", s)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{2,})\b", s)
    if m:
        return m.group(1)
    raise ValueError("Не удалось определить ID сделки. Введите 80519 или ссылку Bitrix24.")


def bitrix_call(webhook, method, params):
    webhook = (webhook or "").strip().rstrip("/")
    if not webhook:
        raise ValueError("Не указан Bitrix24 webhook.")
    r = requests.post(f"{webhook}/{method}.json", json=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"Bitrix error: {data.get('error')} {data.get('error_description')}")
    return data.get("result")


def parse_iso_date(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except Exception:
        pass
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v)[:10], fmt).date()
        except Exception:
            pass
    return None


def asko_start_datetime(target_date):
    now = datetime.now(ZoneInfo(ALMATY_TZ)) if ZoneInfo else datetime.now()
    if target_date == now.date():
        dt = now.replace(microsecond=0)
    else:
        dt = datetime.combine(target_date, dtime(0, 0, 0))
    return dt.strftime("%d.%m.%Y %H:%M:%S")


def normalize_phone(v):
    digits = re.sub(r"\D+", "", v or "")
    if not digits:
        return "7", ""
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits.startswith("7") and len(digits) >= 11:
        return "7", digits[1:]
    return "7", digits


def extract_first_multifield_value(value) -> str:
    """
    Bitrix PHONE обычно приходит так:
    [
        {"ID": "...", "VALUE_TYPE": "WORK", "VALUE": "+7 ...", "TYPE_ID": "PHONE"}
    ]
    """
    if not value:
        return ""

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                phone = str(item.get("VALUE") or "").strip()
                if phone:
                    return phone
            elif isinstance(item, str) and item.strip():
                return item.strip()

    if isinstance(value, dict):
        return str(value.get("VALUE") or "").strip()

    if isinstance(value, str):
        return value.strip()

    return ""


def get_company_phone(webhook: str, company_id: str) -> tuple[str, str, str]:
    """
    Возвращает:
    phone, company_name, phone_source
    """
    company_id = str(company_id or "").strip()
    if not company_id or company_id == "0":
        return "", "", "DEAL.COMPANY_ID пустой"

    company = bitrix_call(webhook, "crm.company.get", {"id": company_id}) or {}

    phone = extract_first_multifield_value(company.get("PHONE"))
    company_name = str(company.get("TITLE") or "").strip()

    if phone:
        return phone, company_name, "COMPANY.PHONE"

    return "", company_name, "COMPANY.PHONE пустой"


def extract_deal(result, webhook: str | None = None):
    def first(keys):
        for k in keys:
            if result.get(k):
                return result.get(k)
        return ""

    start = first(BITRIX_FIELDS["start_date"])
    sd = parse_iso_date(start)
    email = first(BITRIX_FIELDS["email_candidates"])

    company_id = str(result.get(BITRIX_FIELDS["company_id"]) or "").strip()
    company_phone = ""
    company_name = ""
    phone_source = ""

    if webhook:
        try:
            company_phone, company_name, phone_source = get_company_phone(webhook, company_id)
        except Exception as exc:
            phone_source = f"COMPANY.PHONE ошибка: {exc}"

    return DealData(
        deal_id=str(result.get("ID") or ""),
        policy_number=str(result.get(BITRIX_FIELDS["policy_number"]) or "").strip(),
        reg_number=str(result.get(BITRIX_FIELDS["reg_number"]) or "").strip(),
        start_date=sd.strftime("%d.%m.%Y") if sd else "",
        phone=company_phone,
        email=str(email or "").strip(),
        vehicle_model=str(result.get(BITRIX_FIELDS["vehicle_model"]) or "").strip(),
        vehicle_year=str(result.get(BITRIX_FIELDS["vehicle_year"]) or "").strip(),
        vin=str(result.get(BITRIX_FIELDS["vin"]) or "").strip(),
        amount=str(result.get("OPPORTUNITY") or ""),
        currency=str(result.get("CURRENCY_ID") or "KZT"),
        raw=result,
        company_name=company_name,
        phone_source=phone_source or "COMPANY.PHONE не проверялся",
    )


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("ASKO ← Bitrix24 filler")
        self.root.geometry("1120x760")
        self.driver = None
        self.deal = None
        self.cfg = load_config()
        self.v = {k: tk.StringVar(value=str(self.cfg.get(k, ""))) for k in DEFAULT_CONFIG if k != "keep_browser_open"}
        self.keep = tk.BooleanVar(value=bool(self.cfg.get("keep_browser_open", True)))
        self.deal_input = tk.StringVar()
        self.build_ui()
        self.log_write("Готово. Заполните настройки, затем введите ID сделки.")

    def build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        main = ttk.Frame(nb)
        sett = ttk.Frame(nb)
        nb.add(main, text="Заполнение")
        nb.add(sett, text="Настройки")

        ttk.Label(main, text="ID сделки или ссылка Bitrix24:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(main, textvariable=self.deal_input, width=80).grid(row=0, column=1, sticky="we", padx=8, pady=8)
        ttk.Button(main, text="Забрать данные", command=lambda: self.run(self.fetch_deal)).grid(row=0, column=2, padx=8, pady=8)

        bar = ttk.Frame(main)
        bar.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=6)

        for txt, fn in [
            ("1. Войти в ASKO", self.open_and_login),
            ("2. Новый полис ОГПО", self.open_new_policy),
            ("3. Вставить данные", self.fill_asko),
            ("Скриншот", self.screenshot),
            ("Закрыть Chrome", self.close_browser),
        ]:
            ttk.Button(
                bar,
                text=txt,
                command=lambda f=fn: self.run(f) if f not in (self.screenshot, self.close_browser) else f(),
            ).pack(side="left", padx=4)

        self.preview = scrolledtext.ScrolledText(main, height=14, font=("Consolas", 10))
        self.preview.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)

        self.log = scrolledtext.ScrolledText(main, height=18, font=("Consolas", 10))
        self.log.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)

        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=1)

        labels = [
            ("asko_login", "ASKO логин:"),
            ("asko_password", "ASKO пароль:"),
            ("bitrix_webhook", "Bitrix24 webhook:"),
            ("chrome_profile_dir", "Chrome profile dir:"),
            ("payment_type", "Тип оплаты:"),
            ("payment_order", "Порядок оплаты:"),
            ("notification_language", "Язык уведомлений:"),
            ("client_form", "Форма клиента:"),
            ("term_text", "Срок по умолчанию:"),
        ]

        for r, (key, label) in enumerate(labels):
            ttk.Label(sett, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=8)
            show = "*" if key == "asko_password" else None
            ttk.Entry(sett, textvariable=self.v[key], width=90, show=show).grid(row=r, column=1, sticky="we", padx=8, pady=8)
            if key == "chrome_profile_dir":
                ttk.Button(sett, text="Выбрать", command=self.choose_profile).grid(row=r, column=2, padx=8, pady=8)

        ttk.Checkbutton(sett, text="Не закрывать Chrome при выходе", variable=self.keep).grid(
            row=len(labels), column=1, sticky="w", padx=8, pady=8
        )
        ttk.Button(sett, text="Сохранить настройки", command=self.save_settings).grid(
            row=len(labels) + 1, column=1, sticky="w", padx=8, pady=16
        )

        sett.columnconfigure(1, weight=1)

    def choose_profile(self):
        d = filedialog.askdirectory()
        if d:
            self.v["chrome_profile_dir"].set(d)

    def save_settings(self):
        cfg = {k: self.v[k].get() for k in self.v}
        cfg["keep_browser_open"] = bool(self.keep.get())
        save_config(cfg)
        self.cfg = cfg
        self.log_write(f"Настройки сохранены: {CONFIG_FILE}")

    def log_write(self, msg):
        self.log.insert(END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log.see(END)

    def run(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def fetch_deal(self):
        try:
            self.save_settings()
            did = parse_deal_id(self.deal_input.get())
            webhook = self.v["bitrix_webhook"].get()

            self.log_write(f"Получаю сделку {did}...")
            result = bitrix_call(webhook, "crm.deal.get", {"id": did})

            self.deal = extract_deal(result, webhook=webhook)

            data = {
                "deal_id": self.deal.deal_id,
                "Компания": self.deal.company_name,
                "Источник телефона": self.deal.phone_source,
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

            self.preview.delete("1.0", END)
            self.preview.insert(END, json.dumps(data, ensure_ascii=False, indent=2))
            self.log_write("Данные сделки получены.")

            if not self.deal.phone:
                self.log_write("Внимание: телефон в COMPANY.PHONE не найден. Поле телефона в ASKO не будет заполнено.")

        except Exception as e:
            self.log_write(f"Ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

    def make_driver(self):
        opt = Options()
        opt.add_argument("--start-maximized")
        opt.add_argument("--disable-notifications")
        opt.add_argument("--lang=ru-RU")

        p = Path(self.v["chrome_profile_dir"].get() or Path.cwd() / "chrome_profile_asko2")
        p.mkdir(parents=True, exist_ok=True)
        opt.add_argument(f"--user-data-dir={p}")

        return webdriver.Chrome(options=opt)

    def open_and_login(self):
        try:
            if not self.driver:
                self.driver = self.make_driver()

            self.driver.get(ASKO_LOGIN_URL)
            wait = WebDriverWait(self.driver, 25)

            self.set_input(wait.until(EC.presence_of_element_located((By.ID, "tfSystemLogin"))), self.v["asko_login"].get())
            self.set_input(wait.until(EC.presence_of_element_located((By.ID, "tfSystemPassword"))), self.v["asko_password"].get())

            wait.until(EC.element_to_be_clickable((By.ID, "btSystemLogin1"))).click()
            time.sleep(5)
            self.log_write("Вход ASKO выполнен или ожидается загрузка.")

        except Exception as e:
            self.log_write(f"Ошибка входа: {e}")
            messagebox.showerror("Ошибка", str(e))

    def open_new_policy(self):
        try:
            if not self.driver:
                self.open_and_login()

            self.click_text_or_id("Полис ОГПО", "ext-gen238")
            time.sleep(1)

            try:
                self.click_text_or_id("Новый полис", "ext-gen277")
            except Exception:
                self.click_text_or_id("ОС ГПО BTC", "ext-gen1026")

            time.sleep(3)
            self.log_write("Форма нового полиса открыта.")

        except Exception as e:
            self.log_write(f"Ошибка открытия формы: {e}")
            messagebox.showerror("Ошибка", str(e))

    def fill_asko(self):
        try:
            if not self.deal:
                self.fetch_deal()

            if not self.driver:
                self.open_and_login()

            start_val = ""
            if self.deal.start_date:
                start_val = asko_start_datetime(datetime.strptime(self.deal.start_date, "%d.%m.%Y").date())

            code, body = normalize_phone(self.deal.phone)

            pairs = [
                ("blank_number", self.deal.policy_number),
                ("start_datetime", start_val),
                ("term", self.v["term_text"].get()),
                ("payment_type", self.v["payment_type"].get()),
                ("payment_order", self.v["payment_order"].get()),
                ("phone_code", code),
                ("phone_number", body),
                ("email", self.deal.email),
                ("notification_language", self.v["notification_language"].get()),
                ("client_form", self.v["client_form"].get()),
            ]

            note = f"Bitrix deal ID: {self.deal.deal_id}; Госномер: {self.deal.reg_number}; VIN: {self.deal.vin}"
            pairs.append(("note", note))

            for key, val in pairs:
                self.safe_set(ASKO_MAIN_FIELDS[key], val)

            self.log_write("Основные поля ASKO заполнены. Телефон взят из COMPANY.PHONE.")

        except Exception as e:
            self.log_write(f"Ошибка заполнения: {e}")
            messagebox.showerror("Ошибка", str(e))

    def set_input(self, el, val):
        val = "" if val is None else str(val)
        try:
            el.click()
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.BACKSPACE)
            el.send_keys(val)
            el.send_keys(Keys.TAB)
        except Exception:
            self.driver.execute_script(
                "arguments[0].value=arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
                el,
                val,
            )

    def safe_set(self, element_id, val):
        if val is None or str(val) == "":
            return
        try:
            el = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.ID, element_id)))
            self.set_input(el, val)
            self.log_write(f"{element_id} ← {val}")
        except Exception as e:
            self.log_write(f"Не заполнено {element_id}: {e}")

    def click_text_or_id(self, text, element_id=None):
        if element_id:
            try:
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.ID, element_id))).click()
                return
            except Exception:
                pass

        xp = f"//*[normalize-space(text())='{text}' or contains(normalize-space(.), '{text}')]"
        WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, xp))).click()

    def screenshot(self):
        if not self.driver:
            return messagebox.showwarning("Нет Chrome", "Chrome не открыт.")

        out = Path.cwd() / f"asko_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        self.driver.save_screenshot(str(out))
        self.log_write(f"Скриншот: {out}")

    def close_browser(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.log_write("Chrome закрыт.")

    def on_close(self):
        if not self.keep.get():
            self.close_browser()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()