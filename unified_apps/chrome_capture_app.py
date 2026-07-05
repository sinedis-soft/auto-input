"""Universal Chrome page capture app for screenshots and DOM/TXT snapshots.

Chrome must be started with remote debugging, for example:
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\chrome-capture-profile"
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk


DEFAULT_DEBUG_URL = "http://127.0.0.1:9222"
DEFAULT_OUTPUT_DIR = Path.cwd() / "captures"

JS_INSPECT = r"""
(() => {
  function visible(el) {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }
  function textOf(el) { return (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(); }
  function cssPath(el) {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 8) {
      let part = node.nodeName.toLowerCase();
      if (node.className && typeof node.className === 'string') {
        part += node.className.split(/\s+/).filter(Boolean).slice(0, 2).map(c => '.' + CSS.escape(c)).join('');
      }
      const parent = node.parentElement;
      if (parent) {
        const sameTag = Array.from(parent.children).filter(child => child.nodeName === node.nodeName);
        if (sameTag.length > 1) part += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(' > ');
  }
  const selector = ['input','select','textarea','button','a','[role="button"]','[role="combobox"]','[ng-click]','[ng-model]'].join(',');
  return {
    url: location.href,
    title: document.title,
    created_at: new Date().toISOString(),
    elements: Array.from(document.querySelectorAll(selector)).filter(visible).map((el, index) => {
      const rect = el.getBoundingClientRect();
      return {
        index,
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        text: textOf(el),
        value: el.value || '',
        placeholder: el.getAttribute('placeholder') || '',
        name: el.getAttribute('name') || '',
        id: el.getAttribute('id') || '',
        aria_label: el.getAttribute('aria-label') || '',
        role: el.getAttribute('role') || '',
        ng_model: el.getAttribute('ng-model') || '',
        ng_click: el.getAttribute('ng-click') || '',
        css_path: cssPath(el),
        xywh: [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)]
      };
    })
  };
})()
"""


def safe_filename(value: str) -> str:
    value = (value or "page").strip()
    value = re.sub(r"[^\wа-яА-ЯёЁ.-]+", "_", value, flags=re.UNICODE).strip("_")
    return (value or "page")[:100]


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: "CaptureApp"):
        super().__init__(parent)
        self.title("Настройки снимков Chrome")
        self.resizable(False, False)
        self.parent = parent
        self.debug_url = tk.StringVar(value=parent.debug_url.get())
        self.output_dir = tk.StringVar(value=parent.output_dir.get())
        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Chrome remote debugging URL").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(frame, textvariable=self.debug_url, width=72).grid(row=1, column=0, sticky="ew")
        ttk.Label(frame, text="Папка сохранения").grid(row=2, column=0, sticky="w", pady=(14, 6))
        row = ttk.Frame(frame)
        row.grid(row=3, column=0, sticky="ew")
        ttk.Entry(row, textvariable=self.output_dir, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Выбрать", command=self.choose_dir).pack(side="left", padx=(8, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Сохранить настройки", command=self.save).pack(side="right", padx=(0, 8))

    def choose_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.output_dir.set(path)

    def save(self):
        self.parent.debug_url.set(self.debug_url.get().strip() or DEFAULT_DEBUG_URL)
        self.parent.output_dir.set(self.output_dir.get().strip() or str(DEFAULT_OUTPUT_DIR))
        self.parent.set_status("Настройки сохранены.")
        self.destroy()


class CaptureApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Chrome Snapshot Collector")
        self.geometry("980x680")
        self.minsize(880, 600)
        self.debug_url = tk.StringVar(value=DEFAULT_DEBUG_URL)
        self.output_dir = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.capture_name = tk.StringVar(value="page")
        self.status = tk.StringVar(value="Готово. Введите имя снимка и нажмите «Сделать снимок».")
        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Универсальные снимки Chrome", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text="Сохраняет PNG, TXT и JSON активной вкладки Chrome для дальнейшей настройки автоматизации.").pack(anchor="w", pady=(4, 16))

        card = ttk.LabelFrame(root, text="Снимок")
        card.pack(fill="x")
        row = ttk.Frame(card, padding=12)
        row.pack(fill="x")
        ttk.Label(row, text="Имя для файлов").pack(side="left")
        ttk.Entry(row, textvariable=self.capture_name, width=36).pack(side="left", padx=(10, 8))
        ttk.Button(row, text="Сделать снимок", command=self.capture).pack(side="left")
        ttk.Button(row, text="Настройки", command=lambda: SettingsDialog(self)).pack(side="left", padx=(8, 0))

        status_card = ttk.LabelFrame(root, text="Ход работы")
        status_card.pack(fill="x", pady=(16, 0))
        ttk.Label(status_card, textvariable=self.status, wraplength=900).pack(anchor="w", padx=12, pady=10)

        log_card = ttk.LabelFrame(root, text="Журнал и данные для копирования")
        log_card.pack(fill="both", expand=True, pady=(16, 0))
        self.log = scrolledtext.ScrolledText(log_card, wrap="word", font=("Consolas", 10), undo=True)
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        self.log.insert("end", "Подсказка: запустите Chrome с --remote-debugging-port=9222. Текст здесь можно выделять и копировать.\n")

    def set_status(self, text: str):
        self.status.set(text)
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log.see("end")

    def capture(self):
        threading.Thread(target=self._capture_worker, daemon=True).start()

    def _capture_worker(self):
        try:
            self.after(0, self.set_status, "Подключаюсь к Chrome...")
            from playwright.sync_api import sync_playwright

            out_dir = Path(self.output_dir.get()).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            name = safe_filename(self.capture_name.get())
            base = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{name}"
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.debug_url.get().rstrip("/"))
                page = self._active_page(browser)
                data = page.evaluate(JS_INSPECT)
                json_path = base.with_suffix(".json")
                txt_path = base.with_suffix(".txt")
                png_path = base.with_suffix(".png")
                json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                txt_path.write_text(self._to_text(data), encoding="utf-8")
                page.screenshot(path=str(png_path), full_page=True, timeout=15000)
                browser.close()
            self.after(0, self.set_status, f"Снимок сохранен: {png_path.name}, {txt_path.name}, {json_path.name}")
        except Exception as exc:
            self.after(0, self.set_status, f"Не удалось сделать снимок. Проверьте Chrome remote debugging. Детали: {exc}")

    def _active_page(self, browser):
        pages = [page for context in browser.contexts for page in context.pages]
        if not pages:
            raise RuntimeError("В подключенном Chrome нет открытых вкладок.")
        return pages[-1]

    def _to_text(self, data: dict) -> str:
        lines = [f"URL: {data.get('url', '')}", f"TITLE: {data.get('title', '')}", ""]
        for el in data.get("elements", []):
            lines.extend([
                f"[{el['index']}] {el['tag']} type={el.get('type', '')}",
                f"  text: {el.get('text', '')}",
                f"  value: {el.get('value', '')}",
                f"  placeholder: {el.get('placeholder', '')}",
                f"  name/id: {el.get('name', '')} / {el.get('id', '')}",
                f"  aria/role: {el.get('aria_label', '')} / {el.get('role', '')}",
                f"  ng: {el.get('ng_model', '')} / {el.get('ng_click', '')}",
                f"  css: {el.get('css_path', '')}",
                f"  xywh: {el.get('xywh', '')}",
                "",
            ])
        return "\n".join(lines)


if __name__ == "__main__":
    CaptureApp().mainloop()
