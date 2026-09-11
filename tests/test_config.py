from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cursor_usage_supervisor.config import Settings


class SettingsTest(unittest.TestCase):
    def test_validation_bounds_network_polling(self) -> None:
        settings = Settings(refresh_seconds=1, notify_at_percent=200).validated()
        self.assertEqual(settings.refresh_seconds, 60)
        self.assertEqual(settings.notify_at_percent, 100)

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            Settings(refresh_seconds=600, notify_at_percent=85, cursor_db="/tmp/cursor.db").save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.refresh_seconds, 600)
            self.assertEqual(loaded.cursor_db, "/tmp/cursor.db")


if __name__ == "__main__":
    unittest.main()
