"""Persistent, non-secret application settings."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "cursor-usage-supervisor" / "settings.json"


def default_cursor_db() -> str:
    return str(Path.home() / ".config/Cursor/User/globalStorage/state.vscdb")


@dataclass(slots=True)
class Settings:
    refresh_seconds: int = 300
    notify_at_percent: int = 90
    cursor_db: str = default_cursor_db()

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        values = {key: raw[key] for key in asdict(cls()) if key in raw}
        try:
            return cls(**values).validated()
        except (TypeError, ValueError):
            return cls()

    def validated(self) -> "Settings":
        self.refresh_seconds = min(3600, max(60, int(self.refresh_seconds)))
        self.notify_at_percent = min(100, max(1, int(self.notify_at_percent)))
        self.cursor_db = str(Path(self.cursor_db).expanduser())
        return self

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
