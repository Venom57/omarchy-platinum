"""Platinum chrome, and the desktop-pinned container the modules live in.

Two things live here.

The first is the drawing kit: the Mac OS 8 "Platinum" palette and the
primitives built from it -- the two-tone bevel, the group box that notches
its own border for its label, the pinstriped title bar, radios, buttons and
meters. All Cairo, because Platinum lives in details no widget theme
exposes and drawing it is less work than fighting one into that shape.

The second is `ControlPanels`, which is not a window. It is a layer-shell
surface on the BOTTOM layer, which puts it above the wallpaper and below
every normal window -- pinned to the desktop the way a Mac desk accessory
sat there, rather than joining Hyprland's tiling layout. It takes no
keyboard focus and reserves no exclusive zone, so it never steals input or
pushes windows around. Pointer events still reach it, so the interactive
bits work.

Modules are stacked inside one frame instead of each being its own window,
so the desktop carries a single tidy object rather than a scatter of them.
"""

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, GLib, Gtk4LayerShell as LS  # noqa: E402

# --------------------------------------------------------------- palette

BLACK = (0.00, 0.00, 0.00)
WHITE = (1.00, 1.00, 1.00)
FACE = (0.867, 0.867, 0.867)   # #DDDDDD -- window grey
FACE_DK = (0.800, 0.800, 0.800)  # #CCCCCC -- wells
SHADOW = (0.533, 0.533, 0.533)   # #888888 -- bevel shadow
# On a 72dpi CRT the stock #CCCCCC pinstripe read clearly against #DDDDDD;
# on a modern panel that 5% step all but vanishes, so this lands where the
# original looked rather than where it measured.
STRIPE = (0.769, 0.769, 0.769)   # #C4C4C4
DIM = (0.463, 0.463, 0.463)      # #767676 -- disabled text

UP = (0.082, 0.486, 0.055)       # classic Mac green
DOWN = (0.733, 0.031, 0.024)     # classic Mac red
ACCENT = (0.235, 0.353, 0.549)   # Platinum blue

# ChicagoFLF, not the Chicago Kare bitmap reproduction: Kare ships no
# hinting tables, so it only lands cleanly at exact integer pixel sizes and
# goes mushy on a fractionally-scaled display. FLF is hinted and stays
# crisp, and it has the U+2212 and U+2013 that Kare lacks.
FONT = "ChicagoFLF"

TITLEBAR_H = 20
PAD = 10


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


def bevel(cr, x, y, w, h, raised=True, fill=FACE):
    """A black outline with a light and a dark edge tucked just inside it.
    Raised for anything you can press, sunken for anything that only
    displays."""
    if fill is not None:
        rect(cr, x, y, w, h, fill)
    rgb(cr, BLACK)
    cr.set_line_width(1)
    cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
    cr.stroke()
    lt, br = (WHITE, SHADOW) if raised else (SHADOW, WHITE)
    hline(cr, x + 1, x + w - 2, y + 1, lt)
    vline(cr, x + 1, y + 1, y + h - 2, lt)
    hline(cr, x + 1, x + w - 2, y + h - 2, br)
    vline(cr, x + w - 2, y + 1, y + h - 1, br)


def set_font(cr, size, family=FONT):
    """Full hinting, grey antialiasing. ChicagoFLF carries real hinting
    instructions, so letting freetype snap stems to the grid is what keeps
    it sharp at small sizes rather than blurring it."""
    import cairo

    cr.select_font_face(family)
    cr.set_font_size(size)
    opts = cr.get_font_options()
    opts.set_antialias(cairo.ANTIALIAS_GRAY)
    opts.set_hint_style(cairo.HINT_STYLE_FULL)
    cr.set_font_options(opts)


def text(cr, s, x, y, color=BLACK, align="left"):
    """Draw at a baseline. Returns the advance width."""
    rgb(cr, color)
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
    """Trim to fit, with a real ellipsis. ChicagoFLF has U+2026."""
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

    for color, off in ((SHADOW, 0.5), (WHITE, 1.5)):
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
    """Pinstripes across the full width, interrupted by a plain plate
    carrying the title, with the close box at the left."""
    rect(cr, 0, 0, w, TITLEBAR_H, FACE)
    for yy in range(3, TITLEBAR_H - 3, 2):
        hline(cr, 1, w - 2, yy, STRIPE)

    set_font(cr, 12)
    plate_w = text_w(cr, title) + 16
    rect(cr, (w - plate_w) / 2, 1, plate_w, TITLEBAR_H - 2, FACE)
    text(cr, title, w / 2, 14, BLACK, align="center")

    bevel(cr, 6, 4, 11, 11)          # close box
    hline(cr, 0, w, TITLEBAR_H - 1, BLACK)


def meter(cr, x, y, w, h, frac, color=ACCENT):
    """A sunken well with a filled bar -- the Platinum progress idiom."""
    bevel(cr, x, y, w, h, raised=False, fill=WHITE)
    frac = max(0.0, min(1.0, frac))
    fill_w = int((w - 4) * frac)
    if fill_w > 0:
        rect(cr, x + 2, y + 2, fill_w, h - 4, color)


def radio(cr, cx, cy, selected):
    import math

    r = 6
    rgb(cr, WHITE)
    cr.arc(cx + r, cy, r, 0, 2 * math.pi)
    cr.fill()
    cr.set_line_width(1)
    rgb(cr, SHADOW)
    cr.arc(cx + r, cy, r - 0.5, math.pi * 0.75, math.pi * 1.75)
    cr.stroke()
    rgb(cr, BLACK)
    cr.arc(cx + r, cy, r, 0, 2 * math.pi)
    cr.stroke()
    if selected:
        rgb(cr, BLACK)
        cr.arc(cx + r, cy, 2.5, 0, 2 * math.pi)
        cr.fill()


def button(cr, x, y, w, h, label, pressed=False):
    bevel(cr, x, y, w, h, raised=not pressed, fill=FACE_DK if pressed else FACE)
    set_font(cr, 12)
    text(cr, label, x + w / 2, y + h / 2 + 4, BLACK, align="center")


# ---------------------------------------------------------------- module


class Module:
    """One stacked section of the container.

    `refresh` runs on a worker thread, so it may block on I/O; everything
    it produces should land on `self` for `draw` to read. `draw` runs on
    the main loop and must not block.
    """

    title = "Module"
    height = 80          # content height below the group-box label
    interval = 60        # seconds between refreshes; 0 = once only

    def refresh(self):
        """Gather data. Runs off the main thread. Exceptions are caught by
        the container and surfaced in place of the module's content."""

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

        rect(cr, 0, 0, width, height, FACE)
        title_bar(cr, width, app.title)
        self.hit("__close__", 6, 4, 11, 11)

        rgb(cr, BLACK)
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
            if err:
                set_font(cr, 12)
                text(cr, ellipsize(cr, err, inner_w - 24),
                     inner_x + 12, cy + 14, DOWN)
            else:
                try:
                    mod.draw(cr, inner_x + 12, cy, inner_w - 24, self)
                except Exception as exc:  # noqa: BLE001 -- shown in place
                    set_font(cr, 12)
                    text(cr, ellipsize(cr, f"draw failed: {exc}", inner_w - 24),
                         inner_x + 12, cy + 14, DOWN)
            y += box_h + PAD


class ControlPanels(Gtk.Application):
    """A desktop-pinned stack of modules on a layer-shell surface."""

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

    # ------------------------------------------------------------ layout

    @property
    def height(self):
        return (TITLEBAR_H + PAD
                + sum(m.height + 24 + PAD for m in self.modules))

    # ----------------------------------------------------------- startup

    def do_activate(self):
        self.window = Gtk.ApplicationWindow(application=self)

        LS.init_for_window(self.window)
        # BOTTOM sits above the wallpaper and below every normal window --
        # on the desktop, not in the window stack.
        LS.set_layer(self.window, LS.Layer.BOTTOM)
        LS.set_namespace(self.window, "platinum-control-panels")
        # Never take keyboard focus; pointer events still arrive, so the
        # interactive controls keep working.
        LS.set_keyboard_mode(self.window, LS.KeyboardMode.NONE)
        # Reserve nothing: the bar and tiled windows must not move for us.
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
            if mod.interval:
                GLib.timeout_add_seconds(
                    mod.interval, self._tick, mod)

    # ---------------------------------------------------------- refresh

    def _tick(self, mod):
        self._kick(mod)
        return True

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
            mod.on_click(name, self.surface)
        for mod in self.modules:
            self._kick(mod)
        self.surface.queue_draw()


def run(modules, **kwargs):
    import sys

    return ControlPanels(modules, **kwargs).run(sys.argv[:1])
