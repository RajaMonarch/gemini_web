"""
compositor.py — Professional-grade social media post compositor.

Design philosophy:
  - The canvas is treated as a structured document, not a photo with text printed on it.
  - Every element has an explicit zone, calculated bottom-up to prevent overlaps.
  - Text placement is deterministic and layout-aware.
  - Visual hierarchy is enforced: headline > subheadline > services > CTA > contact.
  - Emoji are stripped and replaced with clean text — Pillow TTF fonts have no emoji glyphs.
  - All coordinates are calculated in the compositor, not trusted from the LLM spec.
"""

from __future__ import annotations

import io
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from models.design_spec import DesignSpec


# ── Font management ──────────────────────────────────────────────────────────

FONT_DIR = Path("assets/fonts")

_VALID_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"ttcf")

# Inter v4.1 official release ZIP — contains static TTF files
_INTER_ZIP_URL = "https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip"

# ZIP paths for the static weight TTF files inside Inter-4.1.zip
_ZIP_FONT_MAP = {
    "Inter-Regular.ttf": "Inter-4.1/extras/ttf/Inter-Regular.ttf",
    "Inter-Bold.ttf":    "Inter-4.1/extras/ttf/Inter-Bold.ttf",
}


def ensure_fonts() -> None:
    """
    Download Inter v4.1 static TTF fonts from the official GitHub release ZIP.
    Extracts only the two files needed (Regular + Bold) without saving the full ZIP.
    Falls back to Pillow's built-in bitmap font if download fails.
    """
    import zipfile

    FONT_DIR.mkdir(parents=True, exist_ok=True)

    needed = [f for f in _ZIP_FONT_MAP if not (FONT_DIR / f).exists()]
    if not needed:
        return   # all fonts already on disk

    print(f"[compositor] Downloading Inter v4.1 fonts from GitHub release...")
    try:
        req = urllib.request.Request(
            _INTER_ZIP_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; OctopusAI/1.0)",
                "Accept":     "application/octet-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            zip_data = resp.read()

        print(f"[compositor] Downloaded {len(zip_data)//1024} KB ZIP. Extracting fonts...")

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for filename, zip_path in _ZIP_FONT_MAP.items():
                dest = FONT_DIR / filename
                if dest.exists():
                    continue
                try:
                    data = zf.read(zip_path)
                    if len(data) > 4 and data[:4] in _VALID_MAGIC:
                        dest.write_bytes(data)
                        print(f"[compositor] Extracted {filename} ({len(data)//1024} KB)")
                    else:
                        print(f"[compositor] Warning: {zip_path} is not a valid TTF.")
                except KeyError:
                    # Try alternative path patterns in case ZIP structure differs
                    names = zf.namelist()
                    match = next((n for n in names if n.endswith(filename)), None)
                    if match:
                        data = zf.read(match)
                        if len(data) > 4 and data[:4] in _VALID_MAGIC:
                            dest.write_bytes(data)
                            print(f"[compositor] Extracted {filename} from {match} ({len(data)//1024} KB)")
                    else:
                        print(f"[compositor] Warning: {filename} not found in ZIP.")

    except Exception as exc:
        print(f"[compositor] Could not download Inter fonts: {exc}")
        print("[compositor] Falling back to Pillow default font — text quality will be reduced.")
        print("[compositor] To fix permanently: download Inter-Regular.ttf and Inter-Bold.ttf")
        print("[compositor] from https://github.com/rsms/inter/releases and place in assets/fonts/")


ensure_fonts()


def load_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    name = "Inter-Bold.ttf" if weight == "bold" else "Inter-Regular.ttf"
    path = FONT_DIR / name
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    return ImageFont.load_default(size=size)


# ── Colour helpers ───────────────────────────────────────────────────────────

def hex_to_rgba(h: str) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    if len(h) == 8:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r, g, b, 255


def with_alpha(color: tuple, alpha: int) -> tuple:
    return (*color[:3], alpha)


# ── Text helpers ─────────────────────────────────────────────────────────────

_EMOJI_REPLACEMENTS = {
    "📞": "Ph:", "☎": "Ph:", "📱": "Ph:",
    "✉": "Email:", "📧": "Email:", "📨": "Email:",
    "🌐": "Web:", "🔗": "Web:",
    "→": "|", "➜": "|", "➤": "|", "►": "|",
    "✦": "|", "•": "-", "·": "-", "★": "*", "☆": "*",
    "✓": "v", "✔": "v", "✅": "v",
    "🚀": "", "💡": "", "🎯": "", "💎": "", "🔥": "",
}
_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]", flags=re.UNICODE)


def clean_text(text: str) -> str:
    """Strip emoji and replace with text equivalents. Pillow TTF has no emoji glyphs."""
    for emoji, replacement in _EMOJI_REPLACEMENTS.items():
        text = text.replace(emoji, replacement)
    text = _EMOJI_RE.sub("", text)
    # Collapse multiple spaces / pipes
    text = re.sub(r"\s{2,}", "  ", text)
    return text.strip()


def measure_text_height(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> int:
    """Calculate pixel height of word-wrapped text block."""
    lines = _wrap_text(draw, clean_text(text), font, max_w)
    if not lines:
        return 0
    _, _, _, line_h = font.getbbox("Ag")
    spacing = _line_spacing(font)
    return len(lines) * line_h + (len(lines) - 1) * spacing


def _line_spacing(font) -> int:
    _, _, _, line_h = font.getbbox("Ag")
    # Tighter spacing for large display fonts, normal for body
    return int(line_h * 0.12) if line_h > 60 else int(line_h * 0.20)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words  = text.split()
    lines, line = [], []
    for word in words:
        test = " ".join(line + [word])
        if draw.textlength(test, font=font) <= max_w:
            line.append(word)
        else:
            if line:
                lines.append(" ".join(line))
            line = [word]
    if line:
        lines.append(" ".join(line))
    return lines


def draw_text_block(
    draw:    ImageDraw.ImageDraw,
    text:    str,
    font:    ImageFont.FreeTypeFont,
    color:   tuple,
    x:       int,
    y:       int,
    max_w:   int,
    align:   str = "left",
) -> int:
    """
    Draw word-wrapped text starting at (x, y).
    Returns the Y coordinate immediately after the last line (for stacking).
    """
    text  = clean_text(text)
    lines = _wrap_text(draw, text, font, max_w)
    _, _, _, line_h = font.getbbox("Ag")
    spacing  = _line_spacing(font)
    cursor_y = y

    for ln in lines:
        tw = draw.textlength(ln, font=font)
        if align == "center":
            tx = x + (max_w - tw) // 2
        elif align == "right":
            tx = x + max_w - tw
        else:
            tx = x
        draw.text((tx, cursor_y), ln, font=font, fill=color)
        cursor_y += line_h + spacing

    return cursor_y


# ── Zone calculator ──────────────────────────────────────────────────────────

@dataclass
class Zones:
    # All coordinates are absolute canvas pixels
    subject_rect:  tuple[int,int,int,int]  # (x, y, w, h) where background subjects live
    text_x:        int                      # left edge of text column
    text_w:        int                      # width of text column
    text_top:      int                      # topmost Y available for text
    text_bottom:   int                      # bottommost Y before CTA zone
    cta_y:         int                      # top of CTA button
    cta_x:         int                      # left of CTA button (centered by default)
    cta_w:         int                      # fixed CTA width
    cta_h:         int                      # fixed CTA height
    contact_y:     int                      # top of contact bar
    logo_x:        int
    logo_y:        int
    logo_max_w:    int
    logo_max_h:    int
    overlay_rects: list[tuple]              # list of (x,y,w,h,alpha) dark rectangles


def _calculate_zones(spec: DesignSpec) -> Zones:
    W, H   = spec.canvas_w, spec.canvas_h
    MARGIN = 72   # horizontal margin from canvas edge

    # Fixed bottom elements — calculated bottom-up, no overlaps possible
    CTA_H       = 72    # CTA button height
    CTA_W       = 420   # CTA button width (never trusted from LLM)
    CTA_GAP     = 32    # gap between content bottom and CTA top
    FOOTER_GAP  = 20    # gap between CTA bottom and footer top

    contact_y = H - FOOTER_H          # footer pinned to canvas bottom
    cta_y     = contact_y - FOOTER_GAP - CTA_H
    cta_x     = (W - CTA_W) // 2      # always centered

    if spec.layout_mode == "bottom-text":
        # Subjects: top 55%, Text: bottom 45%
        split_y      = int(H * 0.52)
        text_x       = MARGIN
        text_w       = W - MARGIN * 2
        text_top     = split_y + 32
        text_bottom  = cta_y - CTA_GAP
        subject_rect = (0, 0, W, split_y)
        overlay_rects = [
            (0, split_y - 80, W, 80, 80),
            (0, split_y, W, H - split_y, 180),
        ]

    elif spec.layout_mode == "left-text":
        # Subjects: right 50%, Text: left 50%
        split_x      = int(W * 0.50)
        text_x       = MARGIN
        text_w       = split_x - MARGIN - 20
        text_top     = 140
        text_bottom  = cta_y - CTA_GAP
        cta_x        = MARGIN
        cta_w_local  = min(CTA_W, text_w)
        subject_rect = (split_x, 0, W - split_x, H)
        overlay_rects = [
            (0, 0, split_x + 60, H, 160),
            (split_x, 0, W - split_x, H, 40),
        ]
        return Zones(
            subject_rect  = subject_rect,
            text_x        = text_x,
            text_w        = text_w,
            text_top      = text_top,
            text_bottom   = text_bottom,
            cta_y         = cta_y,
            cta_x         = cta_x,
            cta_w         = cta_w_local,
            cta_h         = CTA_H,
            contact_y     = contact_y,
            logo_x        = MARGIN,
            logo_y        = 36,
            logo_max_w    = 180,
            logo_max_h    = 60,
            overlay_rects = overlay_rects,
        )

    else:  # split
        # Subjects: top-right quadrant, Text: top-left + full bottom
        split_x      = int(W * 0.50)
        split_y      = int(H * 0.48)
        text_x       = MARGIN
        text_w       = split_x - MARGIN - 16
        text_top     = 140
        text_bottom  = cta_y - CTA_GAP
        subject_rect = (split_x, 0, W - split_x, split_y)
        overlay_rects = [
            (0, 0, split_x, H, 155),
            (0, split_y, W, H - split_y, 170),
            (split_x, 0, W - split_x, split_y, 30),
        ]

    return Zones(
        subject_rect  = subject_rect,
        text_x        = text_x,
        text_w        = text_w,
        text_top      = text_top,
        text_bottom   = text_bottom,
        cta_y         = cta_y,
        cta_x         = cta_x,
        cta_w         = CTA_W,
        cta_h         = CTA_H,
        contact_y     = contact_y,
        logo_x        = MARGIN,
        logo_y        = 36,
        logo_max_w    = 180,
        logo_max_h    = 60,
        overlay_rects = overlay_rects,
    )


# ── Gradient overlay ─────────────────────────────────────────────────────────

def _apply_gradient_overlay(canvas: Image.Image, spec: DesignSpec, zones: Zones) -> Image.Image:
    """
    Apply smooth gradient overlays based on layout zones.
    Uses scanline-by-scanline alpha blending for natural vignettes.
    Much better than a hard rectangular overlay.
    """
    W, H = canvas.size

    if spec.layout_mode == "bottom-text":
        # Vertical gradient: transparent at top, opaque at bottom
        split_y    = zones.subject_rect[3]
        feather_h  = 120   # pixel height of the soft transition
        solid_alpha = 185

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw    = ImageDraw.Draw(overlay)

        # Feather zone: alpha ramps from 0 to solid_alpha
        for dy in range(feather_h):
            t = dy / feather_h
            alpha = int(solid_alpha * (t ** 1.4))   # ease-in curve
            draw.line([(0, split_y - feather_h // 3 + dy), (W, split_y - feather_h // 3 + dy)],
                      fill=(0, 0, 0, alpha))

        # Solid zone below feather
        draw.rectangle([0, split_y + feather_h // 2, W, H], fill=(0, 0, 0, solid_alpha))
        canvas = Image.alpha_composite(canvas, overlay)

    elif spec.layout_mode == "left-text":
        # Horizontal gradient: opaque on left, transparent on right
        split_x    = zones.subject_rect[0]
        feather_w  = 100
        solid_alpha = 170

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw    = ImageDraw.Draw(overlay)
        draw.rectangle([0, 0, split_x - feather_w, H], fill=(0, 0, 0, solid_alpha))

        for dx in range(feather_w):
            t     = dx / feather_w
            alpha = int(solid_alpha * (1 - t ** 0.7))
            draw.line([(split_x - feather_w + dx, 0), (split_x - feather_w + dx, H)],
                      fill=(0, 0, 0, alpha))

        # Subtle tint over subject side for brand color blend
        draw.rectangle([split_x, 0, W, H], fill=(0, 0, 0, 30))
        canvas = Image.alpha_composite(canvas, overlay)

    else:  # split
        overlay    = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw       = ImageDraw.Draw(overlay)
        split_x    = zones.subject_rect[0]
        split_y    = zones.subject_rect[3]
        solid_alpha = 165

        # Left column fully dark
        draw.rectangle([0, 0, split_x, H], fill=(0, 0, 0, solid_alpha))
        # Bottom band fully dark
        draw.rectangle([0, split_y, W, H], fill=(0, 0, 0, solid_alpha))
        # Feather between subject and bottom band
        feather_h = 80
        for dy in range(feather_h):
            t     = dy / feather_h
            alpha = int(solid_alpha * t)
            draw.line([(split_x, split_y - feather_h + dy), (W, split_y - feather_h + dy)],
                      fill=(0, 0, 0, alpha))

        canvas = Image.alpha_composite(canvas, overlay)

    return canvas


# ── Brand accent elements ────────────────────────────────────────────────────

def _draw_brand_accents(draw: ImageDraw.ImageDraw, spec: DesignSpec, zones: Zones) -> None:
    """
    Draw thin brand-colored accent lines and decorative elements.
    These are what separate professional posts from generic ones.
    """
    primary = hex_to_rgba(spec.brand_color_primary)
    W       = spec.canvas_w

    if spec.layout_mode == "bottom-text":
        # Horizontal accent line at the split point — a designer's signature move
        accent_y = zones.text_top - 16
        draw.rectangle([zones.text_x, accent_y, zones.text_x + 60, accent_y + 4],
                       fill=primary)

    elif spec.layout_mode == "left-text":
        # Vertical accent bar on the far left edge
        draw.rectangle([0, 0, 6, spec.canvas_h], fill=primary)
        # Short horizontal accent below headline placeholder
        draw.rectangle([zones.text_x, zones.text_top - 8, zones.text_x + 48, zones.text_top - 4],
                       fill=primary)

    else:  # split
        # Vertical accent on left edge + horizontal divider between text zones
        draw.rectangle([0, 0, 6, spec.canvas_h], fill=primary)
        split_x = zones.subject_rect[0]
        # Subtle vertical separator between text column and subject zone
        draw.rectangle([split_x - 2, 0, split_x, zones.subject_rect[3]],
                       fill=with_alpha(primary, 80))


# ── Logo / brand name ────────────────────────────────────────────────────────

# Logo constraints per layout mode
_LOGO_SPECS = {
    #              max_w  max_h  pad_x  pad_y
    "bottom-text": (200,   70,    60,    36),
    "left-text":   (180,   60,    72,    36),
    "split":       (180,   60,    72,    36),
}


def _draw_logo(
    canvas:     Image.Image,
    draw:       ImageDraw.ImageDraw,
    spec:       DesignSpec,
    zones:      Zones,
    logo_bytes: bytes | None,
) -> None:
    """
    Renders the brand logo or falls back to brand name text.

    Logo processing:
    1. Open and convert to RGBA to preserve transparency.
    2. High-quality Lanczos resize within max_w × max_h bounds.
    3. If the logo has no meaningful transparency (e.g. white background PNG),
       detect it and apply a subtle dark pill behind the logo for legibility.
    4. Composite onto canvas using the alpha channel as mask.
    5. Position: top-left corner of the text column, with layout-specific padding.

    Text fallback:
    - Brand name in brand_color_primary, bold, 32px.
    - Same position as logo would have been.
    """
    mode  = spec.layout_mode
    max_w, max_h, pad_x, pad_y = _LOGO_SPECS.get(mode, _LOGO_SPECS["left-text"])

    logo_x = pad_x
    logo_y = pad_y

    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")

            # High-quality resize preserving aspect ratio
            logo.thumbnail((max_w, max_h), Image.LANCZOS)

            # Detect if logo has a solid (non-transparent) background
            # by checking the average alpha of corner pixels
            w, h   = logo.size
            pixels = logo.load()
            corners = [
                pixels[0, 0][3], pixels[w-1, 0][3],
                pixels[0, h-1][3], pixels[w-1, h-1][3],
            ]
            avg_corner_alpha = sum(corners) / 4

            if avg_corner_alpha > 200:
                # Logo has solid background — wrap it in a subtle dark pill
                # so it's legible over any background image
                PILL_PAD = 12
                pill_w   = logo.width  + PILL_PAD * 2
                pill_h   = logo.height + PILL_PAD * 2
                pill     = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
                pill_d   = ImageDraw.Draw(pill)
                pill_d.rounded_rectangle(
                    [0, 0, pill_w, pill_h],
                    radius=8,
                    fill=(0, 0, 0, 160),
                )
                pill.paste(logo, (PILL_PAD, PILL_PAD), mask=logo)
                canvas.paste(pill, (logo_x, logo_y), mask=pill)
            else:
                # Logo has transparent background — paste directly
                canvas.paste(logo, (logo_x, logo_y), mask=logo)

            return
        except Exception as exc:
            print(f"[compositor] Logo render failed: {exc}")
            # Fall through to text fallback

    # Text fallback — brand name in brand primary colour
    if spec.brand_name:
        name  = clean_text(spec.brand_name)
        font  = load_font("bold", 30)
        color = hex_to_rgba(spec.brand_color_primary)
        draw.text((logo_x, logo_y), name, font=font, fill=color)


# ── Services grid ────────────────────────────────────────────────────────────

def _draw_services_grid(
    draw:  ImageDraw.ImageDraw,
    spec:  DesignSpec,
    zones: Zones,
    start_y: int,
) -> int:
    """
    Renders services as a clean 2-column or 4-column grid with bullet accents.
    Returns the Y coordinate after the grid.
    """
    if not spec.services:
        return start_y

    services  = spec.services[:8]
    primary   = hex_to_rgba(spec.brand_color_primary)
    text_col  = (255, 255, 255, 220)
    font      = load_font("regular", 24)
    _, _, _, line_h = font.getbbox("Ag")

    # Choose columns based on available width and number of services
    if len(services) <= 4 or zones.text_w < 500:
        cols    = 2
        col_w   = zones.text_w // cols
        row_h   = line_h + 20
    else:
        cols    = 4
        col_w   = zones.text_w // cols
        row_h   = line_h + 18

    bullet_r = 5
    rows     = (len(services) + cols - 1) // cols

    for i, service in enumerate(services):
        col = i % cols
        row = i // cols
        x   = zones.text_x + col * col_w
        y   = start_y + row * row_h

        # Bullet dot in brand primary color
        draw.ellipse([x, y + line_h // 2 - bullet_r,
                      x + bullet_r * 2, y + line_h // 2 + bullet_r],
                     fill=primary)

        # Service label
        label = clean_text(service)
        draw.text((x + bullet_r * 2 + 10, y), label, font=font, fill=text_col)

    return start_y + rows * row_h + 16


# ── CTA button ───────────────────────────────────────────────────────────────

# CTA design constants — edit here to change the look globally
_CTA_FONT_SIZE  = 30     # base font size; auto-reduces if text overflows
_CTA_FONT_MIN   = 20     # smallest acceptable font size
_CTA_BTN_H      = 68     # fixed button height in pixels
_CTA_H_PAD      = 52     # horizontal padding each side of label text
_CTA_MIN_W      = 260    # minimum button width
_CTA_BORDER_W   = 3      # border stroke width (0 = no border)
_CTA_RADIUS_DIV = 2      # radius = btn_h // this  (2 = full pill, 4 = rounded rect)


def _draw_cta(draw: ImageDraw.ImageDraw, spec: DesignSpec, zones: Zones) -> None:
    """
    Draws a clean, professional CTA button.

    Design decisions (all intentional):
    - NO inner highlight stripe — it caused a two-tone artifact in previous version.
    - Solid flat fill only. The button colour alone provides enough contrast.
    - A thin contrasting border ring is drawn OUTSIDE the fill for definition
      without affecting the interior colour — this is the correct technique.
    - Font is measured first; button wraps it. No fixed width from LLM.
    - Auto-reduces font size if label is long, down to _CTA_FONT_MIN.
    - Alignment:  bottom-text → centred on full canvas width.
                  left-text / split → left-aligned to text column.
    """
    text      = clean_text(spec.cta_text)
    font_size = _CTA_FONT_SIZE
    font      = load_font("bold", font_size)

    # Shrink font until text fits within text column with padding
    max_text_w = zones.text_w - _CTA_H_PAD * 2
    while font_size > _CTA_FONT_MIN:
        if draw.textlength(text, font=font) <= max_text_w:
            break
        font_size -= 1
        font = load_font("bold", font_size)

    # Button dimensions — driven by measured text, not hardcoded width
    text_w = int(draw.textlength(text, font=font))
    btn_w  = max(_CTA_MIN_W, text_w + _CTA_H_PAD * 2)
    btn_w  = min(btn_w, zones.text_w)   # cap at column width
    btn_h  = _CTA_BTN_H
    r      = btn_h // _CTA_RADIUS_DIV

    # Horizontal position
    if spec.layout_mode == "bottom-text":
        btn_x = (spec.canvas_w - btn_w) // 2   # centred on full canvas
    else:
        btn_x = zones.text_x                    # left-aligned to text column

    btn_y  = zones.cta_y
    fill   = hex_to_rgba(spec.cta_bg)
    label  = hex_to_rgba(spec.cta_color)

    # ── 1. Solid fill — no highlight stripe, no gradient ─────────────────────
    draw.rounded_rectangle(
        [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
        radius=r,
        fill=fill,
    )

    # ── 2. Thin border ring for definition ───────────────────────────────────
    # Drawn as outline only — does not affect interior colour.
    # Border colour = label colour at 40% opacity for a matched look.
    if _CTA_BORDER_W > 0:
        border_color = (*label[:3], 100)   # label colour, 40% alpha
        draw.rounded_rectangle(
            [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
            radius=r,
            outline=border_color,
            width=_CTA_BORDER_W,
        )

    # ── 3. Label — centred, vertically and horizontally ──────────────────────
    cx = btn_x + btn_w // 2
    cy = btn_y + btn_h // 2
    draw.text((cx, cy), text, font=font, fill=label, anchor="mm")


# ── Contact bar ───────────────────────────────────────────────────────────────

# Fixed footer height — zone calculator uses this constant too
FOOTER_H = 80   # total height of the footer bar

# Gap between icon and its text label
_ICON_TEXT_GAP = 8
# Gap between segments ( icon+text | icon+text )
_SEG_GAP = 40
# Vertical separator between segments
_SEP_W = 1


def _draw_phone_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int, color: tuple) -> None:
    """
    Draw a minimal phone handset icon centred at (cx, cy).
    s = icon size in pixels (bounding box will be s×s).
    Uses only ellipses and rectangles — no paths needed.
    """
    h  = s
    w  = int(s * 0.72)
    x0 = cx - w // 2
    y0 = cy - h // 2

    lw = max(2, s // 7)   # line weight scales with icon size

    # Earpiece arc (top-left curve of handset)
    ear_r = int(w * 0.45)
    draw.arc(
        [x0, y0, x0 + ear_r * 2, y0 + ear_r * 2],
        start=200, end=340, fill=color, width=lw,
    )
    # Mouthpiece arc (bottom-right curve)
    draw.arc(
        [x0 + w - ear_r * 2, y0 + h - ear_r * 2, x0 + w, y0 + h],
        start=20, end=160, fill=color, width=lw,
    )
    # Body bar connecting the two arcs (diagonal approximation via line)
    draw.line(
        [x0 + int(ear_r * 0.3), y0 + int(ear_r * 1.6),
         x0 + w - int(ear_r * 0.3), y0 + h - int(ear_r * 1.6)],
        fill=color, width=lw,
    )


def _draw_email_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int, color: tuple) -> None:
    """
    Draw a minimal envelope icon centred at (cx, cy).
    Envelope outline + V-fold line at the top.
    """
    w  = s
    h  = int(s * 0.72)
    x0 = cx - w // 2
    y0 = cy - h // 2
    x1 = x0 + w
    y1 = y0 + h
    lw = max(1, s // 9)

    # Envelope rectangle
    draw.rectangle([x0, y0, x1, y1], outline=color, width=lw)

    # V-fold: two lines from top corners meeting at centre
    mid_x = cx
    fold_y = y0 + int(h * 0.45)
    draw.line([x0, y0, mid_x, fold_y], fill=color, width=lw)
    draw.line([x1, y0, mid_x, fold_y], fill=color, width=lw)


def _draw_globe_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int, color: tuple) -> None:
    """
    Draw a minimal globe icon centred at (cx, cy).
    Outer circle + vertical centre line + two horizontal latitude lines.
    """
    r  = s // 2
    x0 = cx - r
    y0 = cy - r
    x1 = cx + r
    y1 = cy + r
    lw = max(1, s // 9)

    # Outer circle
    draw.ellipse([x0, y0, x1, y1], outline=color, width=lw)
    # Vertical meridian line
    draw.line([cx, y0, cx, y1], fill=color, width=lw)
    # Two horizontal latitude lines at 33% and 66% of diameter
    lat1_y = y0 + s // 3
    lat2_y = y0 + (s * 2) // 3
    # Latitude lines are shorter than full width (elliptical feel)
    lat_half = int(r * 0.82)
    draw.line([cx - lat_half, lat1_y, cx + lat_half, lat1_y], fill=color, width=lw)
    draw.line([cx - lat_half, lat2_y, cx + lat_half, lat2_y], fill=color, width=lw)


# Maps segment index to its icon drawing function
_ICON_DRAW_FNS = [_draw_phone_icon, _draw_email_icon, _draw_globe_icon]


def _measure_segment(draw: ImageDraw.ImageDraw, text: str, font, icon_size: int) -> int:
    """Total pixel width of one segment: icon + gap + text."""
    return icon_size + _ICON_TEXT_GAP + int(draw.textlength(text, font=font))


def _draw_contact_bar(
    canvas: Image.Image,
    draw:   ImageDraw.ImageDraw,
    spec:   DesignSpec,
    zones:  Zones,
) -> None:
    """
    Renders contact details as a professional icon + text row, centred in the footer.

    Layout (single horizontal line):

        [📞 icon] Ph: 7105678569   |   [✉ icon] Email: info@brand.com   |   [🌐 icon] brand.co

    Rules:
    - Icons are drawn natively using Pillow primitives (no emoji, no font glyphs).
    - All segments share one font size and one vertical baseline.
    - The icon is vertically centred on the same baseline as the text.
    - Segments separated by a thin vertical rule in brand primary colour.
    - Auto-reduces font + icon size until the full row fits in the canvas width.
    - contact_line may contain phone AND email separated by " | " — it is split
      into individual segments here so each gets its own icon.
    """
    has_contact = bool(spec.contact_line)
    has_website = bool(spec.website_line)
    if not has_contact and not has_website:
        return

    W       = spec.canvas_w
    H       = spec.canvas_h
    bar_top = zones.contact_y
    MARGIN  = 60
    MAX_W   = W - MARGIN * 2

    # ── Parse segments ────────────────────────────────────────────────────────
    # contact_line may be "Ph: 123 | Email: foo@bar.com" — split on " | "
    # website_line is always a single segment
    raw_segments: list[str] = []
    if has_contact:
        # Split on common separators the LLM might use
        parts = re.split(r"\s*\|\s*", clean_text(spec.contact_line))
        raw_segments.extend(p.strip() for p in parts if p.strip())
    if has_website:
        raw_segments.append(clean_text(spec.website_line))

    # Cap to 3 segments (phone / email / website)
    segments = raw_segments[:3]
    if not segments:
        return

    # ── Auto-fit font and icon size ────────────────────────────────────────────
    font_size = 20
    font_min  = 13
    font      = load_font("regular", font_size)

    def total_row_width(fs: int, icon_s: int) -> int:
        f = load_font("regular", fs)
        seg_widths = [_measure_segment(draw, s, f, icon_s) for s in segments]
        return sum(seg_widths) + _SEG_GAP * (len(segments) - 1)

    while font_size > font_min:
        icon_size = font_size + 2   # icon slightly larger than text cap-height
        if total_row_width(font_size, icon_size) <= MAX_W:
            break
        font_size -= 1
        font = load_font("regular", font_size)

    icon_size = font_size + 2

    # Final measurements
    seg_widths  = [_measure_segment(draw, s, font, icon_size) for s in segments]
    total_w     = sum(seg_widths) + _SEG_GAP * (len(segments) - 1)

    # ── Background strip ──────────────────────────────────────────────────────
    bar_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd        = ImageDraw.Draw(bar_layer)
    bg_fill   = hex_to_rgba(spec.contact_bg) if spec.contact_bg else (0, 0, 0, 180)
    bd.rectangle([0, bar_top, W, H], fill=bg_fill)
    canvas.alpha_composite(bar_layer)
    draw = ImageDraw.Draw(canvas)   # rebind after composite

    # ── Separator line (brand primary, full usable width) ─────────────────────
    primary = hex_to_rgba(spec.brand_color_primary)
    draw.rectangle(
        [MARGIN, bar_top, W - MARGIN, bar_top + 2],
        fill=with_alpha(primary, 160),
    )

    # ── Vertical centre of the footer bar ────────────────────────────────────
    _, _, _, cap_h = font.getbbox("Ag")
    row_h    = max(icon_size, cap_h)
    row_y    = bar_top + (FOOTER_H - row_h) // 2   # top of the row block

    icon_col = (255, 255, 255, 200)   # icon colour (slightly muted vs text)
    text_col = (255, 255, 255, 230)   # text colour

    # ── Draw each segment left-to-right ──────────────────────────────────────
    cursor_x = (W - total_w) // 2    # start X so the whole row is centred

    for idx, seg in enumerate(segments):
        # Icon — centred vertically on the text cap line
        icon_cx = cursor_x + icon_size // 2
        icon_cy = row_y + row_h // 2

        icon_fn = _ICON_DRAW_FNS[idx] if idx < len(_ICON_DRAW_FNS) else None
        if icon_fn:
            icon_fn(draw, icon_cx, icon_cy, icon_size, icon_col)

        # Text — baseline-aligned with icon centre
        text_x = cursor_x + icon_size + _ICON_TEXT_GAP
        text_y = row_y + (row_h - cap_h) // 2   # vertically centre cap-height
        draw.text((text_x, text_y), seg, font=font, fill=text_col)

        cursor_x += seg_widths[idx]

        # Vertical separator between segments (not after the last one)
        if idx < len(segments) - 1:
            sep_x = cursor_x + _SEG_GAP // 2
            sep_y0 = row_y + 2
            sep_y1 = row_y + row_h - 2
            draw.rectangle(
                [sep_x, sep_y0, sep_x + _SEP_W, sep_y1],
                fill=with_alpha(primary, 100),
            )
            cursor_x += _SEG_GAP


# ── Headline accent underline ────────────────────────────────────────────────

def _draw_headline_accent(
    draw:     ImageDraw.ImageDraw,
    spec:     DesignSpec,
    headline_bottom_y: int,
    zones:    Zones,
) -> None:
    """Thin accent line under the headline — a professional design detail."""
    primary = hex_to_rgba(spec.brand_color_primary)
    line_w  = min(120, zones.text_w // 3)
    line_y  = headline_bottom_y + 10
    if zones.text_w > 400:
        line_x = zones.text_x + (zones.text_w - line_w) // 2
    else:
        line_x = zones.text_x
    draw.rectangle([line_x, line_y, line_x + line_w, line_y + 4], fill=primary)


# ── Main compositor entry point ──────────────────────────────────────────────

def composite(bg_bytes: bytes, spec: DesignSpec, logo_bytes: bytes | None = None) -> bytes:
    """
    Full professional compositor pipeline:
      1. Background resize
      2. Gradient overlay (layout-aware, smooth feathering)
      3. Brand accent elements
      4. Logo / brand name
      5. Headline (font-size enforced by spec, position by zone calculator)
      6. Headline accent underline
      7. Subheadline
      8. Body text (if no services) OR services grid
      9. CTA button (fixed width, always centered, never overlaps contact)
     10. Contact bar (bottom-anchored, separated from CTA)
     11. Export PNG
    """

    # ── 1. Background ────────────────────────────────────────────────────────
    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
    bg = bg.resize((spec.canvas_w, spec.canvas_h), Image.LANCZOS)

    # Subtle blur on background to push it behind the text layer
    bg = bg.filter(ImageFilter.GaussianBlur(radius=1.2))

    canvas = Image.new("RGBA", (spec.canvas_w, spec.canvas_h))
    canvas.paste(bg, (0, 0))

    # ── 2. Calculate zones ───────────────────────────────────────────────────
    zones = _calculate_zones(spec)

    # ── 3. Gradient overlay (smooth, layout-aware) ───────────────────────────
    canvas = _apply_gradient_overlay(canvas, spec, zones)

    draw = ImageDraw.Draw(canvas)

    # ── 4. Brand accent elements ─────────────────────────────────────────────
    _draw_brand_accents(draw, spec, zones)

    # ── 5. Logo / brand name ─────────────────────────────────────────────────
    _draw_logo(canvas, draw, spec, zones, logo_bytes)
    draw = ImageDraw.Draw(canvas)   # rebind after alpha_composite ops

    # ── 6. Headline ──────────────────────────────────────────────────────────
    headline_font  = load_font(spec.headline.font_weight, spec.headline.font_size)
    headline_color = hex_to_rgba(spec.headline.color)
    cursor_y       = zones.text_top

    headline_bottom = draw_text_block(
        draw, spec.headline.text, headline_font, headline_color,
        zones.text_x, cursor_y, zones.text_w, spec.headline.align,
    )

    # ── 7. Headline accent underline ─────────────────────────────────────────
    _draw_headline_accent(draw, spec, headline_bottom, zones)
    cursor_y = headline_bottom + 28   # gap after headline + underline

    # ── 8. Subheadline ───────────────────────────────────────────────────────
    if spec.subheadline:
        sub_font  = load_font(spec.subheadline.font_weight, spec.subheadline.font_size)
        sub_color = hex_to_rgba(spec.subheadline.color)
        cursor_y  = draw_text_block(
            draw, spec.subheadline.text, sub_font, sub_color,
            zones.text_x, cursor_y, zones.text_w, spec.subheadline.align,
        )
        cursor_y += 28

    # ── 9. Services grid OR body text ────────────────────────────────────────
    if spec.services:
        cursor_y = _draw_services_grid(draw, spec, zones, cursor_y)
    elif spec.body_text:
        body_font  = load_font(spec.body_text.font_weight, spec.body_text.font_size)
        body_color = hex_to_rgba(spec.body_text.color)
        cursor_y   = draw_text_block(
            draw, spec.body_text.text, body_font, body_color,
            zones.text_x, cursor_y, zones.text_w, spec.body_text.align,
        )

    # ── 10. CTA button ───────────────────────────────────────────────────────
    _draw_cta(draw, spec, zones)

    # ── 11. Contact bar ───────────────────────────────────────────────────────
    _draw_contact_bar(canvas, draw, spec, zones)
    draw = ImageDraw.Draw(canvas)

    # ── 12. Export ───────────────────────────────────────────────────────────
    out = canvas.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True, quality=95)
    return buf.getvalue()