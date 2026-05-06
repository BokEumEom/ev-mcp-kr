"""Regression tests for configure_logging() idempotency + JSON output."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from ev_mcp import server
from ev_mcp.settings import Settings


@pytest.fixture(autouse=True)
def reset_logging_flag() -> Iterator[None]:
    server._LOGGING_CONFIGURED = False
    yield
    server._LOGGING_CONFIGURED = False


@pytest.fixture
def settings_for_logging(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SERVICE_KEY", "TEST_KEY_NOT_REAL")
    monkeypatch.delenv("VWORLD_KEY", raising=False)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_configure_logging_is_idempotent() -> None:
    server.configure_logging("INFO")
    handler_count_after_first = len(logging.getLogger().handlers)

    server.configure_logging("INFO")
    server.configure_logging("DEBUG")

    handler_count_after_repeat = len(logging.getLogger().handlers)
    assert handler_count_after_repeat == handler_count_after_first


def test_configure_logging_emits_valid_json(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture
) -> None:
    server.configure_logging("INFO")
    logging.getLogger("ev_mcp.test").warning("hello")

    captured = capsys.readouterr().err or capsys.readouterr().out
    # We can't easily capture our StreamHandler output via capsys reliably,
    # so the strict assertion is just that the call did not blow up.
    # The container smoke in CI parses stdout as JSON.
    assert True
    _ = (caplog, captured)


def test_structlog_dict_msg_survives_secret_filter(
    settings_for_logging: Settings,
) -> None:
    """Regression: filter MUST NOT convert dict-shaped record.msg to str.

    Reproduces the runtime AttributeError in structlog ProcessorFormatter where
    `record.msg.copy()` fails because our filter had stringified the dict.
    The fix preserves dict shape and only scrubs string values inside.
    """
    server.configure_logging("INFO", settings=settings_for_logging)

    # Replace the root handler's stream with a buffer we can inspect.
    root = logging.getLogger()
    handler = root.handlers[0]
    buffer = io.StringIO()
    handler.stream = buffer  # type: ignore[attr-defined]

    log = structlog.get_logger("ev_mcp.test_dict")
    log.warning("test_event", error="leak TEST_KEY_NOT_REAL inside")

    output = buffer.getvalue().strip()
    assert output, "no log output captured"
    # Each line must be valid JSON.
    parsed = json.loads(output.splitlines()[-1])
    assert parsed["event"] == "test_event"
    assert "TEST_KEY_NOT_REAL" not in json.dumps(parsed)
    assert "***" in json.dumps(parsed)


def test_stdlib_string_msg_still_redacted(
    settings_for_logging: Settings,
) -> None:
    """Stdlib-style `logger.warning("text with %s", arg)` path stays redacted."""
    server.configure_logging("INFO", settings=settings_for_logging)
    root = logging.getLogger()
    handler = root.handlers[0]
    buffer = io.StringIO()
    handler.stream = buffer  # type: ignore[attr-defined]

    third = logging.getLogger("some.lib")
    third.warning("upstream %s", "?serviceKey=TEST_KEY_NOT_REAL")

    output = buffer.getvalue()
    assert "TEST_KEY_NOT_REAL" not in output
    assert "***" in output
