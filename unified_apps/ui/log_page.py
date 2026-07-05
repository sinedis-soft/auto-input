from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget

class LogPage(QWidget):
    clear_requested = Signal(); copy_requested = Signal(); filter_changed = Signal(str)
    def __init__(self) -> None:
        super().__init__(); layout = QVBoxLayout(self); layout.setContentsMargins(24,24,24,24); layout.setSpacing(12)
        row = QHBoxLayout(); self.filter = QComboBox(); self.filter.addItems(["all", "info", "warning", "error"]); self.filter.currentTextChanged.connect(self.filter_changed.emit)
        clear = QPushButton("Очистить журнал"); copy = QPushButton("Скопировать журнал"); clear.clicked.connect(self.clear_requested.emit); copy.clicked.connect(self.copy_requested.emit)
        row.addWidget(self.filter); row.addStretch(1); row.addWidget(clear); row.addWidget(copy); layout.addLayout(row)
        self.text = QPlainTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text, 1)
    def set_text(self, text: str) -> None: self.text.setPlainText(text); self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
    def current_filter(self) -> str: return self.filter.currentText()
