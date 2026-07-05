from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from .widgets import Card, primary_button

class AskoPage(QWidget):
    next_requested = Signal(); new_policy_requested = Signal(); reset_requested = Signal(); close_chrome_requested = Signal()
    def __init__(self) -> None:
        super().__init__(); layout = QVBoxLayout(self); layout.setContentsMargins(24,24,24,24); layout.setSpacing(16)
        self.stage = QLabel("Этап: ожидание сделки"); self.stage.setObjectName("StatusLabel"); self.warning = QLabel("После заполнения основных данных ASKO приложение остановится и попросит оператора вручную нажать «Далее» в ASKO."); self.warning.setObjectName("WarningLabel"); self.warning.setWordWrap(True)
        card = Card("ASKO — текущий этап", "Сценарий выполняется в фоне, Selenium не блокирует интерфейс."); card.layout.addWidget(self.stage); card.layout.addWidget(self.warning); layout.addWidget(card)
        self.next_button = primary_button("Далее"); self.next_button.clicked.connect(self.next_requested.emit); layout.addWidget(self.next_button)
        row = QHBoxLayout();
        for text, sig in [("Новый полис", self.new_policy_requested), ("Сбросить сценарий", self.reset_requested), ("Закрыть Chrome", self.close_chrome_requested)]:
            b = primary_button(text) if text == "Новый полис" else __import__('PySide6.QtWidgets').QtWidgets.QPushButton(text); b.setMinimumHeight(36); b.clicked.connect(sig.emit); row.addWidget(b)
        layout.addLayout(row); layout.addStretch(1)
    def set_status(self, text: str) -> None: self.stage.setText(text)
