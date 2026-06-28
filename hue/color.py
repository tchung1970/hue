"""Color helpers — convert sRGB hex into the CIE xy values the CLIP API expects."""

from __future__ import annotations

from typing import Tuple


def hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:  # shorthand like "f0a" -> "ff00aa"
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"invalid hex color: {value!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _gamma(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def rgb_to_xy(r: int, g: int, b: int) -> Tuple[float, float]:
    """sRGB (0-255) -> CIE 1931 xy chromaticity, using the Wide RGB D65 matrix
    Philips documents for Hue bulbs."""
    rf, gf, bf = (_gamma(v / 255.0) for v in (r, g, b))
    x = rf * 0.664511 + gf * 0.154324 + bf * 0.162028
    y = rf * 0.283881 + gf * 0.668433 + bf * 0.047685
    z = rf * 0.000088 + gf * 0.072310 + bf * 0.986039
    total = x + y + z
    if total == 0:
        return 0.0, 0.0
    return x / total, y / total


def hex_to_xy(value: str) -> Tuple[float, float]:
    return rgb_to_xy(*hex_to_rgb(value))


def kelvin_to_mirek(kelvin: int) -> int:
    """Color temperature in Kelvin -> mirek (micro reciprocal degrees).
    Hue accepts 153 (~6500K, cool) to 500 (2000K, warm)."""
    mirek = round(1_000_000 / kelvin)
    return max(153, min(500, mirek))
