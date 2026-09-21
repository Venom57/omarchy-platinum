#!/usr/bin/env python3
"""DJIA Watcher -- a Mac OS 8 "Platinum" control panel for the Dow.

Everything inside the window is drawn by hand with Cairo rather than
assembled from GTK widgets. That is the whole point: Platinum's look lives
in details no widget theme exposes -- the pinstriped title bar, the two-tone
bevel on every frame, the way a group box notches its own border to make
room for its label. Fighting Adwaita into that shape is harder than drawing
it, and the result is never quite right.

So the GTK window is a bare undecorated surface and a single DrawingArea.
Hyprland has no server-side decorations anyway, which means the title bar
below is not a replica of a missing one -- it is the only title bar this
window will ever have.

Data comes from Yahoo Finance's chart endpoint, which needs no API key.

Usage:  ./djia.py
"""

import json
import math
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk  # noqa: E402

# --------------------------------------------------------------- palette
#
# The canonical Platinum ramp. Everything in the window is built from these
# six values; the accent appears only in the chart line and the selected
# radio, the way a control panel used color sparingly.

BLACK = (0.00, 0.00, 0.00)
WHITE = (1.00, 1.00, 1.00)
FACE = (0.867, 0.867, 0.867)  # #DDDDDD -- window grey
FACE_DK = (0.800, 0.800, 0.800)  # #CCCCCC -- pinstripe dark, wells
SHADOW = (0.533, 0.533, 0.533)  # #888888 -- bevel shadow
# Title-bar pinstripes. On a 72dpi CRT the stock #CCCCCC read clearly
# against #DDDDDD; on a modern panel that 5% step all but vanishes, so this
# is pulled darker to land where the original looked, not where it measured.
STRIPE = (0.769, 0.769, 0.769)  # #C4C4C4
DIM = (0.463, 0.463, 0.463)  # #767676 -- disabled text

UP = (0.082, 0.486, 0.055)  # classic Mac green
DOWN = (0.733, 0.031, 0.024)  # classic Mac red
ACCENT = (0.235, 0.353, 0.549)  # Platinum blue

# Chicago in two cuts. The bitmap reproduction is pixel-exact at 12px and
# only at 12px, so it draws the UI text; the outline cut draws anything
# larger, where scaling a bitmap would fall apart.
#
# Chicago Kare's charset is period-accurate, which means it stops at the
# characters a 1997 Mac had: no U+2212 minus, no U+2013 en dash. Keep every
# string drawn in FONT_UI to ASCII plus U+2026, or it silently draws blank.
FONT_UI = "Chicago Kare"
FONT_BIG = "ChicagoFLF"

W, H = 340, 376
TITLEBAR_H = 20
PAD = 12

REFRESH_CHOICES = [("30 sec", 30), ("1 min", 60), ("5 min", 300)]
DEFAULT_CHOICE = 1

SYMBOL = "^DJI"
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
TIMEOUT = 15


# ------------------------------------------------------------------ data


class Quote:
    """One snapshot of the index, plus today's intraday closes."""

    def __init__(self, meta, series):
        self.name = meta.get("longName") or meta.get("symbol") or SYMBOL
        self.price = meta.get("regularMarketPrice")
        self.prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        self.high = meta.get("regularMarketDayHigh")
        self.low = meta.get("regularMarketDayLow")
        self.wk_high = meta.get("fiftyTwoWeekHigh")
        self.wk_low = meta.get("fiftyTwoWeekLow")
        self.market_time = meta.get("regularMarketTime")
        self.series = series
        self.fetched_at = time.time()

    @property
    def change(self):
        if self.price is None or self.prev is None:
            return None
        return self.price - self.prev

    @property
    def change_pct(self):
        if self.change is None or not self.prev:
            return None
        return self.change / self.prev * 100.0


def fetch_quote():
    """Pull the Dow from Yahoo. Returns a Quote, or raises the last error.

    Yahoo occasionally 404s or rate-limits one host while the other stays
    up, so both are tried before giving up.
    """
    url = (
        "/v8/finance/chart/"
        + urllib.parse.quote(SYMBOL)
        + "?interval=5m&range=1d"
    )
    last = None
    for host in HOSTS:
        try:
            req = urllib.request.Request(
                "https://" + host + url,
                # Yahoo serves an empty body to the default urllib agent.
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.load(resp)
            result = payload["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            series = [c for c in closes if c is not None]
            return Quote(result["meta"], series)
        except Exception as exc:  # noqa: BLE001 -- surfaced in the UI
            last = exc
    raise last if last else RuntimeError("no hosts tried")


# ------------------------------------------------------- drawing helpers


def rgb(cr, color):
    cr.set_source_rgb(*color)


def rect(cr, x, y, w, h, color):
    rgb(cr, color)
    cr.rectangle(x, y, w, h)
    cr.fill()


def hline(cr, x1, x2, y, color):
    """A 1px hairline. The 0.5 offset keeps Cairo from straddling two rows."""
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
    """The Platinum bevel: a black outline with a light and a dark edge
    tucked just inside it. Raised for buttons and the window frame, sunken
    for wells and anything that displays rather than accepts input."""
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


def set_font(cr, family, size, bitmap=False):
    """Bitmap Chicago must not be antialiased -- smoothing a font that was
    designed as literal pixels is what makes most 'retro' UIs look wrong."""
    cr.select_font_face(family)
    cr.set_font_size(size)
    opts = cr.get_font_options()
    import cairo

    opts.set_antialias(cairo.ANTIALIAS_NONE if bitmap else cairo.ANTIALIAS_GRAY)
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


def group_box(cr, x, y, w, h, label):
    """An etched frame whose top edge breaks to let the label sit in the
    gap -- the standard grouping device in a Mac OS 8 control panel."""
    set_font(cr, FONT_UI, 12, bitmap=True)
    lw = text_w(cr, label)
    notch_x = x + 10
    notch_w = lw + 8

    # Etched frame: a dark line with a white line below and right of it.
    rgb(cr, SHADOW)
    cr.set_line_width(1)
    top = y + 0.5
    cr.move_to(notch_x + notch_w, top)
    cr.line_to(x + w - 0.5, top)
    cr.line_to(x + w - 0.5, y + h - 0.5)
    cr.line_to(x + 0.5, y + h - 0.5)
    cr.line_to(x + 0.5, top)
    cr.line_to(notch_x, top)
    cr.stroke()

    rgb(cr, WHITE)
    cr.move_to(notch_x + notch_w, top + 1)
    cr.line_to(x + w - 1.5, top + 1)
    cr.line_to(x + w - 1.5, y + h - 1.5)
    cr.line_to(x + 1.5, y + h - 1.5)
    cr.line_to(x + 1.5, top + 1)
    cr.line_to(notch_x, top + 1)
    cr.stroke()

    text(cr, label, notch_x + 4, y + 4)


def close_box(cr, x, y, pressed=False):
    """The 11x11 close box that sat at the left end of every title bar."""
    bevel(cr, x, y, 11, 11, raised=not pressed, fill=FACE_DK if pressed else FACE)


def title_bar(cr, w, title, active=True):
    """Pinstripes across the full width, interrupted by a plain plate that
    carries the title. An inactive Platinum window simply loses the stripes,
    which is how you told focus apart without any color at all."""
    rect(cr, 0, 0, w, TITLEBAR_H, FACE)

    if active:
        # Every other row, starting below the top bevel line.
        for yy in range(3, TITLEBAR_H - 3, 2):
            hline(cr, 1, w - 2, yy, STRIPE)

    set_font(cr, FONT_UI, 12, bitmap=True)
    tw = text_w(cr, title)
    plate_w = tw + 16
    plate_x = (w - plate_w) / 2
    if active:
        rect(cr, plate_x, 1, plate_w, TITLEBAR_H - 2, FACE)
    text(cr, title, w / 2, 14, BLACK if active else DIM, align="center")

    close_box(cr, 6, 4)
    hline(cr, 0, w, TITLEBAR_H - 1, BLACK)


def fmt(n, dp=2):
    if n is None:
        return "--"
    return f"{n:,.{dp}f}"


# -------------------------------------------------------------- the panel


class Panel(Gtk.DrawingArea):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.quote = None
        self.error = None
        self.loading = True
        self.choice = DEFAULT_CHOICE
        self.pressed = None  # name of the control currently held down

        self.set_content_width(W)
        self.set_content_height(H)
        self.set_draw_func(self.on_draw)

        click = Gtk.GestureClick()
        click.connect("pressed", self.on_press)
        click.connect("released", self.on_release)
        self.add_controller(click)

        # Hit rectangles, recomputed each frame so the draw code stays the
        # single source of truth for where anything actually is.
        self.hits = {}

    # ------------------------------------------------------------- input

    def on_press(self, gesture, n, px, py):
        for name, hx, hy, hw, hh in self.hits.values():
            if hx <= px <= hx + hw and hy <= py <= hy + hh:
                self.pressed = name
                self.queue_draw()
                return

    def on_release(self, gesture, n, px, py):
        hit = None
        for name, hx, hy, hw, hh in self.hits.values():
            if hx <= px <= hx + hw and hy <= py <= hy + hh:
                hit = name
                break
        was, self.pressed = self.pressed, None
        self.queue_draw()
        if hit is None or hit != was:
            return

        if hit == "close":
            self.app.quit()
        elif hit == "refresh":
            self.app.refresh_now()
        elif hit.startswith("radio"):
            self.choice = int(hit[5:])
            self.app.reschedule(REFRESH_CHOICES[self.choice][1])

    # ------------------------------------------------------------ render

    def on_draw(self, area, cr, width, height):
        self.hits = {}

        rect(cr, 0, 0, width, height, FACE)
        title_bar(cr, width, "DJIA Watcher", active=True)
        self.hits["close"] = ("close", 6, 4, 11, 11)

        # Window frame: one hard outline around everything.
        rgb(cr, BLACK)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, width - 1, height - 1)
        cr.stroke()

        y = TITLEBAR_H + PAD
        y = self.draw_quote_group(cr, PAD, y, width - 2 * PAD)
        y += 10
        y = self.draw_session_group(cr, PAD, y, width - 2 * PAD)
        y += 10
        y = self.draw_interval_group(cr, PAD, y, width - 2 * PAD)
        self.draw_footer(cr, PAD, height - 32, width - 2 * PAD)

    def draw_quote_group(self, cr, x, y, w):
        h = 146
        group_box(cr, x, y, w, h, "Dow Jones Industrial Average")

        if self.error is not None:
            set_font(cr, FONT_UI, 12, bitmap=True)
            text(cr, "Could not reach Yahoo Finance.", x + w / 2, y + 52,
                 DOWN, align="center")
            msg = str(self.error)
            if len(msg) > 38:
                msg = msg[:37] + "…"
            text(cr, msg, x + w / 2, y + 70, DIM, align="center")
            text(cr, "Click Refresh to try again.", x + w / 2, y + 96,
                 DIM, align="center")
            return y + h

        if self.quote is None:
            set_font(cr, FONT_UI, 12, bitmap=True)
            text(cr, "Checking…", x + w / 2, y + 70, DIM, align="center")
            return y + h

        q = self.quote

        # The price, in the outline cut so it can be large and still clean.
        set_font(cr, FONT_BIG, 34)
        text(cr, fmt(q.price), x + w / 2, y + 48, BLACK, align="center")

        # Change, with the classic solid triangle rather than an arrow glyph.
        ch, pct = q.change, q.change_pct
        if ch is not None:
            color = UP if ch >= 0 else DOWN
            set_font(cr, FONT_UI, 12, bitmap=True)
            sign = "+" if ch >= 0 else "-"
            label = f"{sign}{fmt(abs(ch))}   ({pct:+.2f}%)"
            tw = text_w(cr, label)
            tri_w = 9
            start = x + w / 2 - (tw + tri_w + 6) / 2

            cr.save()
            rgb(cr, color)
            ty = y + 66
            if ch >= 0:
                cr.move_to(start, ty)
                cr.line_to(start + tri_w, ty)
                cr.line_to(start + tri_w / 2, ty - 8)
            else:
                cr.move_to(start, ty - 8)
                cr.line_to(start + tri_w, ty - 8)
                cr.line_to(start + tri_w / 2, ty)
            cr.close_path()
            cr.fill()
            cr.restore()

            text(cr, label, start + tri_w + 6, y + 66, color)

        self.draw_chart(cr, x + 12, y + 78, w - 24, 56)
        return y + h

    def draw_chart(self, cr, x, y, w, h):
        """Today's 5-minute closes in a sunken well, with the previous
        close as a dashed baseline so the sign of the day is readable at a
        glance."""
        bevel(cr, x, y, w, h, raised=False, fill=WHITE)
        q = self.quote
        pts = q.series if q else []
        if len(pts) < 2:
            set_font(cr, FONT_UI, 12, bitmap=True)
            text(cr, "No intraday data", x + w / 2, y + h / 2 + 4, DIM,
                 align="center")
            return

        inner_x, inner_y = x + 2, y + 2
        inner_w, inner_h = w - 4, h - 4

        lo, hi = min(pts), max(pts)
        if q.prev is not None:
            lo, hi = min(lo, q.prev), max(hi, q.prev)
        span = (hi - lo) or 1.0
        pad = span * 0.12
        lo, hi = lo - pad, hi + pad
        span = hi - lo

        def sx(i):
            return inner_x + i * inner_w / (len(pts) - 1)

        def sy(v):
            return inner_y + inner_h - (v - lo) / span * inner_h

        if q.prev is not None:
            cr.save()
            rgb(cr, SHADOW)
            cr.set_line_width(1)
            cr.set_dash([2, 2])
            cr.move_to(inner_x, sy(q.prev) + 0.5)
            cr.line_to(inner_x + inner_w, sy(q.prev) + 0.5)
            cr.stroke()
            cr.restore()

        cr.save()
        cr.rectangle(inner_x, inner_y, inner_w, inner_h)
        cr.clip()
        rgb(cr, ACCENT)
        cr.set_line_width(1.5)
        cr.move_to(sx(0), sy(pts[0]))
        for i, v in enumerate(pts[1:], start=1):
            cr.line_to(sx(i), sy(v))
        cr.stroke()
        cr.restore()

    def draw_session_group(self, cr, x, y, w):
        h = 92
        group_box(cr, x, y, w, h, "Session")
        q = self.quote
        set_font(cr, FONT_UI, 12, bitmap=True)

        rows = [
            ("Previous close", q.prev if q else None),
            ("Day high", q.high if q else None),
            ("Day low", q.low if q else None),
            ("52-week range", None),
        ]
        ry = y + 26
        for label, val in rows[:3]:
            text(cr, label, x + 14, ry, BLACK)
            text(cr, fmt(val), x + w - 14, ry, BLACK, align="right")
            ry += 16

        text(cr, "52-week range", x + 14, ry, BLACK)
        if q and q.wk_low is not None and q.wk_high is not None:
            rng = f"{fmt(q.wk_low, 0)} - {fmt(q.wk_high, 0)}"
        else:
            rng = "--"
        text(cr, rng, x + w - 14, ry, BLACK, align="right")
        return y + h

    def draw_interval_group(self, cr, x, y, w):
        h = 42
        group_box(cr, x, y, w, h, "Check Every")
        set_font(cr, FONT_UI, 12, bitmap=True)

        cx = x + 14
        for i, (label, _) in enumerate(REFRESH_CHOICES):
            cy = y + 22
            self.hits[f"radio{i}"] = (f"radio{i}", cx - 2, cy - 9, 76, 18)
            self.draw_radio(cr, cx, cy, selected=(i == self.choice))
            text(cr, label, cx + 18, cy + 4, BLACK)
            cx += 76
        return y + h

    def draw_radio(self, cr, cx, cy, selected):
        r = 6
        # A sunken ring: shadow on the upper-left arc, white on the lower.
        rgb(cr, WHITE)
        cr.arc(cx + r, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_line_width(1)
        rgb(cr, SHADOW)
        cr.arc(cx + r, cy, r - 0.5, math.pi * 0.75, math.pi * 1.75)
        cr.stroke()
        rgb(cr, (0.75, 0.75, 0.75))
        cr.arc(cx + r, cy, r - 0.5, math.pi * 1.75, math.pi * 2.75)
        cr.stroke()
        rgb(cr, BLACK)
        cr.arc(cx + r, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if selected:
            rgb(cr, BLACK)
            cr.arc(cx + r, cy, 2.5, 0, 2 * math.pi)
            cr.fill()

    def draw_footer(self, cr, x, y, w):
        set_font(cr, FONT_UI, 12, bitmap=True)
        if self.loading:
            stamp = "Checking…"
        elif self.quote is not None:
            t = datetime.fromtimestamp(self.quote.fetched_at)
            stamp = "Updated " + t.strftime("%H:%M:%S")
        else:
            stamp = "Not updated"
        text(cr, stamp, x, y + 15, DIM)

        bw, bh = 78, 21
        bx, by = x + w - bw, y + 1
        down = self.pressed == "refresh"
        self.hits["refresh"] = ("refresh", bx, by, bw, bh)
        bevel(cr, bx, by, bw, bh, raised=not down,
              fill=FACE_DK if down else FACE)
        set_font(cr, FONT_UI, 12, bitmap=True)
        text(cr, "Refresh", bx + bw / 2, by + 15, BLACK, align="center")


# ---------------------------------------------------------------- the app


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.platinum.DJIAWatcher")
        self.timer = None
        self.panel = None
        self.window = None

    def do_activate(self):
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("DJIA Watcher")
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_default_size(W, H)

        self.panel = Panel(self)
        self.window.set_child(self.panel)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.window.add_controller(keys)

        self.window.present()
        self.refresh_now()
        self.reschedule(REFRESH_CHOICES[DEFAULT_CHOICE][1])

    def on_key(self, ctrl, keyval, keycode, state):
        """Ctrl-W / Ctrl-Q close, Ctrl-R refreshes.

        Deliberately not Escape, and not a bare letter: this panel is meant
        to sit open on the desktop, and a stray keystroke landing on it --
        Escape dismissing the launcher, say -- should not take it down with
        it. The close box is the primary way out, as it was on a Mac.
        """
        ctrl_held = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if not ctrl_held:
            return False
        if keyval in (Gdk.KEY_w, Gdk.KEY_q):
            self.quit()
            return True
        if keyval == Gdk.KEY_r:
            self.refresh_now()
            return True
        return False

    def reschedule(self, seconds):
        if self.timer is not None:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add_seconds(seconds, self.on_tick)

    def on_tick(self):
        self.refresh_now()
        return True  # keep the timer alive

    def refresh_now(self):
        self.panel.loading = True
        self.panel.queue_draw()
        # Network off the main loop, or the window freezes for the duration.
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            q = fetch_quote()
            GLib.idle_add(self._done, q, None)
        except Exception as exc:  # noqa: BLE001 -- shown in the panel
            GLib.idle_add(self._done, None, exc)

    def _done(self, quote, error):
        self.panel.loading = False
        if quote is not None:
            self.panel.quote = quote
            self.panel.error = None
        else:
            self.panel.error = error
        self.panel.queue_draw()
        return False


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
