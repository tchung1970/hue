"""Pure helpers for building Bridge schedules.

The Bridge uses the CLIP v1 ``/schedules`` API, whose trigger is encoded in a
``localtime`` string:

  * Recurring weekly:  ``W124/T23:00:00`` — ``W`` + weekday bitmask, then time.
  * One-time absolute: ``2026-06-30T23:00:00``.
  * Timer (relative):  ``PT00:30:00`` — fires once after the given duration.

These functions only build/validate those strings and the action body; all
network I/O lives in ``bridge.py``.
"""

from __future__ import annotations

from typing import Dict, Optional

# Weekday -> bitmask used by the Bridge's "W" localtime format.
_DAY_BITS = {
    "mon": 64,
    "tue": 32,
    "wed": 16,
    "thu": 8,
    "fri": 4,
    "sat": 2,
    "sun": 1,
}
_DAY_ALIASES = {
    "everyday": 127,
    "daily": 127,
    "all": 127,
    "weekdays": 124,  # mon-fri
    "weekday": 124,
    "weekend": 3,  # sat+sun
    "weekends": 3,
}


def day_mask(spec: str) -> int:
    """Turn a day spec into the Bridge's weekday bitmask.

    Accepts an alias (``everyday``, ``weekdays``, ``weekend``) or a comma list
    of day abbreviations (``mon,wed,fri``).
    """
    spec = spec.strip().lower()
    if spec in _DAY_ALIASES:
        return _DAY_ALIASES[spec]
    mask = 0
    for part in spec.split(","):
        part = part.strip()[:3]
        if part not in _DAY_BITS:
            raise ValueError(f"unknown day {part!r} (use mon..sun or weekdays/weekend/everyday)")
        mask |= _DAY_BITS[part]
    if mask == 0:
        raise ValueError("no days selected")
    return mask


def normalize_time(value: str) -> str:
    """Parse a clock time into 24h ``"HH:MM:SS"``.

    Accepts 24h (``"23:00"``, ``"7:5:0"``) and 12h AM/PM (``"11pm"``,
    ``"11:00 PM"``, ``"7am"``, ``"7:30am"``).
    """
    raw = value.strip().lower().replace(" ", "")
    meridiem = None
    if raw.endswith(("am", "pm")):
        meridiem = raw[-2:]
        raw = raw[:-2]

    parts = raw.split(":")
    if not (1 <= len(parts) <= 3):
        raise ValueError(f"invalid time {value!r} (e.g. 23:00 or 11pm)")
    try:
        nums = [int(p) for p in parts] + [0] * (3 - len(parts))
    except ValueError:
        raise ValueError(f"invalid time {value!r} (e.g. 23:00 or 11pm)")
    h, m, s = nums

    if meridiem:
        if not (1 <= h <= 12):
            raise ValueError(f"invalid 12h time {value!r} (hour must be 1-12)")
        h = h % 12 + (12 if meridiem == "pm" else 0)

    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError(f"time out of range: {value!r}")
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_localtime(
    time_str: str,
    *,
    days: Optional[str] = None,
    date: Optional[str] = None,
    timer_minutes: Optional[int] = None,
) -> str:
    """Build the ``localtime`` trigger string. Exactly one trigger style applies:
    timer (``timer_minutes``) > one-time (``date``) > recurring (``days``)."""
    if timer_minutes is not None:
        if timer_minutes <= 0:
            raise ValueError("timer minutes must be positive")
        h, m = divmod(timer_minutes, 60)
        return f"PT{h:02d}:{m:02d}:00"

    t = normalize_time(time_str)
    if date is not None:
        # Basic YYYY-MM-DD shape check; the Bridge validates the calendar date.
        y, mo, d = (int(x) for x in date.split("-"))
        return f"{y:04d}-{mo:02d}-{d:02d}T{t}"

    return f"W{day_mask(days or 'everyday')}/T{t}"


_MASK_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def clock_12h(time_str: str) -> str:
    """``"23:00:00"`` -> ``"11:00 PM"``. Falls back to the input on bad data."""
    try:
        parts = [int(p) for p in time_str.split(":")]
    except ValueError:
        return time_str
    h = parts[0]
    m = parts[1] if len(parts) > 1 else 0
    period = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m:02d} {period}"


def describe_localtime(localtime: str) -> str:
    """Render a Bridge ``localtime`` string back into something human-readable."""
    if localtime.startswith("PT"):
        return f"timer +{localtime[2:]}"
    if localtime.startswith("W") and "/T" in localtime:
        mask_str, _, time_str = localtime[1:].partition("/T")
        try:
            mask = int(mask_str)
        except ValueError:
            return localtime
        if mask == 127:
            days = "everyday"
        elif mask == 124:
            days = "weekdays"
        elif mask == 3:
            days = "weekend"
        else:
            days = ",".join(name for name, bit in zip(_MASK_NAMES, (64, 32, 16, 8, 4, 2, 1)) if mask & bit)
        return f"{days} at {clock_12h(time_str)}"
    if "T" in localtime:  # absolute one-time
        date_part, _, time_part = localtime.partition("T")
        return f"once on {date_part} at {clock_12h(time_part)}"
    return localtime


def brightness_to_v1(level: int) -> int:
    """0-100 percent -> the v1 API's 1-254 brightness scale."""
    if not 1 <= level <= 100:
        raise ValueError("brightness must be 1-100")
    return max(1, min(254, round(level / 100 * 254)))


def action_body(turn_on: bool, brightness: Optional[int] = None) -> Dict[str, object]:
    """The light/group state the schedule applies when it fires."""
    if not turn_on:
        return {"on": False}
    body: Dict[str, object] = {"on": True}
    if brightness is not None:
        body["bri"] = brightness_to_v1(brightness)
    return body
