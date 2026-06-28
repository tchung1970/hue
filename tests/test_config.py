import json

from hue.config import Config, config_path


def test_config_path_honors_env_override(monkeypatch, tmp_path):
    target = tmp_path / "custom.json"
    monkeypatch.setenv("HUE_CONFIG", str(target))
    assert config_path() == target


def test_load_returns_empty_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HUE_CONFIG", str(tmp_path / "nope.json"))
    cfg = Config.load()
    assert not cfg.is_paired


def test_save_then_load_roundtrip_and_perms(monkeypatch, tmp_path):
    monkeypatch.setenv("HUE_CONFIG", str(tmp_path / "config.json"))
    Config(bridge_ip="10.0.0.5", app_key="secret", client_key="ck").save()

    cfg = Config.load()
    assert cfg.is_paired
    assert cfg.bridge_ip == "10.0.0.5"
    assert cfg.app_key == "secret"

    # Credential file must not be world-readable.
    assert oct(config_path().stat().st_mode & 0o777) == "0o600"


def test_is_paired_requires_both_ip_and_key():
    assert not Config(bridge_ip="10.0.0.5").is_paired
    assert not Config(app_key="secret").is_paired
    assert Config(bridge_ip="10.0.0.5", app_key="secret").is_paired
