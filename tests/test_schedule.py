import pytest

from hue.schedule import (
    action_body,
    brightness_to_v1,
    build_localtime,
    day_mask,
    describe_localtime,
    normalize_time,
)


def test_day_mask_aliases():
    assert day_mask("everyday") == 127
    assert day_mask("weekdays") == 124
    assert day_mask("weekend") == 3


def test_day_mask_custom_list():
    # mon(64) + wed(16) + fri(4)
    assert day_mask("mon,wed,fri") == 84
    assert day_mask("Monday") == 64  # truncated to 'mon'


def test_day_mask_rejects_unknown():
    with pytest.raises(ValueError):
        day_mask("funday")


def test_normalize_time():
    assert normalize_time("23:00") == "23:00:00"
    assert normalize_time("7:5") == "07:05:00"
    with pytest.raises(ValueError):
        normalize_time("25:00")


def test_normalize_time_ampm():
    assert normalize_time("11pm") == "23:00:00"
    assert normalize_time("11:00 PM") == "23:00:00"
    assert normalize_time("7am") == "07:00:00"
    assert normalize_time("7:30am") == "07:30:00"
    assert normalize_time("12am") == "00:00:00"  # midnight
    assert normalize_time("12pm") == "12:00:00"  # noon


def test_normalize_time_ampm_out_of_range():
    with pytest.raises(ValueError):
        normalize_time("13pm")


def test_build_localtime_recurring():
    assert build_localtime("23:00", days="weekdays") == "W124/T23:00:00"


def test_build_localtime_one_time():
    assert build_localtime("22:30", date="2026-07-04") == "2026-07-04T22:30:00"


def test_build_localtime_timer_ignores_time():
    assert build_localtime("00:00", timer_minutes=90) == "PT01:30:00"


def test_build_localtime_timer_must_be_positive():
    with pytest.raises(ValueError):
        build_localtime("00:00", timer_minutes=0)


def test_brightness_to_v1_scale():
    assert brightness_to_v1(100) == 254
    assert brightness_to_v1(1) == 3  # round(1/100*254)=3, floored at 1
    with pytest.raises(ValueError):
        brightness_to_v1(0)


def test_action_body():
    assert action_body(False) == {"on": False}
    assert action_body(True) == {"on": True}
    assert action_body(True, 50) == {"on": True, "bri": 127}


def test_describe_localtime_roundtrips_readably():
    assert describe_localtime("W124/T23:00:00") == "weekdays at 11:00 PM"
    assert describe_localtime("W127/T07:00:00") == "everyday at 7:00 AM"
    assert describe_localtime("PT00:30:00") == "timer +00:30:00"
    assert describe_localtime("2026-07-04T22:30:00") == "once on 2026-07-04 at 10:30 PM"
