"""Platinum chrome, and the desktop-pinned container the modules live in.

Three things live here.

The drawing kit: the Mac OS 8 "Platinum" primitives -- the two-tone bevel,
the group box that notches its own border for its label, the pinstriped
title bar, radios, buttons and meters. All Cairo, because Platinum lives in
details no widget theme exposes and drawing it is less work than fighting
one into that shape.

The palette, `C`. The *shapes* are always Platinum, but the colours and
font follow the active Omarchy theme: on Platinum itself they are the exact
hand-tuned values, and on any other theme they are derived from that
theme's colors.toml. Everything draws through `C` at paint time rather
than binding colours at import, so a theme switch re-skins the container in
place.

`ControlPanels`, which is not a window. It is a layer-shell surface on the
BOTTOM layer -- above the wallpaper, below every normal window -- pinned to
the desktop the way a desk accessory sat there rather than joining
Hyprland's tiling layout. It takes no keyboard focus and reserves no
exclusive zone, so it never steals input or pushes windows around. Pointer
events still reach it, so the controls work.
"""

import os
import subprocess
import threading
import tomllib

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, GLib, Gtk4LayerShell as LS  # noqa: E402

STATE = os.path.expanduser("~/.local/state/omarchy/current")
THEME_NAME = os.path.join(STATE, "theme.name")
THEME_COLORS = os.path.join(STATE, "theme", "colors.toml")
# `omarchy font set` rewrites this, so its mtime tells us the font changed.
FONTCONF = os.path.expanduser("~/.config/fontconfig/fonts.conf")

TITLEBAR_H = 20
PAD = 10


# --------------------------------------------------------------- palette


def _hex(s):
    s = s.strip().lstrip("#")
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _mix(a, b, t):
    """t of the way from a to b."""
    return tuple(x + (y - x) * t for x, y in zip(a, b))


_WHITE = (1.0, 1.0, 1.0)
_BLACK = (0.0, 0.0, 0.0)


class Palette:
    """Every colour and the font the kit draws with, by role.

    Roles rather than colours, because the same role needs a different
    colour depending on the theme's mode: the Platinum outline is black,
    and a black outline on a dark theme simply vanishes.
    """

    def __init__(self):
        self.slug = None
        self.use_platinum()

    def use_platinum(self):
        """The exact Mac OS 8 values, tuned by eye rather than derived."""
        self.face = (0.867, 0.867, 0.867)     # #DDDDDD window grey
        self.face_dk = (0.800, 0.800, 0.800)  # #CCCCCC pressed face
        self.hi = _WHITE                      # bevel highlight
        self.shadow = (0.533, 0.533, 0.533)   # #888888 bevel shadow
        self.outline = _BLACK
        # On a 72dpi CRT the stock #CCCCCC pinstripe read clearly against
        # #DDDDDD; on a modern panel that 5% step all but vanishes, so this
        # lands where the original looked rather than where it measured.
        self.stripe = (0.769, 0.769, 0.769)   # #C4C4C4
        self.well = _WHITE                    # meter and chart interiors
        self.fg = _BLACK
        self.dim = (0.463, 0.463, 0.463)      # #767676
        self.up = (0.082, 0.486, 0.055)       # classic Mac green
        self.down = (0.733, 0.031, 0.024)     # classic Mac red
        self.accent = (0.235, 0.353, 0.549)   # Platinum blue
        # ChicagoFLF, not the Chicago Kare bitmap reproduction: Kare ships
        # no hinting tables and goes mushy on a fractionally-scaled display.
        self.font = "ChicagoFLF"

    def use_theme(self, colors, font):
        """Derive every role from an Omarchy colors.toml."""
        bg = _hex(colors["background"])
        fg = _hex(colors["foreground"])
        light = colors.get("mode", "dark") == "light"

        self.face = bg
        self.fg = fg
        self.dim = _hex(colors["dark_foreground"])
        self.accent = _hex(colors["accent"])
        self.up = _hex(colors["green"])
        self.down = _hex(colors["red"])
        self.face_dk = _mix(bg, fg, 0.12)
        self.stripe = _mix(bg, fg, 0.10)

        if light:
            self.hi = _mix(bg, _WHITE, 0.6)
            self.shadow = _mix(bg, _BLACK, 0.35)
            self.outline = _mix(bg, _BLACK, 0.8)
            self.well = _mix(bg, _WHITE, 0.7)
        else:
            # On a dark ground the outline has to go *lighter* to be seen,
            # and the wells go darker so they still read as recessed.
            self.hi = _mix(bg, _WHITE, 0.12)
            self.shadow = _mix(bg, _BLACK, 0.5)
            self.outline = _mix(bg, fg, 0.35)
            self.well = _hex(colors["darker_background"])

        self.font = font


C = Palette()


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def theme_signature():
    """Cheap fingerprint of everything that decides how we look."""
    return (_read(THEME_NAME), _mtime(THEME_COLORS), _mtime(FONTCONF))


def load_theme():
    """Point `C` at the active theme. Falls back to Platinum on any error,
    so a half-written theme mid-switch can't take the container down."""
    slug = _read(THEME_NAME)
    C.slug = slug
    if slug == "platinum":
        C.use_platinum()
        return
    try:
        with open(THEME_COLORS, "rb") as f:
            colors = tomllib.load(f)
        # The same family the bar resolves: the fontconfig `monospace`
        # alias that `omarchy font set` writes.
        font = subprocess.run(
            ["fc-match", "-f", "%{family[0]}", "monospace"],
            capture_output=True, text=True, timeout=3).stdout.strip()
        C.use_theme(colors, font or "monospace")
    except Exception:  # noqa: BLE001 -- look like Platinum rather than die
        C.use_platinum()


# ------------------------------------------------------- drawing helpers


def rgb(cr, color):
    cr.set_source_rgb(*color)


def rect(cr, x, y, w, h, color):
    rgb(cr, color)
    cr.rectangle(x, y, w, h)
    cr.fill()


def hline(cr, x1, x2, y, color):
    """A 1px hairline. The 0.5 offset keeps Cairo off the seam between rows."""
    rgb(cr, color)
    cr.set_line_width(1)
    cr.move_to(x1, y + 0.5)
    cr.line_to(x2, y + 0.5)
    cr.stroke()


def vline(cr, x, y1, y2, color):
    rgb(cr, color)
    cr.set_line_width(1)
    cr.move_to(x + 0.5, y1)
    cr.line_to(x + 0.5, y2)
    cr.stroke()


def bevel(cr, x, y, w, h, raised=True, fill="face"):
    """An outline with a light and a dark edge tucked just inside it.
    Raised for anything you can press, sunken for anything that only
    displays. `fill` is a palette role name, a colour, or None."""
    if isinstance(fill, str):
        fill = getattr(C, fill)
    if fill is not None:
        rect(cr, x, y, w, h, fill)
    rgb(cr, C.outline)
    cr.set_line_width(1)
    cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
    cr.stroke()
    lt, br = (C.hi, C.shadow) if raised else (C.shadow, C.hi)
    hline(cr, x + 1, x + w - 2, y + 1, lt)
    vline(cr, x + 1, y + 1, y + h - 2, lt)
    hline(cr, x + 1, x + w - 2, y + h - 2, br)
    vline(cr, x + w - 2, y + 1, y + h - 1, br)


def set_font(cr, size):
    """Full hinting, grey antialiasing -- right for any hinted outline font,
    which is every font this can be handed."""
    import cairo

    cr.select_font_face(C.font)
    cr.set_font_size(size)
    opts = cr.get_font_options()
    opts.set_antialias(cairo.ANTIALIAS_GRAY)
    opts.set_hint_style(cairo.HINT_STYLE_FULL)
    cr.set_font_options(opts)


def text(cr, s, x, y, color=None, align="left"):
    """Draw at a baseline in `color` (default: the foreground). Returns the
    advance width."""
    rgb(cr, color or C.fg)
    ext = cr.text_extents(s)
    if align == "center":
        x -= ext.x_advance / 2
    elif align == "right":
        x -= ext.x_advance
    cr.move_to(x, y)
    cr.show_text(s)
    return ext.x_advance


def text_w(cr, s):
    return cr.text_extents(s).x_advance


def ellipsize(cr, s, limit):
    if text_w(cr, s) <= limit:
        return s
    while s and text_w(cr, s + "…") > limit:
        s = s[:-1]
    return s + "…"


def group_box(cr, x, y, w, h, label):
    """An etched frame whose top edge breaks to let the label sit in the
    gap -- the standard grouping device in a Mac OS 8 control panel."""
    set_font(cr, 12)
    notch_x = x + 10
    notch_w = text_w(cr, label) + 8

    for color, off in ((C.shadow, 0.5), (C.hi, 1.5)):
        rgb(cr, color)
        cr.set_line_width(1)
        t = y + off
        cr.move_to(notch_x + notch_w, t)
        cr.line_to(x + w - off, t)
        cr.line_to(x + w - off, y + h - off)
        cr.line_to(x + off, y + h - off)
        cr.line_to(x + off, t)
        cr.line_to(notch_x, t)
        cr.stroke()

    text(cr, label, notch_x + 4, y + 4)


def title_bar(cr, w, title):
    rect(cr, 0, 0, w, TITLEBAR_H, C.face)
    for yy in range(3, TITLEBAR_H - 3, 2):
        hline(cr, 1, w - 2, yy, C.stripe)

    set_font(cr, 12)
    plate_w = text_w(cr, title) + 16
    rect(cr, (w - plate_w) / 2, 1, plate_w, TITLEBAR_H - 2, C.face)
    text(cr, title, w / 2, 14, align="center")

    bevel(cr, 6, 4, 11, 11)          # close box
    hline(cr, 0, w, TITLEBAR_H - 1, C.outline)


def meter(cr, x, y, w, h, frac, color=None):
    """A sunken well with a filled bar -- the Platinum progress idiom."""
    bevel(cr, x, y, w, h, raised=False, fill="well")
    frac = max(0.0, min(1.0, frac))
    fill_w = int((w - 4) * frac)
    if fill_w > 0:
        rect(cr, x + 2, y + 2, fill_w, h - 4, color or C.accent)


def radio(cr, cx, cy, selected):
    import math

    r = 6
    rgb(cr, C.well)
    cr.arc(cx + r, cy, r, 0, 2 * math.pi)
    cr.fill()
    cr.set_line_width(1)
    rgb(cr, C.shadow)
    cr.arc(cx + r, cy, r - 0.5, math.pi * 0.75, math.pi * 1.75)
    cr.stroke()
    rgb(cr, C.outline)
    cr.arc(cx + r, cy, r, 0, 2 * math.pi)
    cr.stroke()
    if selected:
        rgb(cr, C.fg)
        cr.arc(cx + r, cy, 2.5, 0, 2 * math.pi)
        cr.fill()


def button(cr, x, y, w, h, label, pressed=False):
    bevel(cr, x, y, w, h, raised=not pressed,
          fill="face_dk" if pressed else "face")
    set_font(cr, 12)
    text(cr, label, x + w / 2, y + h / 2 + 4, align="center")


def checkbox(cr, x, y, checked):
    bevel(cr, x, y, 12, 12, raised=False, fill="well")
    if checked:
        rgb(cr, C.fg)
        cr.set_line_width(1.5)
        cr.move_to(x + 3, y + 3); cr.line_to(x + 9, y + 9)
        cr.move_to(x + 9, y + 3); cr.line_to(x + 3, y + 9)
        cr.stroke()


# ---------------------------------------------------------------- module


class Module:
    """One stacked section of the container.

    `refresh` runs on a worker thread, so it may block on I/O; everything
    it produces should land on `self` for `draw` to read. `draw` runs on
    the main loop and must not block. Draw through `C`, never a literal
    colour, or the module won't follow the theme.
    """

    title = "Module"
    height = 80          # content height below the group-box label
    interval = 60        # seconds between refreshes; 0 = once only

    def refresh(self):
        """Gather data. Runs off the main thread."""

    def draw(self, cr, x, y, w, panel):
        """Render into the content box. Register clickable regions with
        `panel.hit(name, x, y, w, h)`."""

    def on_click(self, name, panel):
        """A region registered with `panel.hit` was clicked."""


# ------------------------------------------------------------- container


class _Surface(Gtk.DrawingArea):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.hits = {}
        self.pressed = None
        self.set_draw_func(self.on_draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._press)
        click.connect("released", self._release)
        self.add_controller(click)

    # Modules register hit regions during draw, so the drawing code stays
    # the single source of truth for where anything actually is.
    def hit(self, name, x, y, w, h):
        self.hits[name] = (x, y, w, h)

    def _at(self, px, py):
        for name, (x, y, w, h) in self.hits.items():
            if x <= px <= x + w and y <= py <= y + h:
                return name
        return None

    def _press(self, _g, _n, px, py):
        self.pressed = self._at(px, py)
        if self.pressed:
            self.queue_draw()

    def _release(self, _g, _n, px, py):
        hit = self._at(px, py)
        was, self.pressed = self.pressed, None
        self.queue_draw()
        if hit and hit == was:
            self.app.dispatch(hit)

    def on_draw(self, _area, cr, width, height):
        self.hits = {}
        app = self.app

        rect(cr, 0, 0, width, height, C.face)
        title_bar(cr, width, app.title)
        self.hit("__close__", 6, 4, 11, 11)

        rgb(cr, C.outline)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, width - 1, height - 1)
        cr.stroke()

        y = TITLEBAR_H + PAD
        inner_x, inner_w = PAD, width - 2 * PAD
        for mod in app.modules:
            box_h = mod.height + 24
            group_box(cr, inner_x, y, inner_w, box_h, mod.title)
            cy = y + 20
            err = app.errors.get(id(mod))
            try:
                if err:
                    raise RuntimeError(err)
                mod.draw(cr, inner_x + 12, cy, inner_w - 24, self)
            except Exception as exc:  # noqa: BLE001 -- shown in place
                set_font(cr, 12)
                text(cr, ellipsize(cr, str(exc), inner_w - 24),
                     inner_x + 12, cy + 14, C.down)
            y += box_h + PAD


class ControlPanels(Gtk.Application):
    """A desktop-pinned stack of modules on a layer-shell surface."""

    THEME_POLL = 2  # seconds

    def __init__(self, modules, title="Control Panels", width=300,
                 anchors=("top", "right"), margins=(8, 8), app_id=None):
        super().__init__(application_id=app_id or "org.platinum.ControlPanels")
        self.modules = modules
        self.title = title
        self.width = width
        self.anchors = anchors
        self.margins = margins
        self.errors = {}
        self.surface = None
        self.window = None
        self._sig = None

    @property
    def height(self):
        return (TITLEBAR_H + PAD
                + sum(m.height + 24 + PAD for m in self.modules))

    def do_activate(self):
        self._sig = theme_signature()
        load_theme()

        self.window = Gtk.ApplicationWindow(application=self)
        LS.init_for_window(self.window)
        # BOTTOM: above the wallpaper, below every normal window.
        LS.set_layer(self.window, LS.Layer.BOTTOM)
        LS.set_namespace(self.window, "platinum-control-panels")
        # Never take keyboard focus; pointer events still arrive.
        LS.set_keyboard_mode(self.window, LS.KeyboardMode.NONE)
        # Reserve nothing. Note that a zone of 0 still *honours* other
        # surfaces' zones, so a top margin is measured from under the bar.
        LS.set_exclusive_zone(self.window, 0)

        edges = {"top": LS.Edge.TOP, "bottom": LS.Edge.BOTTOM,
                 "left": LS.Edge.LEFT, "right": LS.Edge.RIGHT}
        for name in self.anchors:
            LS.set_anchor(self.window, edges[name], True)
        for name, px in zip(self.anchors, self.margins):
            LS.set_margin(self.window, edges[name], px)

        self.surface = _Surface(self)
        self.surface.set_content_width(self.width)
        self.surface.set_content_height(self.height)
        self.window.set_child(self.surface)
        self.window.present()

        for mod in self.modules:
            self._kick(mod)
            self._schedule(mod)

        # Theme changes arrive by polling a three-value fingerprint rather
        # than a file monitor: theme-set replaces the staged theme directory
        # wholesale, which silently orphans an inotify watch on it.
        GLib.timeout_add_seconds(self.THEME_POLL, self._check_theme)

    # ------------------------------------------------------------ theme

    def _check_theme(self):
        sig = theme_signature()
        if sig != self._sig:
            self._sig = sig
            load_theme()
            self.surface.queue_draw()
        return True

    # ---------------------------------------------------------- refresh

    def _schedule(self, mod):
        """One-shot timers re-armed after each run, so a module that
        changes its own interval (the DJIA radios) takes effect next tick
        instead of never."""
        if mod.interval:
            GLib.timeout_add_seconds(mod.interval, self._tick, mod)

    def _tick(self, mod):
        self._kick(mod)
        self._schedule(mod)
        return False

    def _kick(self, mod):
        threading.Thread(target=self._work, args=(mod,), daemon=True).start()

    def _work(self, mod):
        try:
            mod.refresh()
            err = None
        except Exception as exc:  # noqa: BLE001 -- surfaced in the module box
            err = str(exc)
        GLib.idle_add(self._done, mod, err)

    def _done(self, mod, err):
        if err:
            self.errors[id(mod)] = err
        else:
            self.errors.pop(id(mod), None)
        if self.surface:
            self.surface.queue_draw()
        return False

    # ------------------------------------------------------------ input

    def dispatch(self, name):
        if name == "__close__":
            self.quit()
            return
        for mod in self.modules:
            if mod.on_click(name, self.surface):
                # A module returning True wants a refresh shortly after,
                # e.g. once a volume change has actually landed.
                GLib.timeout_add(250, lambda m=mod: (self._kick(m), False)[1])
        self.surface.queue_draw()


def run(modules, **kwargs):
    import sys

    return ControlPanels(modules, **kwargs).run(sys.argv[:1])
