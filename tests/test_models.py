from hue.models import describe_model


def test_known_models():
    assert describe_model("LCT014") == "A19 Warm-to-Cool White & Color Ambiance"
    assert describe_model("LTW011") == "BR30 Warm-to-Cool White Ambiance"
    assert describe_model("LWA003") == "A19 Hue White"


def test_unknown_model_returns_empty():
    assert describe_model("ZZZ999") == ""
