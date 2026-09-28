#!/usr/bin/env python3
"""Control Panels -- a desktop-pinned stack of Platinum control panels.

Sits on the layer-shell BOTTOM layer: above the wallpaper, below every
window, never taking keyboard focus. Edit MODULES to choose and order what
appears; each module lives in modules.py and draws with the kit in
platinum.py.
"""

import os
import sys

# gtk4-layer-shell has to be loaded before libwayland-client or
# init_for_window() silently does nothing and the window comes up as an
# ordinary toplevel. From Python the only reliable way to win that race is
# LD_PRELOAD, so re-exec with it set rather than make every launcher
# remember to.
_LAYER_SHELL = "/usr/lib/libgtk4-layer-shell.so"
if _LAYER_SHELL not in os.environ.get("LD_PRELOAD", "") and os.path.exists(_LAYER_SHELL):
    os.environ["LD_PRELOAD"] = ":".join(
        p for p in (_LAYER_SHELL, os.environ.get("LD_PRELOAD")) if p)
    os.execv(sys.executable, [sys.executable, *sys.argv])

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from modules import DJIA, DateTime, Memory, Sound  # noqa: E402
from platinum import run  # noqa: E402

MODULES = [DateTime(), DJIA(), Memory(), Sound()]

if __name__ == "__main__":
    sys.exit(run(MODULES, title="Control Panels", width=300,
                 anchors=("top", "right"), margins=(8, 10)))
