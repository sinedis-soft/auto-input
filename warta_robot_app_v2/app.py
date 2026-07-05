import tkinter as tk
from tkinter import ttk, messagebox

from settings_store import load_settings, save_settings
from warta_worker import WartaWorker


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent, settings, on_save):
        super().__init__(parent)
        self.title("Настройки WARTA Robot")
        self.geometry("720x320")
        self.resizable(False, False)

        self.on_save = on_save

        self.vars = {
            "warta_url": tk.StringVar(value=settings.get("warta_url", "")),
            "warta_login": tk.StringVar(value=settings.get("warta_login", "")),
            "warta_password": tk.StringVar(value=settings.get("warta_password", "")),
            "bitrix_webhook_url": tk.StringVar(value=settings.get("bitrix_webhook_url", "")),
        }

        self.build()

    def build(self):
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        rows = [
            ("WARTA URL", "warta_url", False),
            ("WARTA login", "warta_login", False),
            ("WARTA password", "warta_password", True),
            ("Bitrix24 webhook", "bitrix_webhook_url", True),
        ]

        for i, (label, key, secret) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=6)
            entry = ttk.Entry(frame, textvariable=self.vars[key], width=82, show="*" if secret else "")
            entry.grid(row=i, column=1, sticky="we", pady=6)

        note = (
            "Пароль и webhook сохраняются локально в settings.json. "
            "Не отправляйте этот файл никому. Для production лучше Windows Credential Manager."
        )
        ttk.Label(frame, text=note, wraplength=660, foreground="#6b6b6b").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=10
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=10)

        ttk.Button(buttons, text="Сохранить", command=self.save).pack(side="right", padx=5)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="right", padx=5)

    def save(self):
        data = {key: var.get().strip() for key, var in self.vars.items()}
        self.on_save(data)
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("WARTA Robot")
        self.geometry("940x640")
        self.minsize(860, 560)

        self.settings = load_settings()

        self.worker = WartaWorker(
            log_callback=self.threadsafe_log,
            state_callback=self.threadsafe_state,
        )
        self.worker.start()

        self.deal_url_var = tk.StringVar()
        self.capture_name_var = tk.StringVar(value="page")
        self.state_var = tk.StringVar(value="Готово. Вставьте ссылку на сделку и нажмите «Начать / Продолжить».")

        self.build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")

        ttk.Label(top, text="Ссылка на сделку Bitrix24:").pack(anchor="w")
        deal_row = ttk.Frame(top)
        deal_row.pack(fill="x", pady=(4, 10))

        ttk.Entry(deal_row, textvariable=self.deal_url_var).pack(side="left", fill="x", expand=True)
        ttk.Button(deal_row, text="Начать / Продолжить", command=self.start_or_continue).pack(side="left", padx=(8, 0))

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=(0, 10))

        ttk.Button(buttons, text="Настройки", command=self.open_settings).pack(side="left")
        ttk.Button(buttons, text="Сбросить сценарий", command=self.reset_scenario).pack(side="left", padx=8)

        ttk.Label(buttons, text="Имя снимка:").pack(side="left", padx=(20, 4))
        ttk.Entry(buttons, textvariable=self.capture_name_var, width=24).pack(side="left")
        ttk.Button(buttons, text="Снимок страницы", command=self.capture_page).pack(side="left", padx=8)

        state_frame = ttk.LabelFrame(root, text="Состояние")
        state_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(state_frame, textvariable=self.state_var, wraplength=850).pack(anchor="w", padx=8, pady=8)

        log_frame = ttk.LabelFrame(root, text="Лог")
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_frame, height=20, wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        self.log(
            "Перед использованием откройте «Настройки» и заполните WARTA login/password и Bitrix24 webhook."
        )

    def open_settings(self):
        SettingsWindow(self, self.settings, self.save_settings)

    def save_settings(self, data):
        self.settings.update(data)
        save_settings(self.settings)
        self.log("Настройки сохранены.")

    def start_or_continue(self):
        self.worker.submit(
            "start_or_continue",
            {
                "settings": self.settings.copy(),
                "deal_url": self.deal_url_var.get().strip(),
            },
        )

    def capture_page(self):
        self.worker.submit(
            "capture",
            {
                "settings": self.settings.copy(),
                "name": self.capture_name_var.get().strip() or "page",
            },
        )

    def reset_scenario(self):
        self.worker.submit("reset", {})
        self.log("Сценарий сброшен.")

    def threadsafe_log(self, text):
        self.after(0, lambda: self.log(text))

    def threadsafe_state(self, text):
        self.after(0, lambda: self.state_var.set(text))

    def log(self, text):
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def on_close(self):
        try:
            self.worker.submit("shutdown", {})
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
