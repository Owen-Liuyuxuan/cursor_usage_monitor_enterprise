"""Read Cursor's local session and query its dashboard usage endpoints.

The access token is read from Cursor's SQLite database for each refresh and is
kept only in memory.  It is never returned in the normalized snapshot.
"""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SUMMARY_URL = "https://cursor.com/api/usage-summary"
LEGACY_URL = "https://cursor.com/api/usage?user={user_id}"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class CursorUsageError(RuntimeError):
    """A safe-to-display collection failure with no credential material."""


@dataclass(frozen=True, slots=True)
class CursorSession:
    access_token: str = field(repr=False)
    user_id: str
    membership_type: str | None
    team_name: str | None


def _decode_user_id(access_token: str) -> str:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        subject = str(claims["sub"])
        user_id = subject.split("|", 1)[-1]
    except (binascii.Error, IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CursorUsageError("Cursor access token has an unrecognized format") from error
    if not user_id:
        raise CursorUsageError("Cursor account identifier is unavailable")
    return user_id


def read_cursor_session(database: Path) -> CursorSession:
    """Read only the required session fields from Cursor's database."""
    if not database.is_file():
        raise CursorUsageError(f"Cursor session database was not found at {database}")
    try:
        connection = sqlite3.connect(
            f"file:{urllib.parse.quote(str(database))}?mode=ro", uri=True, timeout=3
        )
        try:
            rows = dict(connection.execute(
                "SELECT key, value FROM ItemTable WHERE key IN "
                "('cursorAuth/accessToken', 'cursorAuth/stripeMembershipType', "
                "'cursorAuth/cachedTeam')"
            ))
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise CursorUsageError("Cursor session database could not be read") from error

    token = rows.get("cursorAuth/accessToken")
    if not token:
        raise CursorUsageError("Cursor Desktop is not signed in")
    team_name = None
    try:
        team_name = json.loads(rows.get("cursorAuth/cachedTeam", "{}")).get("name")
    except (AttributeError, json.JSONDecodeError):
        pass
    return CursorSession(
        access_token=token,
        user_id=_decode_user_id(token),
        membership_type=rows.get("cursorAuth/stripeMembershipType"),
        team_name=team_name,
    )


def _request_json(request: urllib.request.Request, timeout: float = 15) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise CursorUsageError("Cursor session expired; sign in again in Cursor Desktop") from error
        raise CursorUsageError(f"Cursor usage service returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise CursorUsageError("Cursor usage service is unreachable") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CursorUsageError("Cursor usage response was unexpectedly large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CursorUsageError("Cursor usage service returned invalid data") from error
    if not isinstance(value, dict):
        raise CursorUsageError("Cursor usage service returned an unexpected payload")
    return value


def _cookie(session: CursorSession) -> str:
    value = urllib.parse.quote(f"{session.user_id}::{session.access_token}", safe="")
    return f"WorkosCursorSessionToken={value}"


def fetch_raw_usage(
    session: CursorSession,
    request_json: Callable[[urllib.request.Request], dict[str, Any]] = _request_json,
) -> tuple[dict[str, Any], dict[str, Any]]:
    headers = {
        "Cookie": _cookie(session),
        "Origin": "https://cursor.com",
        "Referer": "https://cursor.com/dashboard",
        "User-Agent": "CursorUsageSupervisor/0.1",
    }
    summary = request_json(urllib.request.Request(SUMMARY_URL, headers=headers))
    legacy_url = LEGACY_URL.format(user_id=urllib.parse.quote(session.user_id, safe=""))
    try:
        legacy = request_json(urllib.request.Request(legacy_url, headers=headers))
    except CursorUsageError:
        # The legacy endpoint is only a compatibility probe. Its retirement
        # must not break accounts already recognized by the primary response.
        legacy = {}
    return summary, legacy


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _billable_usage_cents(plan_used: Any, on_demand_used: Any) -> int | float | None:
    """Return the requested headline: included consumed plus on-demand usage.

    Bonus usage is deliberately excluded because Cursor describes it as free
    provider-granted usage rather than an amount charged to the account.
    """
    included = _number(plan_used)
    on_demand = _number(on_demand_used)
    if included is None or on_demand is None:
        return None
    return included + on_demand


def normalize_usage(
    session: CursorSession,
    summary: dict[str, Any],
    legacy: dict[str, Any],
) -> dict[str, Any]:
    """Normalize legacy and current account shapes without treating absence as zero."""
    common: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": "cursor-dashboard-session",
        "membership_type": summary.get("membershipType") or session.membership_type,
        "team_name": session.team_name,
        "billing_cycle": {
            "start": summary.get("billingCycleStart") or legacy.get("startOfMonth"),
            "end": summary.get("billingCycleEnd"),
        },
        "privacy": "local-session-token-and-cursor-dashboard",
    }

    legacy_model = legacy.get("gpt-4") if isinstance(legacy.get("gpt-4"), dict) else {}
    request_limit = _number(legacy_model.get("maxRequestUsage"))
    if request_limit is not None and request_limit > 0:
        common.update({
            "billing_model": "legacy_request_count",
            "requests": {
                "used": _number(legacy_model.get("numRequests")),
                "total_seen": _number(legacy_model.get("numRequestsTotal")),
                "limit": request_limit,
            },
        })
        return common

    individual = summary.get("individualUsage")
    plan = individual.get("plan") if isinstance(individual, dict) else None
    if isinstance(plan, dict):
        on_demand = individual.get("onDemand")
        breakdown = plan.get("breakdown")
        common.update({
            "billing_model": "usage_based",
            "is_unlimited": summary.get("isUnlimited"),
            "limit_type": summary.get("limitType"),
            "billable_usage_cents": _billable_usage_cents(
                plan.get("used"), on_demand.get("used") if isinstance(on_demand, dict) else None
            ),
            "plan": {
                "used_cents": _number(plan.get("used")),
                "limit_cents": _number(plan.get("limit")),
                "remaining_cents": _number(plan.get("remaining")),
                "breakdown": {
                    "included_cents": _number(breakdown.get("included")),
                    "bonus_cents": _number(breakdown.get("bonus")),
                    "total_cents": _number(breakdown.get("total")),
                } if isinstance(breakdown, dict) else None,
                # These historical wire names are attribution/usage metrics on
                # older Team contracts. Do not present them as proof of two
                # independent allowance pools.
                "auto_percent_used_raw": _number(plan.get("autoPercentUsed")),
                "api_percent_used_raw": _number(plan.get("apiPercentUsed")),
                "total_percent": _number(plan.get("totalPercentUsed")),
            },
            "on_demand": {
                "enabled": on_demand.get("enabled"),
                "used_cents": _number(on_demand.get("used")),
                "limit_cents": _number(on_demand.get("limit")),
                "remaining_cents": _number(on_demand.get("remaining")),
            } if isinstance(on_demand, dict) else None,
            "messages": {
                "cursor_models": summary.get("autoModelSelectedDisplayMessage"),
                "other_models": summary.get("namedModelSelectedDisplayMessage"),
            },
        })
        return common

    common.update({
        "billing_model": "unknown",
        "error": "Cursor returned an unrecognized usage schema; no zero usage was assumed",
    })
    return common


def collect_usage(database: Path) -> dict[str, Any]:
    session = read_cursor_session(database)
    summary, legacy = fetch_raw_usage(session)
    return normalize_usage(session, summary, legacy)
