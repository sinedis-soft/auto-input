from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .widgets import KeyValueCard, primary_button

DEAL_KEYS = [
    ("deal_id", "deal_id"), ("scenario", "сценарий"), ("company", "компания"),
    ("phone_source", "источник телефона"), ("phone", "телефон"), ("email", "email"),
    ("policy_number", "номер бланка ASKO"), ("reg_number", "госномер"), ("vin", "VIN"),
    ("start_date", "дата начала"), ("term", "срок"), ("asko_company_id", "ИД в ASKO KZ"),
    ("premium", "премия"), ("currency", "валюта"),
]


class DealPage(QWidget):
    load_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        row = QHBoxLayout()
        self.deal_input = QLineEdit()
        self.deal_input.setPlaceholderText("ID сделки или ссылка Bitrix24")
        self.load_button = primary_button("Загрузить сделку")
        self.load_button.clicked.connect(lambda: self.load_requested.emit(self.deal_input.text()))
        row.addWidget(self.deal_input, 1)
        row.addWidget(self.load_button)
        layout.addLayout(row)
        self.preview = KeyValueCard("Preview данных сделки", DEAL_KEYS)
        layout.addWidget(self.preview)
        layout.addStretch(1)

    def set_preview(self, data: dict) -> None:
        self.preview.set_values(data)
