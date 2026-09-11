"""D-Bus service supplying credential-free Cursor usage snapshots."""

from __future__ import annotations

import argparse
import json
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .client import CursorUsageError, collect_usage
from .config import Settings

BUS_NAME = "io.github.owen.CursorUsageSupervisor"
OBJECT_PATH = "/io/github/owen/CursorUsageSupervisor"
INTERFACE = BUS_NAME

INTROSPECTION_XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetSummary"><arg name="summary" type="s" direction="out"/></method>
    <method name="Refresh"><arg name="summary" type="s" direction="out"/></method>
    <signal name="UsageChanged"><arg name="summary" type="s"/></signal>
  </interface>
</node>
"""


def collect_summary(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings.load()
    return collect_usage(Path(settings.cursor_db))


class UsageService:
    def __init__(self) -> None:
        self.settings = Settings.load()
        self.connection: Gio.DBusConnection | None = None
        self.registration_id = 0
        self.node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        self.summary = self._initial_summary()
        self.last_successful: dict[str, Any] | None = None
        parsed = json.loads(self.summary)
        if not parsed.get("error"):
            self.last_successful = parsed
        self.last_usage_percent = self._usage_percent(parsed)

    def _initial_summary(self) -> str:
        try:
            value = collect_summary(self.settings)
        except CursorUsageError as error:
            value = self._error_summary(str(error))
        return json.dumps(value, separators=(",", ":"))

    @staticmethod
    def _error_summary(message: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": datetime.now().astimezone().isoformat(),
            "source": "unavailable",
            "error": message,
        }

    def on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self.connection = connection
        self.registration_id = connection.register_object(
            OBJECT_PATH, self.node.interfaces[0], self._handle_method_call, None, None
        )

    def _handle_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        _parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "Refresh":
            self.refresh()
        if method_name in {"GetSummary", "Refresh"}:
            invocation.return_value(GLib.Variant("(s)", (self.summary,)))
            return
        invocation.return_dbus_error(f"{INTERFACE}.UnknownMethod", method_name)

    def refresh(self) -> bool:
        self.settings = Settings.load()
        try:
            value = collect_summary(self.settings)
            self.last_successful = value
        except CursorUsageError as error:
            if self.last_successful:
                value = dict(self.last_successful)
                value["stale"] = True
                value["refresh_error"] = str(error)
            else:
                value = self._error_summary(str(error))
        except Exception:
            value = self._error_summary("Unexpected error while refreshing Cursor usage")

        updated = json.dumps(value, separators=(",", ":"))
        changed = updated != self.summary
        self.summary = updated
        current_percent = self._usage_percent(value)
        if self.last_usage_percent < self.settings.notify_at_percent <= current_percent:
            self._notify(current_percent)
        self.last_usage_percent = current_percent
        if changed and self.connection:
            self.connection.emit_signal(
                None, OBJECT_PATH, INTERFACE, "UsageChanged", GLib.Variant("(s)", (self.summary,))
            )
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _usage_percent(summary: dict[str, Any]) -> float:
        if summary.get("error"):
            return 0.0
        if summary.get("billing_model") == "legacy_request_count":
            requests = summary.get("requests") or {}
            used, limit = requests.get("used"), requests.get("limit")
            return 100 * float(used) / float(limit) if used is not None and limit else 0.0
        return float((summary.get("plan") or {}).get("total_percent") or 0)

    def schedule(self) -> None:
        GLib.timeout_add_seconds(self.settings.refresh_seconds, self._scheduled_refresh)

    def _scheduled_refresh(self) -> bool:
        self.refresh()
        self.schedule()
        return GLib.SOURCE_REMOVE

    def _notify(self, percentage: float) -> None:
        if not self.connection:
            return
        parameters = GLib.Variant(
            "(susssasa{sv}i)",
            (
                "Cursor Usage Supervisor", 0, "cursor-usage-supervisor",
                "Cursor usage alert", f"Included usage has reached {percentage:.0f}%.",
                [], {}, -1,
            ),
        )
        self.connection.call(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify", parameters, None,
            Gio.DBusCallFlags.NONE, -1, None, None,
        )


def run_service() -> None:
    service = UsageService()
    loop = GLib.MainLoop()
    owner_id = Gio.bus_own_name(
        Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
        service.on_bus_acquired, None, lambda _connection, _name: loop.quit(),
    )
    service.schedule()
    for signum in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, loop.quit)
    try:
        loop.run()
    finally:
        Gio.bus_unown_name(owner_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cursor Usage Supervisor backend")
    parser.add_argument("--once", action="store_true", help="print one redacted snapshot and exit")
    arguments = parser.parse_args()
    if arguments.once:
        try:
            print(json.dumps(collect_summary(), indent=2))
        except CursorUsageError as error:
            raise SystemExit(str(error)) from None
    else:
        run_service()


if __name__ == "__main__":
    main()
