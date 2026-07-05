from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from .widgets import Card, primary_button

class WartaPage(QWidget):
    next_requested = Signal(); reset_requested = Signal(); close_worker_requested = Signal()
    def __init__(self) -> None:
        super().__init__(); layout = QVBoxLayout(self); layout.setContentsMargins(24,24,24,24); layout.setSpacing(16)
        card = Card("WARTA — текущий этап", "Worker запускается в фоне через существующий адаптер."); self.status = QLabel("Этап: ожидание сделки"); self.status.setObjectName("StatusLabel"); card.layout.addWidget(self.status); layout.addWidget(card)
        b = primary_button("Далее"); b.clicked.connect(self.next_requested.emit); layout.addWidget(b)
        row = QHBoxLayout(); reset = QPushButton("Сбросить сценарий"); close = QPushButton("Закрыть worker"); reset.clicked.connect(self.reset_requested.emit); close.clicked.connect(self.close_worker_requested.emit); row.addWidget(reset); row.addWidget(close); layout.addLayout(row); layout.addStretch(1)
    def set_status(self, text: str) -> None: self.status.setText(text)
