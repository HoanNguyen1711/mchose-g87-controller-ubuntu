"""GTK3 settings window + tray indicator."""
import queue
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import i18n  # noqa: E402
from .device import (EFFECT_BY_NAME, EFFECTS, LEVEL_MAX, PALETTE_SIZE,  # noqa: E402
                     DeviceNotFound, Keyboard)
from .i18n import effect_label, t  # noqa: E402

APP_ID = "io.github.mchose_ctl"
BATTERY_POLL_SECONDS = 120
LOW_BATTERY = 15
APPLY_DELAY_MS = 300
PRESETS = ["#ff0000", "#ff8000", "#ffff00", "#00ff00", "#00ffff", "#0040ff", "#ff00ff", "#ffffff"]

CSS = b"""
.swatch { min-width: 22px; min-height: 22px; padding: 0; border-radius: 11px; }
.effect-grid button { padding: 6px 10px; }
.title { font-size: 15pt; font-weight: bold; }
""" + b"".join(
    b".swatch-%d { background: %s; }" % (i, c.encode()) for i, c in enumerate(PRESETS))


class Worker:
    """Runs keyboard jobs one at a time off the GTK main thread."""

    def __init__(self):
        self.jobs = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, fn, done=None, error=None):
        self.jobs.put((fn, done, error))

    @staticmethod
    def _run(fn):
        # jobs are idempotent read-modify-writes, so a radio hiccup is safe to retry
        for attempt in range(2):
            try:
                with Keyboard() as kb:
                    return fn(kb)
            except TimeoutError:
                if attempt:
                    raise

    def _loop(self):
        while True:
            fn, done, error = self.jobs.get()
            try:
                result = self._run(fn)
            except (DeviceNotFound, TimeoutError, OSError, ValueError) as e:
                if error:
                    GLib.idle_add(error, e)
            else:
                if done:
                    GLib.idle_add(done, result)


def rgba_to_rgb(rgba):
    return tuple(round(v * 255) for v in (rgba.red, rgba.green, rgba.blue))


def rgb_to_rgba(rgb):
    rgba = Gdk.RGBA()
    rgba.parse("#%02x%02x%02x" % rgb)
    return rgba


def level_scale():
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, LEVEL_MAX, 1)
    scale.set_digits(0)
    scale.set_hexpand(True)
    for i in range(LEVEL_MAX + 1):
        scale.add_mark(i, Gtk.PositionType.BOTTOM, None)
    return scale


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MCHOSE G87")
        self.app = app
        self.set_default_size(560, -1)
        self.set_resizable(False)
        self.set_icon_name("input-keyboard")
        self.connect("delete-event", lambda *_: self.hide() or True)
        self.connect("focus-in-event", lambda *_: self.refresh(stale_only=True))

        self.updating = False  # set while filling widgets from device state
        self.effect = None
        self.color_dirty = False
        self.apply_source = None
        self.last_refresh = 0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=18)
        self.add(root)

        header = Gtk.Box(spacing=12)
        title = Gtk.Label(label="MCHOSE G87", xalign=0)
        title.get_style_context().add_class("title")
        header.pack_start(title, False, False, 0)
        self.battery_label = Gtk.Label(label=t("battery_unknown"))
        self.battery_bar = Gtk.LevelBar(min_value=0, max_value=100)
        self.battery_bar.set_size_request(80, -1)
        self.battery_bar.set_valign(Gtk.Align.CENTER)
        self.language = Gtk.ComboBoxText(tooltip_text=t("language"), valign=Gtk.Align.CENTER)
        for code, name in i18n.LANGUAGES.items():
            self.language.append(code, name)
        self.language.set_active_id(i18n.current())
        self.language.connect("changed", lambda c: app.change_language(c.get_active_id()))
        header.pack_end(self.language, False, False, 0)
        header.pack_end(self.battery_label, False, False, 0)
        header.pack_end(self.battery_bar, False, False, 0)
        root.pack_start(header, False, False, 0)

        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.pack_start(self.controls, False, False, 0)

        self.controls.pack_start(self._section(t("effects")), False, False, 0)
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=5, max_children_per_line=5,
                           column_spacing=6, row_spacing=6)
        grid.get_style_context().add_class("effect-grid")
        self.effect_buttons = {}
        group = None
        for e in EFFECTS:
            b = Gtk.RadioButton.new_with_label_from_widget(group, effect_label(e))
            b.set_mode(False)  # look like a toggle button
            b.connect("toggled", self.on_effect_toggled, e)
            group = group or b
            grid.add(b)
            self.effect_buttons[e.mode] = b
        self.controls.pack_start(grid, False, False, 0)

        form = Gtk.Grid(column_spacing=14, row_spacing=10)
        self.brightness = level_scale()
        self.speed = level_scale()
        self.brightness.connect("value-changed", self.on_setting_changed)
        self.speed.connect("value-changed", self.on_setting_changed)
        self.brightness_label = Gtk.Label(label=t("brightness"), xalign=0)
        self.speed_label = Gtk.Label(label=t("speed"), xalign=0)
        form.attach(self.brightness_label, 0, 0, 1, 1)
        form.attach(self.brightness, 1, 0, 1, 1)
        form.attach(self.speed_label, 0, 1, 1, 1)
        form.attach(self.speed, 1, 1, 1, 1)

        self.color_label = Gtk.Label(label=t("color"), xalign=0)
        self.color_box = Gtk.Box(spacing=6)
        self.color_button = Gtk.ColorButton()
        self.color_button.connect("color-set", self.on_color_picked)
        self.color_box.pack_start(self.color_button, False, False, 0)
        for i, c in enumerate(PRESETS):
            sw = Gtk.Button(tooltip_text=c, valign=Gtk.Align.CENTER)
            sw.get_style_context().add_class("swatch")
            sw.get_style_context().add_class(f"swatch-{i}")
            sw.connect("clicked", self.on_preset, c)
            self.color_box.pack_start(sw, False, False, 0)
        form.attach(self.color_label, 0, 2, 1, 1)
        form.attach(self.color_box, 1, 2, 1, 1)

        self.palette_label = Gtk.Label(label=t("palette"), xalign=0)
        self.palette = Gtk.Switch(halign=Gtk.Align.START)
        self.palette.connect("notify::active", self.on_setting_changed)
        form.attach(self.palette_label, 0, 3, 1, 1)
        form.attach(self.palette, 1, 3, 1, 1)
        self.controls.pack_start(form, False, False, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        root.pack_start(self.status, False, False, 0)

        root.show_all()

    @staticmethod
    def _section(text):
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{text}</b>")
        return label

    # --- device -> UI ----------------------------------------------------

    def refresh(self, stale_only=False):
        if stale_only and time.monotonic() - self.last_refresh < 3:
            return
        self.last_refresh = time.monotonic()
        self.app.worker.submit(lambda kb: kb.light(), self.show_state, self.show_error)

    def show_state(self, state):
        self.updating = True
        e = self.effect = state.effect
        self.controls.set_sensitive(True)
        if e.mode in self.effect_buttons:
            self.effect_buttons[e.mode].set_active(True)
        if state.brightness is not None:
            self.brightness.set_value(state.brightness)
        if state.speed is not None:
            self.speed.set_value(state.speed)
        if state.color is not None:
            self.color_button.set_rgba(rgb_to_rgba(state.color))
        self.palette.set_active(bool(state.multicolor))
        self.color_dirty = False
        for widgets, ok in (((self.brightness, self.brightness_label), e.brightness),
                            ((self.speed, self.speed_label), e.speed),
                            ((self.color_box, self.color_label,
                              self.palette, self.palette_label), e.color)):
            for w in widgets:
                w.set_sensitive(ok)
        self.updating = False
        self.status.set_text("")

    def show_error(self, err):
        self.controls.set_sensitive(not isinstance(err, DeviceNotFound))
        self.status.set_text(t("error", err=err))

    def show_battery(self, battery):
        if battery is None:
            self.battery_label.set_text(t("battery_unknown"))
            self.battery_bar.set_value(0)
        else:
            charging = " ⚡" if battery.charging else ""
            self.battery_label.set_text(t("battery", level=battery.level) + charging)
            self.battery_bar.set_value(battery.level)

    # --- UI -> device ----------------------------------------------------

    def on_effect_toggled(self, button, effect):
        if self.updating or not button.get_active():
            return
        self.status.set_text(t("applying"))
        self.app.set_effect(effect)

    def on_setting_changed(self, *_):
        if self.updating or self.effect is None:
            return
        if self.apply_source:
            GLib.source_remove(self.apply_source)
        self.apply_source = GLib.timeout_add(APPLY_DELAY_MS, self.apply)

    def on_color_picked(self, _button):
        self.color_dirty = True
        self.updating = True
        self.palette.set_active(False)
        self.updating = False
        self.on_setting_changed()

    def on_preset(self, _button, color):
        self.color_button.set_rgba(rgb_to_rgba(tuple(bytes.fromhex(color[1:]))))
        self.on_color_picked(None)

    def apply(self):
        self.apply_source = None
        e = self.effect
        kwargs = {}
        if e.brightness:
            kwargs["brightness"] = int(self.brightness.get_value())
        if e.speed:
            kwargs["speed"] = int(self.speed.get_value())
        if e.color:
            kwargs["multicolor"] = PALETTE_SIZE if self.palette.get_active() else 0
            if self.color_dirty:
                kwargs["color"] = rgba_to_rgb(self.color_button.get_rgba())
        self.status.set_text(t("applying"))
        self.app.worker.submit(lambda kb: kb.set_light(e, **kwargs),
                               self.app.on_light_changed, self.show_error)
        return False


class App(Gtk.Application):
    def __init__(self, hidden):
        super().__init__(application_id=APP_ID)
        self.start_hidden = hidden
        self.window = None
        self.worker = Worker()
        self.low_battery_warned = False
        self.battery = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = SettingsWindow(self)
        self.window.hide()
        self._build_tray()
        self.hold()  # keep running in the tray when the window is closed
        self.poll_battery()
        GLib.timeout_add_seconds(BATTERY_POLL_SECONDS, self.poll_battery)

    def do_activate(self):
        if self.start_hidden:
            self.start_hidden = False
            return
        self.show_window()

    def show_window(self, *_):
        self.window.present()
        self.window.refresh()

    def change_language(self, lang):
        if lang == i18n.current():
            return
        i18n.set_language(lang)
        # rebuild every widget with the new strings
        old = self.window
        if old.apply_source:
            GLib.source_remove(old.apply_source)
            old.apply()
        self.window = SettingsWindow(self)
        old.destroy()
        self._build_menu()
        self.show_battery(self.battery)
        self.show_window()

    def _build_tray(self):
        self.indicator = AppIndicator.Indicator.new(
            APP_ID, "input-keyboard-symbolic", AppIndicator.IndicatorCategory.HARDWARE)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("MCHOSE G87")
        self._build_menu()

    def _build_menu(self):
        menu = Gtk.Menu()
        self.battery_item = Gtk.MenuItem(label=t("battery_unknown"), sensitive=False)
        menu.append(self.battery_item)
        menu.append(Gtk.SeparatorMenuItem())
        open_item = Gtk.MenuItem(label=t("open_settings"))
        open_item.connect("activate", self.show_window)
        menu.append(open_item)

        effects_item = Gtk.MenuItem(label=t("effects"))
        effects_menu = Gtk.Menu()
        for e in EFFECTS:
            if e.name == "off":
                continue
            item = Gtk.MenuItem(label=effect_label(e))
            item.connect("activate", lambda _i, e=e: self.set_effect(e))
            effects_menu.append(item)
        effects_item.set_submenu(effects_menu)
        menu.append(effects_item)

        off_item = Gtk.MenuItem(label=t("effect.off"))
        off_item.connect("activate", lambda _i: self.set_effect(EFFECT_BY_NAME["off"]))
        menu.append(off_item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label=t("quit"))
        quit_item.connect("activate", lambda _i: self.quit())
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)
        # clicking the tray icon with the middle button opens settings
        self.indicator.set_secondary_activate_target(open_item)

    def set_effect(self, effect):
        self.worker.submit(lambda kb: kb.set_light(effect), self.on_light_changed,
                           self.window.show_error)

    def on_light_changed(self, state):
        self.window.show_state(state)
        self.window.status.set_text(t("applied"))

    def poll_battery(self):
        self.worker.submit(lambda kb: kb.battery(), self.show_battery,
                           lambda _e: self.show_battery(None))
        return True

    def show_battery(self, battery):
        self.battery = battery
        self.window.show_battery(battery)
        if battery is None:
            self.indicator.set_label("", "100%")
            self.battery_item.set_label(t("battery_unavailable"))
            return
        charging = t("charging") if battery.charging else ""
        self.indicator.set_label(f"{battery.level}%", "100%")
        self.battery_item.set_label(t("battery", level=battery.level) + charging)
        if battery.level <= LOW_BATTERY and not battery.charging:
            if not self.low_battery_warned:
                n = Gio.Notification.new(t("low_battery_title"))
                n.set_body(t("low_battery_body", level=battery.level))
                self.send_notification("low-battery", n)
                self.low_battery_warned = True
        else:
            self.low_battery_warned = False


def run(hidden=False):
    # the GTK3 indicator library still works; silence its deprecation notice
    GLib.log_set_handler("libayatana-appindicator", GLib.LogLevelFlags.LEVEL_WARNING,
                         lambda *_: None)
    return App(hidden).run([])
