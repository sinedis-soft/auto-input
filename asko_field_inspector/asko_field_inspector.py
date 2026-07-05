
import json
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


START_URL = "https://asko2.novelty.kz/login.html"


class AskoFieldInspector:
    def __init__(self, root):
        self.root = root
        self.root.title("ASKO2 Field Inspector")
        self.root.geometry("980x680")

        self.driver = None
        self.last_scan = None

        self.output_dir = tk.StringVar(value=str(Path.cwd() / "asko2_scans"))
        self.status = tk.StringVar(value="Готово. Нажмите «Открыть Chrome».")

        top = tk.Frame(root)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Папка сохранения:").pack(side="left")
        tk.Entry(top, textvariable=self.output_dir, width=70).pack(side="left", padx=6)
        tk.Button(top, text="Выбрать", command=self.choose_dir).pack(side="left")

        buttons = tk.Frame(root)
        buttons.pack(fill="x", padx=10, pady=5)

        tk.Button(buttons, text="1. Открыть Chrome", command=self.open_chrome_thread, width=22).pack(side="left", padx=4)
        tk.Button(buttons, text="2. Сканировать текущую страницу", command=self.scan_thread, width=28).pack(side="left", padx=4)
        tk.Button(buttons, text="3. Сохранить скриншот + данные", command=self.save_thread, width=30).pack(side="left", padx=4)
        tk.Button(buttons, text="Закрыть Chrome", command=self.close_chrome, width=18).pack(side="left", padx=4)

        tk.Label(root, textvariable=self.status, anchor="w").pack(fill="x", padx=10, pady=4)

        self.log = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=10, pady=8)

        self.print_help()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def print_help(self):
        self.log.insert("end", """Инструкция:
1) Нажмите «Открыть Chrome».
2) В открывшемся Chrome вручную войдите в ASKO2.
3) Перейдите на нужную форму.
4) Нажмите «Сканировать текущую страницу».
5) Нажмите «Сохранить скриншот + данные».

Программа сохраняет:
- screenshot_*.png — снимок текущего экрана Chrome;
- fields_*.json — технические данные полей;
- fields_*.txt — удобный текстовый отчёт.

Пароли не сохраняются: значения password-полей маскируются.
""")

    def set_status(self, text):
        self.status.set(text)
        self.root.update_idletasks()

    def log_write(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def choose_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir.set(folder)

    def open_chrome_thread(self):
        threading.Thread(target=self.open_chrome, daemon=True).start()

    def scan_thread(self):
        threading.Thread(target=self.scan_page, daemon=True).start()

    def save_thread(self):
        threading.Thread(target=self.save_all, daemon=True).start()

    def open_chrome(self):
        try:
            self.set_status("Запускаю Chrome...")
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None

            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_argument("--lang=ru-RU")

            # Отдельный профиль, чтобы не ломать ваш основной Chrome.
            profile_dir = Path.cwd() / "chrome_profile_asko2"
            profile_dir.mkdir(exist_ok=True)
            chrome_options.add_argument(f"--user-data-dir={profile_dir}")

            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.get(START_URL)

            self.set_status("Chrome открыт. Введите логин/пароль вручную и перейдите на нужную форму.")
            self.log_write(f"\nОткрыта страница: {START_URL}")
        except Exception as e:
            self.set_status("Ошибка запуска Chrome.")
            messagebox.showerror("Ошибка", str(e))

    def scan_page(self):
        if not self.driver:
            messagebox.showwarning("Нет Chrome", "Сначала нажмите «Открыть Chrome».")
            return

        try:
            self.set_status("Сканирую DOM текущей страницы...")
            data = self.driver.execute_script(JS_SCAN_SCRIPT)
            self.last_scan = data

            self.log.delete("1.0", "end")
            self.log_write(f"URL: {data.get('url')}")
            self.log_write(f"Title: {data.get('title')}")
            self.log_write(f"Найдено элементов: {len(data.get('elements', []))}\n")

            for i, el in enumerate(data.get("elements", []), 1):
                line = (
                    f"[{i}] {el.get('tag')} type={el.get('type') or ''}\n"
                    f"  text: {el.get('text') or ''}\n"
                    f"  value: {el.get('value') or ''}\n"
                    f"  label: {el.get('label') or ''}\n"
                    f"  placeholder: {el.get('placeholder') or ''}\n"
                    f"  name: {el.get('name') or ''}\n"
                    f"  id: {el.get('id') or ''}\n"
                    f"  aria-label: {el.get('ariaLabel') or ''}\n"
                    f"  ng-model: {el.get('ngModel') or ''}\n"
                    f"  ng-click: {el.get('ngClick') or ''}\n"
                    f"  ng-options: {el.get('ngOptions') or ''}\n"
                    f"  css: {el.get('css') or ''}\n"
                    f"  xpath: {el.get('xpath') or ''}\n"
                    f"  xywh: {el.get('x')},{el.get('y')},{el.get('width')},{el.get('height')}\n"
                )
                self.log_write(line)

            self.set_status("Сканирование завершено.")
        except Exception as e:
            self.set_status("Ошибка сканирования.")
            messagebox.showerror("Ошибка", str(e))

    def save_all(self):
        if not self.driver:
            messagebox.showwarning("Нет Chrome", "Сначала нажмите «Открыть Chrome».")
            return

        try:
            if not self.last_scan:
                self.scan_page()
                if not self.last_scan:
                    return

            out_dir = Path(self.output_dir.get())
            out_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = out_dir / f"screenshot_{ts}.png"
            json_path = out_dir / f"fields_{ts}.json"
            txt_path = out_dir / f"fields_{ts}.txt"

            self.driver.save_screenshot(str(screenshot_path))

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self.last_scan, f, ensure_ascii=False, indent=2)

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(self.log.get("1.0", "end"))

            self.set_status(f"Сохранено: {out_dir}")
            self.log_write(f"\nСохранено:\n{screenshot_path}\n{json_path}\n{txt_path}")
            messagebox.showinfo("Готово", f"Файлы сохранены в:\n{out_dir}")
        except Exception as e:
            self.set_status("Ошибка сохранения.")
            messagebox.showerror("Ошибка", str(e))

    def close_chrome(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.set_status("Chrome закрыт.")

    def on_close(self):
        self.close_chrome()
        self.root.destroy()


JS_SCAN_SCRIPT = r"""
function getXPath(el) {
  if (!el || el.nodeType !== 1) return "";
  if (el.id) return '//*[@id="' + el.id + '"]';
  const parts = [];
  while (el && el.nodeType === 1) {
    let index = 1;
    let sib = el.previousSibling;
    while (sib) {
      if (sib.nodeType === 1 && sib.nodeName === el.nodeName) index++;
      sib = sib.previousSibling;
    }
    parts.unshift(el.nodeName.toLowerCase() + "[" + index + "]");
    el = el.parentNode;
  }
  return "/" + parts.join("/");
}

function cssEscapeSimple(s) {
  if (!s) return "";
  return String(s).replace(/([ #;?%&,.+*~\':"!^$[\]()=>|/@])/g, "\\$1");
}

function getCssPath(el) {
  if (!el || el.nodeType !== 1) return "";
  if (el.id) return "#" + cssEscapeSimple(el.id);
  const parts = [];
  while (el && el.nodeType === 1 && el !== document.body) {
    let part = el.nodeName.toLowerCase();
    if (el.className && typeof el.className === "string") {
      const classes = el.className.trim().split(/\s+/).slice(0, 3).map(cssEscapeSimple).join(".");
      if (classes) part += "." + classes;
    }
    let nth = 1;
    let sib = el.previousElementSibling;
    while (sib) {
      if (sib.nodeName === el.nodeName) nth++;
      sib = sib.previousElementSibling;
    }
    part += ":nth-of-type(" + nth + ")";
    parts.unshift(part);
    el = el.parentElement;
  }
  return parts.join(" > ");
}

function textClean(s) {
  return (s || "").replace(/\s+/g, " ").trim().slice(0, 300);
}

function findLabel(el) {
  if (!el) return "";
  const id = el.getAttribute("id");
  if (id) {
    const label = document.querySelector('label[for="' + CSS.escape(id) + '"]');
    if (label) return textClean(label.innerText || label.textContent);
  }

  let parent = el.closest("label");
  if (parent) return textClean(parent.innerText || parent.textContent);

  const container = el.closest(".form-group,.row,.field,.control,.input-group,.widget-tile-row,.widget-input,.mat-form-field,.ant-form-item");
  if (container) {
    const candidates = container.querySelectorAll("label,.label,.control-label,.form-label,.widget-input-label,span,div");
    for (const c of candidates) {
      const t = textClean(c.innerText || c.textContent);
      if (t && t.length < 120 && !t.includes(textClean(el.value))) return t;
    }
  }

  let prev = el.previousElementSibling;
  for (let i = 0; prev && i < 3; i++, prev = prev.previousElementSibling) {
    const t = textClean(prev.innerText || prev.textContent);
    if (t && t.length < 120) return t;
  }
  return "";
}

function visible(el) {
  const st = window.getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return st.display !== "none" &&
         st.visibility !== "hidden" &&
         Number(st.opacity) !== 0 &&
         r.width > 0 &&
         r.height > 0;
}

const selector = [
  "input",
  "select",
  "textarea",
  "button",
  "[role='button']",
  "[contenteditable='true']",
  "a[href]",
  ".select2",
  ".select2-container",
  ".mat-select",
  ".ant-select",
  ".dropdown-toggle",
  "[ng-click]",
  "[onclick]"
].join(",");

const raw = Array.from(document.querySelectorAll(selector));
const elements = [];

for (const el of raw) {
  if (!visible(el)) continue;

  const r = el.getBoundingClientRect();
  const type = el.getAttribute("type") || el.getAttribute("role") || "";
  const isPassword = String(type).toLowerCase() === "password";
  let value = "";

  if ("value" in el) value = isPassword ? "***MASKED***" : String(el.value || "").slice(0, 300);

  elements.push({
    tag: el.tagName.toLowerCase(),
    type: type,
    text: textClean(el.innerText || el.textContent),
    value: value,
    label: findLabel(el),
    placeholder: el.getAttribute("placeholder") || "",
    name: el.getAttribute("name") || "",
    id: el.getAttribute("id") || "",
    ariaLabel: el.getAttribute("aria-label") || "",
    titleAttr: el.getAttribute("title") || "",
    ngModel: el.getAttribute("ng-model") || "",
    ngClick: el.getAttribute("ng-click") || "",
    ngOptions: el.getAttribute("ng-options") || "",
    onclick: el.getAttribute("onclick") || "",
    href: el.getAttribute("href") || "",
    css: getCssPath(el),
    xpath: getXPath(el),
    x: Math.round(r.x + window.scrollX),
    y: Math.round(r.y + window.scrollY),
    width: Math.round(r.width),
    height: Math.round(r.height)
  });
}

return {
  url: location.href,
  title: document.title,
  scannedAt: new Date().toISOString(),
  elements: elements
};
"""


if __name__ == "__main__":
    root = tk.Tk()
    app = AskoFieldInspector(root)
    root.mainloop()
