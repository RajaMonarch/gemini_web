# services/qa.py
from models.design_spec import DesignSpec

def relative_luminance(rgb: tuple) -> float:
    def channel(c):
        c /= 255
        return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
    r,g,b = [channel(x) for x in rgb[:3]]
    return 0.2126*r + 0.7152*g + 0.0722*b

def contrast_ratio(fg: tuple, bg: tuple) -> float:
    L1 = max(relative_luminance(fg), relative_luminance(bg))
    L2 = min(relative_luminance(fg), relative_luminance(bg))
    return (L1 + 0.05) / (L2 + 0.05)

def check_headline_contrast(spec: DesignSpec) -> bool:
    from .compositor import hex_to_rgba
    fg = hex_to_rgba(spec.headline.color)
    # Sample overlay color as effective background approximation
    bg = hex_to_rgba(spec.overlay_color)
    ratio = contrast_ratio(fg, bg)
    return ratio >= 4.5   # WCAG AA for large text