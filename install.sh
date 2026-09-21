#!/usr/bin/env bash
# Install the Platinum theme on an Omarchy system.
#
# Why this exists instead of `omarchy theme install <url>`:
#
#   A theme installed from a git repo has every *.lua stripped out of it.
#   omarchy-theme-set detects a cloned theme by its .git directory and
#   refuses to stage anything that runs code. Platinum's hyprland.lua --
#   rounding, borders, gaps, opacity, animations, the bevel gradient -- is
#   most of the theme, so a git install would silently drop half of it.
#
#   Copying the theme into place without a .git directory keeps all of it.
#   This script also handles the three things no theme file can carry: the
#   Chicago fonts, the theme-set hook, and the bar plugin clone.
#
# Everything here is idempotent; re-running it is safe.
#
#   ./install.sh                 theme, fonts, hook, bar patch
#   ./install.sh --with-panels   also the DJIA Watcher control panel
#   ./install.sh --no-fonts      skip the font download (offline installs)

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THEMES="$HOME/.config/omarchy/themes"
DEST="$THEMES/platinum"
FONTS="$HOME/.local/share/fonts/chicago"
PLUGINS="$HOME/.config/omarchy/plugins"

WITH_PANELS=0
WITH_FONTS=1
for arg in "$@"; do
  case "$arg" in
    --with-panels) WITH_PANELS=1 ;;
    --no-fonts)    WITH_FONTS=0 ;;
    -h|--help)     sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "install.sh: unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m==> %s\033[0m\n' "$*" >&2; }

command -v omarchy >/dev/null || { echo "install.sh: this is not an Omarchy system." >&2; exit 1; }

# ------------------------------------------------------------------ theme
say "Installing the theme into $DEST"
mkdir -p "$DEST"
cp -r "$SRC/theme/." "$DEST/"
# A .git directory here would make omarchy-theme-set treat this as a cloned
# theme and strip hyprland.lua. Guard against a previous git-based install.
if [[ -d $DEST/.git ]]; then
  warn "Removing $DEST/.git -- its presence causes Omarchy to strip hyprland.lua"
  rm -rf "$DEST/.git"
fi

# ------------------------------------------------------------------ fonts
# ChicagoFLF is public domain (the designer's statement ships with it) and
# is fetched from the same upstream the ttf-chicagoflf AUR package uses,
# checksummed against that PKGBUILD.
#
# Chicago Kare, the bitmap reproduction, is deliberately NOT used: it has no
# hinting tables, so it only renders cleanly at exact integer pixel sizes
# and goes mushy on any fractionally-scaled display.
FLF_URL="https://fontlibrary.org/assets/downloads/chicagoflf/a2e4a3d14e40fa7076a0a1bc06f3de43/chicagoflf.zip"
FLF_SHA="a5c1ff8aeb06505c77e6286fb63b6350494a9b030b688c212322d331d9d2278f"

if (( WITH_FONTS )); then
  mkdir -p "$FONTS"
  if [[ -f $FONTS/ChicagoFLF.ttf ]]; then
    say "ChicagoFLF already installed"
  else
    say "Fetching ChicagoFLF (public domain)"
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    if curl -fsSL -o "$tmp/flf.zip" "$FLF_URL"; then
      actual=$(sha256sum "$tmp/flf.zip" | cut -d' ' -f1)
      if [[ $actual == "$FLF_SHA" ]]; then
        unzip -o -j "$tmp/flf.zip" 'chicago/ChicagoFLF.ttf' -d "$FONTS" >/dev/null
        unzip -p "$tmp/flf.zip" 'chicago/README.ChicagoFLF' > "$FONTS/README.ChicagoFLF"
      else
        warn "ChicagoFLF checksum mismatch -- refusing to install."
        warn "  expected $FLF_SHA"
        warn "  actual   $actual"
      fi
    else
      warn "Could not download ChicagoFLF; GTK apps will fall back to the system font."
    fi
  fi

  fc-cache -f "$FONTS" >/dev/null 2>&1 || true
fi

# -------------------------------------------------------------- bar clone
# The clone is named after the current user, so its directory differs per
# machine; find it by the Bar.qml it contains.
say "Patching the bar plugin"
shopt -s nullglob
bar_qml=( "$PLUGINS"/*/Bar.qml )
shopt -u nullglob
if (( ${#bar_qml[@]} == 0 )); then
  omarchy plugin clone omarchy.bar >/dev/null 2>&1 || warn "omarchy plugin clone omarchy.bar failed"
  shopt -s nullglob; bar_qml=( "$PLUGINS"/*/Bar.qml ); shopt -u nullglob
fi
if (( ${#bar_qml[@]} == 1 )); then
  python3 "$SRC/scripts/patch-bar.py" "${bar_qml[0]}"
elif (( ${#bar_qml[@]} > 1 )); then
  warn "More than one cloned bar found; patching none. Clones: ${bar_qml[*]}"
else
  warn "No cloned bar to patch -- the menu-bar rule and Chicago bar font will be missing."
fi

# ------------------------------------------------------- menu font reset
# OMARCHY_MENU_FONT decides the font for the menu, launcher, polkit and
# clipboard surfaces. It is only ever set through hl.env, which calls
# setenv() inside Hyprland -- so once anything sets it, deleting the line
# and reloading leaves the old value live for the rest of the session, and
# every shell Hyprland spawns inherits it.
#
# It can be overwritten though, and Omarchy treats an empty value as unset:
#   return (override && override.length > 0) ? override : fontFamily
# so writing an empty value hands those surfaces back to `omarchy font set`.
# Without this, a stale value from any source sticks permanently.
LOOKNFEEL="$HOME/.config/hypr/looknfeel.lua"
if [[ -f $LOOKNFEEL ]] && ! grep -q 'OMARCHY_MENU_FONT' "$LOOKNFEEL"; then
  say "Neutralising OMARCHY_MENU_FONT in looknfeel.lua"
  cat >>"$LOOKNFEEL" <<'LUA'

-- Hand the menu/launcher/polkit/clipboard font back to `omarchy font set`.
-- hl.env cannot unset a variable (it calls setenv() inside Hyprland, which
-- persists for the session), but an empty value is treated as absent by
-- Omarchy, which is equivalent. Remove this line only if you deliberately
-- want those surfaces pinned to a font other than the system one.
hl.env("OMARCHY_MENU_FONT", "")
LUA
  hyprctl reload >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------- hook
say "Installing the theme-set hook"
omarchy hook install theme-set "$SRC/hooks/platinum-chrome" >/dev/null

# ----------------------------------------------------------------- panels
if (( WITH_PANELS )); then
  say "Installing the DJIA Watcher control panel"
  install -Dm755 "$SRC/panels/djia.py" "$HOME/.local/share/platinum-panels/djia.py"
  mkdir -p "$HOME/.local/share/applications"
  sed "s|^Exec=.*|Exec=$HOME/.local/share/platinum-panels/djia.py|" \
    "$SRC/panels/djia-watcher.desktop" > "$HOME/.local/share/applications/djia-watcher.desktop"
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

# ------------------------------------------------------------------ apply
say "Applying the theme"
omarchy theme set platinum >/dev/null 2>&1 || warn "Run: omarchy theme set platinum"

cat <<'DONE'

Platinum installed.

  omarchy theme set platinum     apply it
  omarchy theme set <other>      switch away; the hook reverts the chrome
  omarchy theme bg next          cycle the four desktop patterns

Known limits, which are Omarchy/Hyprland constraints rather than bugs:

  * No title bars. Hyprland has no server-side decorations, so windows get
    a beveled border and nothing else. (The included control panel draws
    its own, because it owns its window contents.)
  * Menus and popups follow the font selector, not Chicago. The only hook
    for that is OMARCHY_MENU_FONT, and hl.env is one-way for the life of a
    session, so it can never be scoped to a theme.
DONE
