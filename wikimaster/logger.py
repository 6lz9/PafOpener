"""Journal d'activité horodaté, partagé entre le contrôleur (thread de travail) et l'interface."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

INFO = "INFO"
ATTENTION = "ATTENTION"
ERREUR = "ERREUR"


@dataclass(frozen=True)
class LogEntry:
    horodatage: datetime
    niveau: str
    message: str

    def format(self) -> str:
        return f"[{self.horodatage:%H:%M:%S}] {self.niveau:<9} {self.message}"


class ActivityLog:
    """Journal thread-safe. L'interface récupère les nouvelles entrées avec `drain()`."""

    def __init__(self, file_path: Path | None = None, max_entries: int = 5000):
        self._lock = threading.Lock()
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._pending: deque[LogEntry] = deque(maxlen=max_entries)
        self._file_path = file_path
        if file_path is not None:
            file_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, niveau: str, message: str) -> LogEntry:
        entry = LogEntry(datetime.now(), niveau, message)
        with self._lock:
            self._entries.append(entry)
            self._pending.append(entry)
            if self._file_path is not None:
                try:
                    with self._file_path.open("a", encoding="utf-8") as fh:
                        fh.write(f"{entry.horodatage:%Y-%m-%d} {entry.format()}\n")
                except OSError:
                    pass  # le journal fichier ne doit jamais bloquer le programme
        return entry

    def info(self, message: str) -> LogEntry:
        return self.log(INFO, message)

    def warning(self, message: str) -> LogEntry:
        return self.log(ATTENTION, message)

    def error(self, message: str) -> LogEntry:
        return self.log(ERREUR, message)

    def drain(self) -> list[LogEntry]:
        """Retourne les entrées ajoutées depuis le dernier appel."""
        with self._lock:
            items = list(self._pending)
            self._pending.clear()
        return items

    @property
    def entries(self) -> list[LogEntry]:
        with self._lock:
            return list(self._entries)

    def messages(self) -> list[str]:
        return [e.message for e in self.entries]
