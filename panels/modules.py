"""The control panel modules that stack inside the Platinum container.

Each one gathers its data in `refresh` (worker thread, may block) and
renders it in `draw` (main loop, must not). Clickable regions are
registered with `panel.hit` during draw and come back through `on_click`.
"""

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime

from platinum import (
    ACCENT, BLACK, DIM, DOWN, SHADOW, UP, WHITE,
    bevel, button, ellipsize, meter, radio, rect, rgb, set_font, text,
    text_w,
)
from platinum import Module


def _run(*cmd, timeout=5):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, check=True).stdout


# ------------------------------------------------------------------ DJIA


class DJIA(Module):
    """The Dow, from Yahoo Finance's chart endpoint -- no API key, but
    undocumented, so both hosts are tried before giving up."""

    title = "Dow Jones Industrial Average"
    height = 118
    CHOICES = [("30 sec", 30), ("1 min", 60), ("5 min", 300)]
    HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

    def __init__(self):
        self.choice = 1
        self.interval = self.CHOICES[self.choice][1]
        self.price = self.prev = None
        self.series = []
        self.stamp = None

    def refresh(self):
        path = ("/v8/finance/chart/" + urllib.parse.quote("^DJI")
                + "?interval=5m&range=1d")
        last = None
        for host in self.HOSTS:
            try:
                req = urllib.request.Request(
                    "https://" + host + path,
                    # Yahoo serves an empty body to urllib's default agent.
                    headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.load(resp)["chart"]["result"][0]
                meta = result["meta"]
                self.price = meta.get("regularMarketPrice")
                self.prev = (meta.get("chartPreviousClose")
                             or meta.get("previousClose"))
                closes = result["indicators"]["quote"][0]["close"]
                self.series = [c for c in closes if c is not None]
                self.stamp = time.time()
                return
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise RuntimeError(f"Yahoo Finance unreachable: {last}")

    def draw(self, cr, x, y, w, panel):
        if self.price is None:
            set_font(cr, 12)
            text(cr, "Checking…", x + w / 2, y + 40, DIM, align="center")
            return

        set_font(cr, 26)
        text(cr, f"{self.price:,.2f}", x + w / 2, y + 24, BLACK, align="center")

        if self.prev:
            ch = self.price - self.prev
            pct = ch / self.prev * 100
            color = UP if ch >= 0 else DOWN
            sign = "+" if ch >= 0 else "−"
            set_font(cr, 12)
            label = f"{sign}{abs(ch):,.2f}  ({pct:+.2f}%)"
            lw = text_w(cr, label)
            sx = x + w / 2 - (lw + 14) / 2
            rgb(cr, color)
            if ch >= 0:
                cr.move_to(sx, y + 41); cr.line_to(sx + 9, y + 41)
                cr.line_to(sx + 4.5, y + 33)
            else:
                cr.move_to(sx, y + 33); cr.line_to(sx + 9, y + 33)
                cr.line_to(sx + 4.5, y + 41)
            cr.close_path(); cr.fill()
            text(cr, label, sx + 14, y + 41, color)

        self._chart(cr, x, y + 50, w, 40)

        cx = x
        for i, (label, _) in enumerate(self.CHOICES):
            panel.hit(f"djia:{i}", cx - 2, y + 98, 74, 18)
            radio(cr, cx, y + 107, i == self.choice)
            set_font(cr, 12)
            text(cr, label, cx + 17, y + 111, BLACK)
            cx += 76

    def _chart(self, cr, x, y, w, h):
        bevel(cr, x, y, w, h, raised=False, fill=WHITE)
        pts = self.series
        if len(pts) < 2:
            return
        lo, hi = min(pts), max(pts)
        if self.prev:
            lo, hi = min(lo, self.prev), max(hi, self.prev)
        pad = (hi - lo or 1) * 0.12
        lo, hi = lo - pad, hi + pad
        ix, iy, iw, ih = x + 2, y + 2, w - 4, h - 4

        def sx(i): return ix + i * iw / (len(pts) - 1)
        def sy(v): return iy + ih - (v - lo) / (hi - lo) * ih

        if self.prev:
            cr.save(); rgb(cr, SHADOW); cr.set_line_width(1)
            cr.set_dash([2, 2])
            cr.move_to(ix, sy(self.prev) + 0.5)
            cr.line_to(ix + iw, sy(self.prev) + 0.5); cr.stroke()
            cr.restore()
        cr.save(); cr.rectangle(ix, iy, iw, ih); cr.clip()
        rgb(cr, ACCENT); cr.set_line_width(1.5)
        cr.move_to(sx(0), sy(pts[0]))
        for i, v in enumerate(pts[1:], 1):
            cr.line_to(sx(i), sy(v))
        cr.stroke(); cr.restore()

    def on_click(self, name, panel):
        if name.startswith("djia:"):
            self.choice = int(name[5:])
            self.interval = self.CHOICES[self.choice][1]


# ---------------------------------------------------------------- Memory


class Memory(Module):
    """RAM and swap from /proc/meminfo, plus the heaviest processes.

    'Used' is MemTotal minus MemAvailable -- the kernel's own estimate of
    what could be handed out without swapping -- rather than MemTotal minus
    MemFree, which counts reclaimable page cache as used and makes every
    Linux box look nearly full.
    """

    title = "Memory"
    height = 106
    interval = 5

    def __init__(self):
        self.total = self.used = self.swap_total = self.swap_used = 0
        self.top = []

    def refresh(self):
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        self.total = info["MemTotal"]
        self.used = info["MemTotal"] - info["MemAvailable"]
        self.swap_total = info.get("SwapTotal", 0)
        self.swap_used = self.swap_total - info.get("SwapFree", 0)

        out = _run("ps", "-eo", "rss=,comm=", "--sort=-rss")
        top = []
        for line in out.splitlines()[:3]:
            rss, _, comm = line.strip().partition(" ")
            top.append((comm.strip(), int(rss) * 1024))
        self.top = top

    @staticmethod
    def _gb(n):
        return f"{n / 1024**3:.1f} GB"

    def draw(self, cr, x, y, w, panel):
        set_font(cr, 12)
        frac = self.used / self.total if self.total else 0
        text(cr, "Built-in Memory", x, y + 12, BLACK)
        text(cr, f"{self._gb(self.used)} of {self._gb(self.total)}",
             x + w, y + 12, BLACK, align="right")
        meter(cr, x, y + 17, w, 12, frac,
              DOWN if frac > 0.9 else ACCENT)

        sfrac = self.swap_used / self.swap_total if self.swap_total else 0
        text(cr, "Virtual Memory", x, y + 44, BLACK)
        text(cr, self._gb(self.swap_used) if self.swap_total else "Off",
             x + w, y + 44, DIM if not self.swap_used else BLACK, align="right")
        meter(cr, x, y + 49, w, 8, sfrac, SHADOW)

        ty = y + 76
        for comm, rss in self.top:
            text(cr, ellipsize(cr, comm, w - 70), x, ty, DIM)
            text(cr, f"{rss / 1024**2:,.0f} MB", x + w, ty, DIM, align="right")
            ty += 14


# ----------------------------------------------------------- Date & Time


class DateTime(Module):
    """The clock, the zone, and whether NTP has the clock in hand -- the
    one thing worth knowing about system time that the bar clock can't
    show you."""

    title = "Date & Time"
    height = 64
    interval = 30

    def __init__(self):
        self.zone = "…"
        self.ntp = None
        self.synced = None

    def refresh(self):
        props = {}
        for line in _run("timedatectl", "show").splitlines():
            k, _, v = line.partition("=")
            props[k] = v
        self.zone = props.get("Timezone", "?")
        self.ntp = props.get("NTP") == "yes"
        self.synced = props.get("NTPSynchronized") == "yes"

    def draw(self, cr, x, y, w, panel):
        # Read the clock at draw time, not refresh time, so the seconds
        # aren't stale by up to the refresh interval.
        now = datetime.now()
        set_font(cr, 22)
        text(cr, now.strftime("%-I:%M %p"), x, y + 22, BLACK)
        set_font(cr, 12)
        text(cr, now.strftime("%A, %B %-d, %Y"), x, y + 40, BLACK)

        zone = self.zone.replace("_", " ")
        text(cr, ellipsize(cr, zone, w - 120), x, y + 58, DIM)

        if self.synced is None:
            status, color = "…", DIM
        elif self.synced:
            status, color = "Network time", UP
        elif self.ntp:
            status, color = "Syncing…", DIM
        else:
            status, color = "Manual", DOWN
        text(cr, status, x + w, y + 58, color, align="right")


# ----------------------------------------------------------------- Sound


class Sound(Module):
    """Output volume and mute, via wpctl on the default sink.

    Changes go through `omarchy audio output volume`, not wpctl directly,
    so Omarchy's own OSD fires and the bar's volume widget stays in step.
    """

    title = "Sound"
    height = 58
    interval = 3
    STEP = 5

    def __init__(self):
        self.volume = None
        self.muted = False
        self.sink = "…"

    def refresh(self):
        # "Volume: 0.40" or "Volume: 0.40 [MUTED]"
        out = _run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@").strip()
        parts = out.split()
        self.volume = float(parts[1])
        self.muted = "[MUTED]" in out
        try:
            info = _run("wpctl", "inspect", "@DEFAULT_AUDIO_SINK@")
            for line in info.splitlines():
                if "node.description" in line:
                    self.sink = line.split("=", 1)[1].strip().strip('"')
                    break
        except Exception:  # noqa: BLE001 -- the name is cosmetic
            pass

    def draw(self, cr, x, y, w, panel):
        set_font(cr, 12)
        text(cr, ellipsize(cr, self.sink, w), x, y + 12, BLACK)

        vol = self.volume or 0.0
        bw = 26
        mw = w - 2 * bw - 60
        meter(cr, x, y + 20, mw, 14, min(vol, 1.0),
              SHADOW if self.muted else ACCENT)
        pct = "Muted" if self.muted else f"{vol * 100:.0f}%"
        text(cr, pct, x + mw + 6, y + 31, DIM if self.muted else BLACK)

        bx = x + w - 2 * bw - 2
        for name, label in (("sound:down", "−"), ("sound:up", "+")):
            panel.hit(name, bx, y + 18, bw, 18)
            button(cr, bx, y + 18, bw, 18, label, panel.pressed == name)
            bx += bw + 2

        panel.hit("sound:mute", x, y + 40, 90, 16)
        box = (x, y + 42, 12, 12)
        bevel(cr, *box, raised=False, fill=WHITE)
        if self.muted:
            rgb(cr, BLACK); cr.set_line_width(1.5)
            cr.move_to(x + 3, y + 45); cr.line_to(x + 9, y + 51)
            cr.move_to(x + 9, y + 45); cr.line_to(x + 3, y + 51)
            cr.stroke()
        text(cr, "Mute", x + 18, y + 53, BLACK)

    def on_click(self, name, panel):
        cmd = {"sound:up": f"+{self.STEP}", "sound:down": f"-{self.STEP}",
               "sound:mute": "mute-toggle"}.get(name)
        if cmd:
            subprocess.Popen(["omarchy", "audio", "output", "volume", cmd],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
