from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_safe_storage import seal_token

from cursor_usage_supervisor.client import (
    CursorSession,
    fetch_raw_usage,
    normalize_usage,
    read_cursor_session,
)
from cursor_usage_supervisor.errors import CursorUsageError
from cursor_usage_supervisor.safe_storage import SEALED_PREFIX


def fake_jwt(subject: str = "auth0|user_test") -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class CursorSessionTest(unittest.TestCase):
    def test_reads_required_fields_without_refresh_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.vscdb"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            connection.executemany("INSERT INTO ItemTable VALUES (?, ?)", [
                ("cursorAuth/accessToken", fake_jwt()),
                ("cursorAuth/refreshToken", "must-not-be-read"),
                ("cursorAuth/stripeMembershipType", "enterprise"),
                ("cursorAuth/cachedTeam", json.dumps({"name": "Example Team"})),
            ])
            connection.commit()
            connection.close()

            session = read_cursor_session(database)

            self.assertEqual(session.user_id, "user_test")
            self.assertEqual(session.membership_type, "enterprise")
            self.assertEqual(session.team_name, "Example Team")
            self.assertNotIn("refresh", repr(session).lower())

    def test_unseals_safe_storage_access_token(self) -> None:
        password = "unit-test-password"
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.vscdb"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute(
                "INSERT INTO ItemTable VALUES (?, ?)",
                ("cursorAuth/accessToken", seal_token(fake_jwt(), password)),
            )
            connection.commit()
            connection.close()

            with patch(
                "cursor_usage_supervisor.safe_storage.lookup_linux_os_crypt_password",
                return_value=password,
            ):
                session = read_cursor_session(database)

            self.assertEqual(session.user_id, "user_test")
            self.assertFalse(session.access_token.startswith(SEALED_PREFIX))

    def test_missing_database_is_safe_error(self) -> None:
        with self.assertRaisesRegex(CursorUsageError, "not found"):
            read_cursor_session(Path("/definitely/missing/state.vscdb"))


class NormalizationTest(unittest.TestCase):
    session = CursorSession(fake_jwt(), "user_test", "enterprise", "Example Team")

    def test_current_usage_based_shape(self) -> None:
        summary = {
            "billingCycleStart": "2026-08-31T00:00:00Z",
            "billingCycleEnd": "2026-09-30T00:00:00Z",
            "membershipType": "enterprise",
            "limitType": "team",
            "individualUsage": {
                "plan": {
                    "used": 1200, "limit": 2000, "remaining": 800,
                    "breakdown": {"included": 1200, "bonus": 300, "total": 1500},
                    "autoPercentUsed": 25, "apiPercentUsed": 60, "totalPercentUsed": 60,
                },
                "onDemand": {"enabled": True, "used": 700, "limit": None, "remaining": None},
            },
        }
        result = normalize_usage(self.session, summary, {"gpt-4": {"maxRequestUsage": None}})

        self.assertEqual(result["billing_model"], "usage_based")
        self.assertEqual(result["plan"]["breakdown"]["bonus_cents"], 300)
        self.assertEqual(result["on_demand"]["used_cents"], 700)
        self.assertEqual(result["billable_usage_cents"], 1900)
        self.assertEqual(result["plan"]["auto_percent_used_raw"], 25)
        self.assertEqual(result["plan"]["api_percent_used_raw"], 60)
        self.assertNotIn("cursor_models_percent", result["plan"])
        self.assertNotIn("other_models_percent", result["plan"])
        self.assertNotIn(self.session.access_token, json.dumps(result))

    def test_legacy_request_limit_takes_precedence(self) -> None:
        legacy = {
            "startOfMonth": "2026-09-01T00:00:00Z",
            "gpt-4": {"numRequests": 1200, "numRequestsTotal": 1300, "maxRequestUsage": 2000},
        }
        result = normalize_usage(self.session, {}, legacy)
        self.assertEqual(result["billing_model"], "legacy_request_count")
        self.assertEqual(result["requests"]["limit"], 2000)

    def test_unknown_schema_is_not_zero(self) -> None:
        result = normalize_usage(self.session, {}, {})
        self.assertEqual(result["billing_model"], "unknown")
        self.assertIn("error", result)
        self.assertNotIn("plan", result)

    def test_current_summary_survives_retired_legacy_endpoint(self) -> None:
        responses = iter([{"individualUsage": {"plan": {}}}, CursorUsageError("HTTP 404")])

        def request_json(_request):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value

        summary, legacy = fetch_raw_usage(self.session, request_json)
        self.assertIn("individualUsage", summary)
        self.assertEqual(legacy, {})


if __name__ == "__main__":
    unittest.main()
