import pytest

from hue.color import hex_to_rgb, hex_to_xy, kelvin_to_mirek, rgb_to_xy


def test_hex_to_rgb_full_and_shorthand():
    assert hex_to_rgb("#ff8800") == (255, 136, 0)
    assert hex_to_rgb("f80") == (255, 136, 0)


def test_hex_to_rgb_rejects_bad_input():
    with pytest.raises(ValueError):
        hex_to_rgb("#12")


def test_rgb_to_xy_is_normalized_chromaticity():
    x, y = rgb_to_xy(255, 255, 255)
    # White point sums well below 1 on each axis and stays in gamut.
    assert 0 < x < 1 and 0 < y < 1


def test_pure_red_skews_toward_red_primary():
    x, _ = hex_to_xy("#ff0000")
    assert x > 0.6


def test_kelvin_to_mirek_in_range():
    assert kelvin_to_mirek(6500) == 154  # 1e6 / 6500 = 153.8 -> 154
    assert kelvin_to_mirek(2000) == 500


def test_kelvin_to_mirek_clamps_out_of_range():
    assert kelvin_to_mirek(10000) == 153  # cooler than Hue's coolest -> clamp
    assert kelvin_to_mirek(1000) == 500  # warmer than Hue's warmest -> clamp
