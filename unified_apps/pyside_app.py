"""Entry point for the PySide6 Bitrix policy automation hub.

Run:
    python -m unified_apps.pyside_app
or:
    python unified_apps/pyside_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "unified_apps"

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow

QSS = """
* { font-family: 'Segoe UI', 'Segoe UI Variable', Arial; font-size: 10.5pt; color: #1f1f1f; }
QMainWindow, QWidget { background: #f5f7fb; }
#TopStatus { background: #ffffff; border-bottom: 1px solid #dde3ee; padding: 12px 18px; font-weight: 600; }
#SideMenu { background: #ffffff; border: none; border-right: 1px solid #dde3ee; padding: 12px 8px; }
#SideMenu::item { padding: 12px 14px; border-radius: 8px; margin: 2px; }
#SideMenu::item:selected { background: #e8f1ff; color: #0f5fc2; font-weight: 600; }
#Card { background: #ffffff; border: 1px solid #dde3ee; border-radius: 12px; }
#CardTitle { font-size: 14pt; font-weight: 700; }
#MutedLabel { color: #697386; }
#StatusLabel { background: #eef6ff; border: 1px solid #bdd7ff; border-radius: 8px; padding: 10px; font-weight: 600; }
#WarningLabel { background: #fff7df; border: 1px solid #ffd36a; border-radius: 8px; padding: 10px; color: #6a4a00; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox { background: #ffffff; border: 1px solid #cfd8e6; border-radius: 8px; padding: 8px; selection-background-color: #0f6cbd; }
QPushButton { background: #ffffff; border: 1px solid #c8d2e1; border-radius: 8px; padding: 8px 14px; }
QPushButton:hover { background: #f0f5fb; }
QPushButton:pressed { background: #e2eaf5; }
#PrimaryButton { background: #0f6cbd; color: white; border: 1px solid #0f6cbd; font-weight: 600; }
#PrimaryButton:hover { background: #115ea3; }
#BottomLog { background: #101820; color: #d8dee9; border: none; font-family: Consolas, 'Cascadia Mono'; font-size: 9.5pt; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
