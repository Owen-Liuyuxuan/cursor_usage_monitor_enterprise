"""Libadwaita preferences for Cursor Usage Supervisor."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from .config import Settings


class PreferencesApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="io.github.owen.CursorUsageSupervisor.Preferences")
        self.settings = Settings.load()

    def do_activate(self) -> None:
        existing = self.get_active_window()
        if existing:
            existing.present()
            return
        window = Adw.PreferencesWindow(application=self)
        window.set_title("Cursor Usage Supervisor")
        window.set_default_size(580, 460)
        page = Adw.PreferencesPage(title="Usage")
        window.add(page)

        behavior = Adw.PreferencesGroup(
            title="Behavior", description="Cursor usage changes slowly; five minutes is recommended."
        )
        page.add(behavior)
        behavior.add(self._spin_row("Refresh interval", "seconds", self.settings.refresh_seconds, 60, 3600, 60, "refresh_seconds"))
        behavior.add(self._spin_row("Notify at", "%", self.settings.notify_at_percent, 1, 100, 1, "notify_at_percent"))

        source = Adw.PreferencesGroup(
            title="Data source",
            description="The backend opens Cursor's session database read-only and queries Cursor's dashboard.",
        )
        page.add(source)
        source.add(self._text_row("Cursor session database", self.settings.cursor_db))

        privacy = Adw.PreferencesGroup(title="Privacy and security")
        page.add(privacy)
        row = Adw.ActionRow(
            title="No stored credentials",
            subtitle="The access token stays in backend memory; the refresh token is never read.",
        )
        row.add_prefix(Gtk.Image.new_from_icon_name("security-high-symbolic"))
        privacy.add(row)
        window.present()

    def _spin_row(self, title: str, unit: str, value: int, minimum: int, maximum: int, step: int, attribute: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        control = Gtk.SpinButton(
            adjustment=Gtk.Adjustment(value=value, lower=minimum, upper=maximum, step_increment=step, page_increment=step * 5),
            numeric=True, valign=Gtk.Align.CENTER,
        )
        control.set_tooltip_text(unit)
        control.connect("value-changed", self._save_number, attribute)
        row.add_suffix(control)
        row.set_activatable_widget(control)
        return row

    def _text_row(self, title: str, value: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        entry = Gtk.Entry(text=value, valign=Gtk.Align.CENTER, width_chars=34)
        entry.connect("activate", self._save_path)
        entry.connect("notify::has-focus", self._save_path_on_blur)
        row.add_suffix(entry)
        row.set_activatable_widget(entry)
        return row

    def _save_number(self, control: Gtk.SpinButton, attribute: str) -> None:
        setattr(self.settings, attribute, control.get_value_as_int())
        self.settings.validated().save()

    def _save_path(self, entry: Gtk.Entry) -> None:
        self.settings.cursor_db = entry.get_text()
        self.settings.validated().save()

    def _save_path_on_blur(self, entry: Gtk.Entry, _parameter: object) -> None:
        if not entry.get_property("has-focus"):
            self._save_path(entry)


def main() -> None:
    PreferencesApplication().run(None)


if __name__ == "__main__":
    main()
