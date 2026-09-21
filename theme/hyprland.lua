-- Platinum: Hyprland settings that belong to this theme and no other.
--
-- Loaded by `require_optional.module("omarchy.current.theme.hyprland")` in
-- default/hypr/omarchy.lua, as "Current theme overrides". Because
-- `hyprctl reload` re-parses the whole config from scratch, anything set
-- here simply stops applying the moment another theme is staged -- no undo
-- logic needed, and no hook involvement. That is why this lives in the
-- theme rather than in ~/.config/hypr/looknfeel.lua, where it used to sit
-- and where it leaked into every other theme.
--
-- NOTE: shipping this file suppresses the generated one that theme-set
-- would otherwise build from colors.toml (the renderer never overwrites a
-- file the theme provides). The border gradient is therefore defined here
-- rather than derived from hyprland_active_border in colors.toml.

-- The Platinum bevel: lit from the top-left, white falling to dark grey.
-- An inactive window loses the bevel and sits flat, the way a background
-- window did in Mac OS 8.
local active_border_color = { colors = { "rgba(ffffffff)", "rgba(6e6e6eff)" }, angle = 135 }
local inactive_border_color = { colors = { "rgba(b4b4b4ff)", "rgba(b4b4b4ff)" } }

hl.config({
  general = {
    col = {
      active_border = active_border_color,
      inactive_border = inactive_border_color,
    },

    -- Wide enough for the gradient to read as a bevel rather than a line.
    -- Below 3px the white-to-grey fall just looks like aliasing.
    border_size = 3,

    -- Finder windows sat nearly flush.
    gaps_in = 2,
    gaps_out = 4,
  },

  group = {
    col = {
      border_active = active_border_color,
      border_inactive = inactive_border_color,
    },
  },
})

hl.config({
  decoration = {
    -- Square. The single biggest visual lever in the whole theme.
    rounding = 0,

    -- Platinum was fully opaque; there was no translucency in the OS.
    active_opacity = 1.0,
    inactive_opacity = 1.0,
    fullscreen_opacity = 1.0,

    -- A background window kept full contrast and signalled its state by
    -- losing the title bar pinstripes instead.
    dim_inactive = false,

    blur = { enabled = false },

    -- The drop shadow is a Mac OS X invention.
    shadow = { enabled = false },
  },
})

hl.config({
  animations = {
    -- Instant. Every modern easing curve reads as post-2000.
    enabled = false,
  },
})

-- decoration.active_opacity above is not sufficient on its own: Omarchy
-- tags every window `default-opacity` and then applies
-- `opacity = "0.985 0.96"` as a window rule, and a window rule beats the
-- decoration default. Re-stating it here wins because theme overrides load
-- after default/hypr/windows.lua.
o.window(".*", { opacity = "1.0 1.0" })

-- The Platinum control panels are desk accessories: they float at their
-- drawn size rather than joining the tiling layout, the way a Mac control
-- panel was always a fixed-size window you placed yourself.
o.window({ class = "^org%.platinum%." }, { float = true })
