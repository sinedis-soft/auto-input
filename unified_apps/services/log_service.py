"""Small in-memory log model for the PySide6 UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LogRecord:
    timestamp: datetime
    level: str
    message: str

    def format(self) -> str:
        return f"[{self.timestamp:%H:%M:%S}] {self.level.upper():7} {self.message}"


class LogService:
    def __init__(self) -> None:
        self.records: list[LogRecord] = []

    def add(self, message: str, level: str = "info") -> LogRecord:
        lowered = (level or "info").lower()
        if lowered not in {"info", "warning", "error"}:
            lowered = "info"
        record = LogRecord(datetime.now(), lowered, str(message))
        self.records.append(record)
        return record

    def clear(self) -> None:
        self.records.clear()

    def formatted(self, level: str = "all") -> str:
        selected = self.records if level == "all" else [r for r in self.records if r.level == level]
        return "\n".join(record.format() for record in selected)
