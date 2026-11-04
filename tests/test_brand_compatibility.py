import pytest

from pactora.config import Settings, env


def test_legacy_environment_is_supported(settings, monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith(("PACTORA_", "VEILCART_")):
            monkeypatch.delenv(name)
    for suffix, value in {
        "DATA": str(settings.data_dir),
        "MASTER_KEY": settings.master_key,
        "GATEWAY_KEY": settings.gateway_key,
        "PASSWORD_HASH": settings.password_hash,
    }.items():
        monkeypatch.setenv("VEILCART_" + suffix, value)
    actual = Settings.from_env()
    assert actual.data_dir == settings.data_dir
    assert actual.gateway_key == settings.gateway_key
    monkeypatch.setenv("PACTORA_GATEWAY_KEY", "new-" + settings.gateway_key)
    assert Settings.from_env().gateway_key == "new-" + settings.gateway_key


def test_empty_primary_does_not_silently_use_legacy(monkeypatch):
    monkeypatch.setenv("VEILCART_GATEWAY_KEY", "legacy")
    monkeypatch.setenv("PACTORA_GATEWAY_KEY", "")
    assert env("PACTORA_GATEWAY_KEY") == ""


def test_missing_required_setting(monkeypatch):
    monkeypatch.delenv("PACTORA_REQUIRED", raising=False)
    monkeypatch.delenv("VEILCART_REQUIRED", raising=False)
    with pytest.raises(KeyError):
        env("PACTORA_REQUIRED")
