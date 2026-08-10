"""Per-project visual design language token packs — the CSS half (wave 6, #14).

A project's existing VDL always wins; seeds only fill gaps; declarations are read from
config, never scraped at render time. A malformed block fails open to the default palette
with a stderr warning.

This module owns only the last step: turning a resolved pack into the token override the
page carries. WHERE a pack comes from — a project's declaration, a seed, or the
deterministic fallback — is `scripts/vdl_packs.py`, deliberately outside this package,
because the docs index resolves packs too and must reach the same answer without importing
a renderer.

The layer is emitted LAST, after every template's CSS. Placed earlier, a template that
redeclared `--accent` would silently take the page back; no template does today, and
`test_vdl_packs.py` keeps it that way.
"""
from __future__ import annotations

import re

# The tokens a pack may override. Deliberately short: the renderer's neutral surfaces are
# load-bearing for the type hierarchy waves 1-4 built, so a pack tints the page, it does
# not repaint it. A doc should read as ITS project's and as one of this set.
ACCENT_TOKEN = "--accent"
TINT_TOKEN = "--bg"
THEMES = ("light", "dark")


_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _decls(pack: dict, theme: str) -> str:
    out = [f"{ACCENT_TOKEN}:{pack['accent'][theme]}"]
    if pack.get("tint"):
        out.append(f"{TINT_TOKEN}:{pack['tint'][theme]}")
    return ";".join(out) + ";"


def _colour(pack: dict, key: str, theme: str) -> str | None:
    """A validated hex, or None.

    `render_artifact(vdl=...)` is a supported LIBRARY seam, so this sink cannot assume
    its input came from `vdl_packs.pack_for()`. The value is interpolated straight into
    a `<style>` block: an unvalidated string there is not a wrong colour, it is markup.
    """
    group = pack.get(key)
    if not isinstance(group, dict):
        return None
    value = group.get(theme)
    return value if isinstance(value, str) and _HEX.fullmatch(value) else None


def css_layer(pack: dict | None) -> str:
    """A `:root` override in every theme block the stylesheet already uses.

    Mirrors the base stylesheet exactly, which #73 changed: the bare `:root` carries the DARK
    accent because the ground is now dark unconditionally, both `[data-theme]` overrides are
    emitted, and `@media print` restores the light accent. The `prefers-color-scheme` query is
    gone from both — a pack that still emitted one would brand a dark page with the colour it
    chose for white paper whenever the viewer's OS was set to light.

    Emitting all of them matters twice over. A pack covering only some would leave a page
    half-branded under an explicit theme toggle, and the lint gate can only see the pack through
    the two `[data-theme]` blocks: `theme_tokens()` reads exactly those and takes the last value,
    so the pack's colours are the ones judged for contrast.
    """
    if not isinstance(pack, dict):
        return ""
    parts = {}
    for theme in THEMES:
        accent = _colour(pack, "accent", theme)
        if accent is None:
            return ""                      # fail open: no layer beats injected markup
        decls = [f"{ACCENT_TOKEN}:{accent}"]
        tint = _colour(pack, "tint", theme) if pack.get("tint") else None
        if tint:
            decls.append(f"{TINT_TOKEN}:{tint}")
        parts[theme] = ";".join(decls) + ";"
    light, dark = parts["light"], parts["dark"]
    return (f"\n:root{{{dark}}}"
            f"\n:root[data-theme=dark]{{{dark}}}"
            f"\n:root[data-theme=light]{{{light}}}"
            f"\n@media print{{:root,:root[data-theme=dark]{{{light}}}}}\n")
