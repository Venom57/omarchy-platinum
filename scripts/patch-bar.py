#!/usr/bin/env python3
"""Apply the two Platinum patches to a cloned Omarchy bar plugin.

Hyprland has no server-side decorations and Omarchy's bar exposes no border
token, so the black rule that separates a Mac menu bar from the desktop has
to be drawn by the bar itself. That is patch one. Patch two marks the font
property so the theme-set hook can swap Chicago in and out.

Both patches are idempotent -- running this twice is a no-op -- because
install.sh may be re-run over an existing clone.

Usage:  patch-bar.py /path/to/<user>.bar/Bar.qml
"""

import sys
from pathlib import Path

RULE_MARKER = "Platinum menu bar rule"
FONT_MARKER = "// PLATINUM-BAR-FONT"

# Inserted immediately before the bar panel's tooltip window, which puts it
# inside BarPanel and on top of the bar's own background.
RULE_ANCHOR = """    PopupWindow {
      id: tooltipWindow
"""

RULE = """    // Platinum menu bar rule. Mac OS 8 divided the menu bar from the
    // desktop with a single hard black line -- no shadow, no gradient, no
    // fade. Drawn on whichever edge faces the desktop so it survives
    // `omarchy bar move`, and skipped entirely when the bar is transparent
    // (there is no bar surface to terminate).
    Rectangle {
      z: 100
      visible: !root.transparent
      color: "#000000"
      width: root.vertical ? 1 : parent.width
      height: root.vertical ? parent.height : 1
      anchors {
        top: root.position === "bottom" ? parent.top : undefined
        bottom: root.position === "top" ? parent.bottom : undefined
        left: root.position === "right" ? parent.left : undefined
        right: root.position === "left" ? parent.right : undefined
      }
    }

"""

FONT_OLD = "  property string fontFamily: Style.font.family\n"

FONT_NEW = """  // Bar font. Normally this follows Style.font.family -- the fontconfig
  // `monospace` alias that `omarchy font set` writes -- so the font selector
  // controls the bar like it controls everything else.
  //
  // The line below is rewritten in place by the theme-set hook
  // (~/.config/omarchy/hooks/theme-set.d/platinum-chrome), which swaps in
  // Chicago while the Platinum theme is active and puts it back on the way
  // out. Keep it on one line and keep the marker; the hook matches on it.
  property string fontFamily: Style.font.family  // PLATINUM-BAR-FONT
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"patch-bar: no such file: {path}", file=sys.stderr)
        return 1

    src = path.read_text()
    applied = []

    if RULE_MARKER in src:
        applied.append("rule already present")
    elif src.count(RULE_ANCHOR) == 1:
        src = src.replace(RULE_ANCHOR, RULE + RULE_ANCHOR, 1)
        applied.append("rule inserted")
    else:
        # Upstream moved the anchor. Say so rather than guessing at a
        # location and silently producing a bar that will not load.
        print(
            "patch-bar: could not find the tooltip-window anchor "
            f"(matched {src.count(RULE_ANCHOR)} times); skipping the menu bar "
            "rule. The theme still works, just without the black rule.",
            file=sys.stderr,
        )
        applied.append("rule SKIPPED")

    if FONT_MARKER in src:
        applied.append("font marker already present")
    elif src.count(FONT_OLD) == 1:
        src = src.replace(FONT_OLD, FONT_NEW, 1)
        applied.append("font marker added")
    else:
        print(
            "patch-bar: could not find the fontFamily property "
            f"(matched {src.count(FONT_OLD)} times); the theme-set hook will "
            "not be able to set the bar font.",
            file=sys.stderr,
        )
        applied.append("font marker SKIPPED")

    path.write_text(src)
    print("patch-bar: " + "; ".join(applied))
    return 0


if __name__ == "__main__":
    sys.exit(main())
