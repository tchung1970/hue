"""Friendly descriptions for Philips Hue bulb model ids.

The Bridge reports a terse model id (e.g. ``LCT014``) in each device's
``product_data``. This maps the common ones to a human-readable label including
form factor and capability. Unknown ids fall back to an empty description so the
raw id still shows.
"""

from __future__ import annotations

# Curated set — includes the models on this network plus other common ones.
MODEL_NAMES = {
    # White & Color Ambiance (color + tunable white), A19/E26
    "LCT014": "A19 Warm-to-Cool White & Color Ambiance",
    "LCT015": "A19 Warm-to-Cool White & Color Ambiance",
    "LCT016": "A19 Warm-to-Cool White & Color Ambiance",
    "LCA001": "A19 Warm-to-Cool White & Color Ambiance",
    "LCA005": "A19 Warm-to-Cool White & Color Ambiance",
    "LCA006": "A19 Warm-to-Cool White & Color Ambiance",
    "LCA007": "A19 Warm-to-Cool White & Color Ambiance",
    # White Ambiance (tunable white, no color)
    "LTW010": "A19 Warm-to-Cool White Ambiance",
    "LTA001": "A19 Warm-to-Cool White Ambiance",
    "LTW011": "BR30 Warm-to-Cool White Ambiance",
    "LTW012": "E12 Warm-to-Cool White Ambiance",
    # White (soft white only, dimmable)
    "LWB006": "A19 Hue White",
    "LWB010": "A19 Hue White",
    "LWB014": "A19 Hue White",
    "LWA001": "A19 Hue White",
    "LWA003": "A19 Hue White",
    "LWA008": "A19 Hue White",
}


def describe_model(model_id: str) -> str:
    """Return a friendly label for a model id, or '' if unknown."""
    return MODEL_NAMES.get(model_id, "")
