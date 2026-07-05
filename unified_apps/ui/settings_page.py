from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget
from .widgets import Card, primary_button

FIELDS = [
    ("bitrix_webhook_url", "Bitrix24 webhook", True), ("asko_login", "ASKO login", False), ("asko_password", "ASKO password", True),
    ("asko_chrome_profile_dir", "ASKO Chrome profile dir", False), ("asko_payment_type", "ASKO тип оплаты", False), ("asko_payment_order", "ASKO порядок оплаты", False),
    ("asko_notification_language", "ASKO язык уведомлений", False), ("asko_client_form", "ASKO форма клиента", False), ("asko_term_text", "ASKO срок по умолчанию", False),
    ("warta_url", "WARTA url", False), ("warta_login", "WARTA login", False), ("warta_password", "WARTA password", True),
]

class SettingsPage(QWidget):
    save_requested = Signal(dict)
    def __init__(self) -> None:
        super().__init__(); outer = QVBoxLayout(self); outer.setContentsMargins(24,24,24,24)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); outer.addWidget(scroll)
        body = QWidget(); layout = QVBoxLayout(body); layout.setSpacing(16); self.inputs = {}
        card = Card("Настройки", "Секреты сохраняются только в локальный JSON-файл и не выводятся в журнал."); form = QFormLayout(); form.setLabelAlignment(__import__('PySide6.QtCore').QtCore.Qt.AlignLeft)
        for key, label, secret in FIELDS:
            edit = QLineEdit(); edit.setEchoMode(QLineEdit.Password if secret else QLineEdit.Normal); self.inputs[key] = edit
            if key == "asko_chrome_profile_dir":
                row = QHBoxLayout(); row.addWidget(edit, 1); browse = QPushButton("Выбрать папку"); browse.clicked.connect(self._browse_profile); row.addWidget(browse); wrap = QWidget(); wrap.setLayout(row); form.addRow(label, wrap)
            else: form.addRow(label, edit)
        card.layout.addLayout(form); save = primary_button("Сохранить настройки"); save.clicked.connect(lambda: self.save_requested.emit(self.values())); card.layout.addWidget(save); layout.addWidget(card); layout.addStretch(1); scroll.setWidget(body)
    def _browse_profile(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку Chrome profile", self.inputs["asko_chrome_profile_dir"].text())
        if path: self.inputs["asko_chrome_profile_dir"].setText(path)
    def set_values(self, data: dict) -> None:
        for key, edit in self.inputs.items(): edit.setText(str(data.get(key, "") or ""))
    def values(self) -> dict: return {key: edit.text().strip() for key, edit in self.inputs.items()}
