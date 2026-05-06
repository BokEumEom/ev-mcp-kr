"""Regression tests: SERVICE_KEY masking covers URL-encoded variants."""

from __future__ import annotations

import urllib.parse

import pytest

from ev_mcp.client import EvChargerClient
from ev_mcp.geocode import Geocoder
from ev_mcp.settings import Settings


@pytest.fixture
def settings_with_special_key(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """data.go.kr keys often contain '+' '/' '=' which encode differently."""
    monkeypatch.setenv("SERVICE_KEY", "abc+def/ghi=jkl")
    monkeypatch.setenv("VWORLD_KEY", "vw+key/with==pad")
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_client_redact_strips_raw_key(settings_with_special_key: Settings) -> None:
    client = EvChargerClient(settings_with_special_key)
    msg = "error: serviceKey=abc+def/ghi=jkl in body"
    assert "abc+def/ghi=jkl" not in client.redact(msg)
    assert "***" in client.redact(msg)


def test_client_redact_strips_quote_variant(settings_with_special_key: Settings) -> None:
    client = EvChargerClient(settings_with_special_key)
    encoded = urllib.parse.quote("abc+def/ghi=jkl", safe="")
    msg = f"upstream URL: ...?serviceKey={encoded}&dataType=JSON"
    redacted = client.redact(msg)
    assert encoded not in redacted
    assert "***" in redacted


def test_client_redact_strips_quote_plus_variant(settings_with_special_key: Settings) -> None:
    client = EvChargerClient(settings_with_special_key)
    encoded = urllib.parse.quote_plus("abc+def/ghi=jkl")
    msg = f"upstream URL: ...?serviceKey={encoded}&dataType=JSON"
    redacted = client.redact(msg)
    assert encoded not in redacted
    assert "***" in redacted


def test_geocoder_redact_strips_quote_variants(
    settings_with_special_key: Settings,
) -> None:
    geo = Geocoder(settings_with_special_key)
    raw = "vw+key/with==pad"
    encoded = urllib.parse.quote(raw, safe="")
    plus = urllib.parse.quote_plus(raw)
    for form in (raw, encoded, plus):
        msg = f"vworld error for ...?key={form}"
        redacted = geo._redact(msg)
        assert form not in redacted
        assert "***" in redacted
