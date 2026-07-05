"""Reusable PySide6 widgets for the automation hub."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 14, 16, 16)
        self.layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self.layout.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("MutedLabel")
            sub.setWordWrap(True)
            self.layout.addWidget(sub)


class KeyValueCard(Card):
    def __init__(self, title: str, keys: list[tuple[str, str]]) -> None:
        super().__init__(title)
        self.labels: dict[str, QLabel] = {}
        for key, caption in keys:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            name = QLabel(caption)
            name.setObjectName("MutedLabel")
            name.setMinimumWidth(180)
            value = QLabel("—")
            value.setTextInteractionFlags(value.textInteractionFlags())
            value.setWordWrap(True)
            row_layout.addWidget(name)
            row_layout.addWidget(value, 1)
            self.layout.addWidget(row)
            self.labels[key] = value

    def set_values(self, data: dict) -> None:
        for key, label in self.labels.items():
            value = data.get(key, "")
            label.setText(str(value) if value not in (None, "") else "—")


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("PrimaryButton")
    button.setMinimumHeight(42)
    return button
