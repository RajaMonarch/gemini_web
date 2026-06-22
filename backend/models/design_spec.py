from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, field_validator


class TextZone(BaseModel):
    text:        str
    x:           int
    y:           int
    w:           int
    h:           int
    font_size:   int
    font_weight: Literal["regular", "bold"]
    color:       str
    align:       Literal["left", "center", "right"]

    @field_validator("font_weight", mode="before")
    @classmethod
    def normalise_font_weight(cls, v: str) -> str:
        return {
            "normal": "regular", "400": "regular", "regular": "regular",
            "bold": "bold", "700": "bold", "600": "bold",
            "500": "bold", "semibold": "bold", "medium": "bold",
        }.get(str(v).lower(), "regular")

    @field_validator("color", mode="before")
    @classmethod
    def ensure_hash(cls, v: str) -> str:
        v = str(v).strip()
        return v if v.startswith("#") else f"#{v}"


class DesignSpec(BaseModel):
    # Canvas
    canvas_w:   int = 1080
    canvas_h:   int = 1080

    # AI background
    background_prompt: str
    overlay_color:     str   # hex+alpha e.g. "#00000099"

    # Layout mode — drives how the compositor positions every element
    # "bottom-text" : subjects top 55%, all text bottom 45%  (default)
    # "left-text"   : subjects right 50%, text left 50%
    # "split"       : subjects top-right quadrant, text top-left + full bottom
    layout_mode: Literal["bottom-text", "left-text", "split"] = "bottom-text"

    # Typography zones
    headline:    TextZone
    subheadline: TextZone | None = None
    body_text:   TextZone | None = None

    # Services grid (optional — up to 8 items)
    services:    list[str] | None = None

    # Brand name text fallback (shown when no logo image is uploaded)
    brand_name:  str | None = None

    # Contact / footer
    contact_line:      str | None = None
    website_line:      str | None = None
    contact_color:     str        = "#FFFFFF"
    contact_font_size: int        = 22
    contact_bg:        str | None = None

    # CTA
    cta_text:  str
    cta_bg:    str
    cta_color: str

    # Brand palette
    brand_color_primary:   str
    brand_color_secondary: str
    accent_color:          str | None = None   # third brand accent if provided

    # Logo placement
    logo_position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "top-left"

    @field_validator(
        "overlay_color", "cta_bg", "cta_color", "contact_color",
        "brand_color_primary", "brand_color_secondary",
        mode="before",
    )
    @classmethod
    def ensure_hash_top(cls, v: str) -> str:
        v = str(v).strip()
        return v if v.startswith("#") else f"#{v}"

    @field_validator("accent_color", mode="before")
    @classmethod
    def ensure_hash_optional(cls, v) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        return v if v.startswith("#") else f"#{v}"