# Platinum for Omarchy

A Mac OS 8 theme for [Omarchy](https://omarchy.org/) — the "Platinum"
appearance Apple designed for Copland and shipped in Mac OS 8.

Grey `#DDDDDD` surfaces, hard two-tone bevels lit from the top-left, square
everything, zero animation, and Chicago on the menu bar.

> **Copland** was Apple's next-generation OS, started in 1994 and cancelled
> in 1996. It never shipped, but its interface work did: the Platinum
> appearance that arrived in Mac OS 8 in 1997. That is what this theme
> targets.

## Install

```bash
git clone https://github.com/Venom57/omarchy-platinum
cd omarchy-platinum
./install.sh
```

Options:

| Flag | Effect |
|---|---|
| `--with-panels` | also install the DJIA Watcher control panel |
| `--no-fonts` | skip the font download (offline installs) |

Re-running is safe; every step is idempotent.

### Do not use `omarchy theme install`

`omarchy theme install <url>` clones the repo into your themes directory,
and Omarchy then detects the `.git` directory and **strips every `*.lua`
file** from the theme — it refuses to stage anything from a cloned theme
that runs code. Platinum's `hyprland.lua` carries the rounding, borders,
gaps, opacity, animations and bevel gradient, so a git install silently
drops most of the theme.

`install.sh` copies the theme into place *without* a `.git` directory,
which keeps all of it.

## What it does

### In the theme (`theme/`) — managed by `omarchy theme set`

| File | Contents |
|---|---|
| `colors.toml` | The Platinum ramp, plus ANSI colors from the 1987 Macintosh II palette, darkened where the original was illegible on light grey |
| `shell.toml` | Bar, menu, popup and lock surfaces: fully opaque, 1px hard control outlines, classic highlight blue |
| `hyprland.lua` | `rounding = 0`, `border_size = 3`, animations off, blur and shadow off, full opacity, the bevel gradient, and the float rule for control panels |
| `gtk.css` | GTK override layer: grey surfaces, beveled buttons, recessed text fields |
| `backgrounds/` | Four desktop patterns, default being the authentic 1px 50% dither |

Because `hyprctl reload` re-parses from scratch, everything in
`hyprland.lua` simply stops applying when you switch to another theme. No
undo logic is involved.

### Outside the theme — managed by the hook

Two things a theme file cannot reach:

- **The bar font.** A QML property on a cloned bar plugin, not theme
  config. `scripts/patch-bar.py` adds a marker to it, and
  `hooks/platinum-chrome` rewrites it on every theme change.
- **The GTK font and CSS.** Outside Omarchy's theming entirely.

The bar clone also gains the single hard black rule under the menu bar,
which Omarchy's bar exposes no token for.

### Fonts

Installed to `~/.local/share/fonts/chicago/`, no root required:

- **ChicagoFLF** — public domain, from [Font Library](https://fontlibrary.org/en/font/chicagoflf).
  Used for the bar, GTK apps and the control panel. The zip is
  checksum-verified against the `ttf-chicagoflf` AUR PKGBUILD.

Chicago Kare, the bitmap reproduction, is deliberately **not** used. It
traces the original bitmap, so its outlines are pixel staircases, and it
ships no hinting tables (`cvt`/`fpgm`/`prep`). It therefore only lands
cleanly when one font pixel maps to exactly one screen pixel — which never
happens on a fractionally-scaled display, where a 12px UI font is rendered
at 15 physical pixels. It looks mushy at every size there. ChicagoFLF is a
hinted outline design and stays crisp.

Terminals are deliberately left on your existing mono font. Chicago is
proportional, and `omarchy font set` writes the system `monospace` alias —
pointing it at Chicago would wreck every terminal.

## Known limits

These are Omarchy and Hyprland constraints, not oversights:

- **No title bars.** Hyprland has no server-side decorations at all, so
  windows get a beveled border and nothing else — no pinstripes, no
  close/collapse/zoom boxes. The included control panel draws its own,
  because it owns its window contents.
- **No global menu bar.** File/Edit/View at the top of the screen needs a
  protocol Wayland does not have.
- **Menus and popups follow the font selector, not Chicago.** Their font
  comes from `OMARCHY_MENU_FONT`, which is only settable through `hl.env`.
  That calls `setenv()` inside Hyprland, so it cannot be *unset* — deleting
  the line and reloading leaves the old value live for the whole session,
  and every shell Hyprland spawns inherits it. It *can* be overwritten, and
  Omarchy treats an empty value as absent, so `install.sh` writes
  `hl.env("OMARCHY_MENU_FONT", "")` to neutralise it permanently.

  Scoping it per-theme would additionally need a shell restart on every
  switch, since the value is read once at startup — not worth it for a
  font. Cloning the menu plugin to sidestep that does **not** work: Omarchy
  refuses to hand a service-capable API to a third-party plugin while the
  bar is itself a clone, which breaks the menu's own bar widget.
- **No period cursor.** No classic Mac cursor theme is packaged for Linux.

## The control panel

`panels/djia.py` is a Mac OS 8 control panel that watches the Dow Jones
Industrial Average — live price, session high/low, 52-week range, and an
intraday sparkline with the previous close as a dashed baseline.

Every pixel is drawn with Cairo rather than assembled from GTK widgets,
because Platinum lives in details no widget theme exposes: pinstripes,
two-tone bevels, group boxes that notch their own border for the label.
That is also why it has a working title bar and close box.

Data comes from Yahoo Finance's chart endpoint, which needs no API key but
is undocumented and can change without notice; the panel reports errors in
place rather than dying.

Install with `./install.sh --with-panels`, then launch **DJIA Watcher**
from your app launcher. Ctrl-W or the close box quits, Ctrl-R refreshes.

The drawing helpers (`bevel`, `group_box`, `title_bar`, radio, button) are
generic, so further panels are mostly new content against the same chrome.

## Uninstall

```bash
omarchy theme set tokyo-night     # or any other theme; the hook reverts the chrome
rm -rf ~/.config/omarchy/themes/platinum
rm -f  ~/.config/omarchy/hooks/theme-set.d/platinum-chrome
rm -rf ~/.local/share/fonts/chicago && fc-cache -f
```

The bar clone is left alone, since you may have other changes in it. To
drop it too: `omarchy plugin remove <user>.bar` and
`omarchy plugin enable omarchy.bar`.

## License

MIT — see [LICENSE](LICENSE). ChicagoFLF is not covered by it and is not
redistributed here: it is public domain, and `install.sh` fetches it from
its upstream.
