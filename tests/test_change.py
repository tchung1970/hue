import pytest

from hue.cli import _ct_label, _state_body


def test_on_off_tokens():
    assert _state_body("on", None) == {"on": {"on": True}}
    assert _state_body("off", None) == {"on": {"on": False}}


def test_brightness_number():
    assert _state_body("40", None) == {"on": {"on": True}, "dimming": {"brightness": 40.0}}


def test_zero_brightness_turns_off():
    assert _state_body("0", None) == {"on": {"on": False}}


def test_warm_preset():
    body = _state_body("warm", None)
    assert body["on"] == {"on": True}
    assert body["color_temperature"]["mirek"] == 370  # 2700K -> ~370 mirek


def test_cool_preset():
    body = _state_body("cool", None)
    assert body["on"] == {"on": True}
    assert body["color_temperature"]["mirek"] == 200  # 5000K -> 200 mirek


def test_warm_cool_case_insensitive():
    assert _state_body("WARM", None) == _state_body("warm", None)


def test_ct_implies_on():
    body = _state_body(None, 2700)
    assert body["on"] == {"on": True}
    assert body["color_temperature"]["mirek"] == 370  # 1e6/2700 ~= 370


def test_state_and_ct_combine():
    body = _state_body("on", 6500)
    assert body["on"] == {"on": True}
    assert "color_temperature" in body


def test_bad_state_rejected():
    with pytest.raises(ValueError):
        _state_body("purple", None)


def test_out_of_range_brightness_rejected():
    with pytest.raises(ValueError):
        _state_body("150", None)


def test_empty_change_rejected():
    with pytest.raises(ValueError):
        _state_body(None, None)


def test_ct_label_warm():
    assert _ct_label({"color_temperature": {"mirek": 370}}) == "2703K warm"


def test_ct_label_cool():
    assert _ct_label({"color_temperature": {"mirek": 200}}) == "5000K cool"


def test_ct_label_neutral():
    assert _ct_label({"color_temperature": {"mirek": 250}}) == "4000K neutral"


def test_ct_label_absent_when_no_mirek():
    assert _ct_label({"color_temperature": {"mirek": None}}) == ""
    assert _ct_label({}) == ""
