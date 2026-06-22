# services/zone_analyser.py
from PIL import Image, ImageFilter
import io
from dataclasses import dataclass


@dataclass
class LayoutZones:
    layout:       str          # "bottom-text" | "top-text" | "split"
    text_y_start: int          # top of safe text region in pixels
    text_y_end:   int          # bottom of safe text region
    text_x:       int          # left edge of text block
    text_w:       int          # width of text block
    overlay_rect: tuple        # (x, y, w, h) for the darkening overlay


def analyse_zones(bg_bytes: bytes, canvas_w: int, canvas_h: int) -> LayoutZones:
    """
    Scans the generated background image and finds the safest region
    for text placement based on brightness and edge density.
    Returns a LayoutZones describing where to place all text elements.
    """
    img = Image.open(io.BytesIO(bg_bytes)).convert("L")   # grayscale
    img = img.resize((canvas_w, canvas_h), Image.LANCZOS)

    # Blur heavily — we care about broad regions not individual pixels
    blurred = img.filter(ImageFilter.GaussianBlur(radius=40))

    # Divide canvas into 3 horizontal bands and score each
    band_h   = canvas_h // 3
    bands    = {
        "top":    _band_brightness(blurred, 0,          band_h,     canvas_w),
        "middle": _band_brightness(blurred, band_h,     band_h * 2, canvas_w),
        "bottom": _band_brightness(blurred, band_h * 2, canvas_h,   canvas_w),
    }

    # Lower brightness = safer for white text
    # Score = brightness (lower is better)
    bottom_safe = bands["bottom"] < 100
    top_safe    = bands["top"]    < 100

    MARGIN  = 60    # px from canvas edge
    TEXT_W  = canvas_w - (MARGIN * 2)

    if bottom_safe:
        # Standard layout: image subjects top, text bottom
        text_y_start = int(canvas_h * 0.52)
        return LayoutZones(
            layout       = "bottom-text",
            text_y_start = text_y_start,
            text_y_end   = canvas_h - 160,   # leave room for contact bar
            text_x       = MARGIN,
            text_w       = TEXT_W,
            overlay_rect = (0, text_y_start - 40, canvas_w, canvas_h - text_y_start + 40),
        )
    elif top_safe:
        # Inverted: subjects bottom, text top
        text_y_end = int(canvas_h * 0.48)
        return LayoutZones(
            layout       = "top-text",
            text_y_start = MARGIN,
            text_y_end   = text_y_end,
            text_x       = MARGIN,
            text_w       = TEXT_W,
            overlay_rect = (0, 0, canvas_w, text_y_end + 40),
        )
    else:
        # Fallback: full overlay split layout — darken entire canvas heavily
        return LayoutZones(
            layout       = "split",
            text_y_start = int(canvas_h * 0.55),
            text_y_end   = canvas_h - 160,
            text_x       = MARGIN,
            text_w       = TEXT_W,
            overlay_rect = (0, 0, canvas_w, canvas_h),
        )


def _band_brightness(img: Image.Image, y1: int, y2: int, w: int) -> float:
    """Returns average pixel brightness for a horizontal band (0=black, 255=white)."""
    band = img.crop((0, y1, w, y2))
    pixels = list(band.getdata())
    return sum(pixels) / len(pixels) if pixels else 128.0