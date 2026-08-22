"""Unit tests for CLI helpers in main.py (no network)."""

import argparse
import json
import logging
from datetime import UTC, datetime

import pytest

from main import JsonFormatter, _parse_since, _setup_logging, _watch_loop


class TestParseSince:
    def test_parses_date(self):
        parsed = _parse_since("2024-01-31")
        assert parsed == datetime(2024, 1, 31, tzinfo=UTC)

    def test_parses_datetime_with_z_suffix(self):
        parsed = _parse_since("2024-01-31T12:00:00Z")
        assert parsed == datetime(2024, 1, 31, 12, 0, 0, tzinfo=UTC)

    def test_naive_datetime_assumed_utc(self):
        parsed = _parse_since("2024-01-31T12:00:00")
        assert parsed.tzinfo is UTC

    def test_preserves_explicit_offset(self):
        parsed = _parse_since("2024-01-31T12:00:00+02:00")
        assert parsed.utcoffset().total_seconds() == 7200

    def test_invalid_date_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="invalid date"):
            _parse_since("not-a-date")


class TestJsonFormatter:
    def _record(self, **kwargs) -> logging.LogRecord:
        defaults = {
            "name": "test.logger",
            "level": logging.INFO,
            "pathname": __file__,
            "lineno": 1,
            "msg": "hello %s",
            "args": ("world",),
            "exc_info": None,
        }
        defaults.update(kwargs)
        return logging.LogRecord(**defaults)

    def test_outputs_valid_json(self):
        entry = json.loads(JsonFormatter().format(self._record()))
        assert entry["level"] == "INFO"
        assert entry["logger"] == "test.logger"
        assert entry["message"] == "hello world"
        assert "timestamp" in entry

    def test_includes_exc_info(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = self._record(exc_info=sys.exc_info())
        entry = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in entry["exc_info"]

    def test_non_ascii_preserved(self):
        record = self._record(msg="café: sync terminé", args=())
        entry = json.loads(JsonFormatter().format(record))
        assert entry["message"] == "café: sync terminé"


class TestSetupLogging:
    def test_json_format_installs_json_formatter(self):
        _setup_logging(verbose=False, log_format="json")
        handlers = logging.getLogger().handlers
        assert any(isinstance(h.formatter, JsonFormatter) for h in handlers)

    def test_text_format_uses_default_formatter(self):
        _setup_logging(verbose=True, log_format="text")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)


class TestWatchLoop:
    def test_advances_since_between_passes(self):
        """Pass N+1 must receive a cutoff taken at the start of pass N."""
        seen: list[datetime | None] = []
        sleeps: list[float] = []

        def run_pass(since):
            seen.append(since)

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 3:
                raise KeyboardInterrupt

        initial = datetime(2024, 1, 1, tzinfo=UTC)
        with pytest.raises(KeyboardInterrupt):
            _watch_loop(run_pass, 60, initial, sleep=fake_sleep)

        assert len(seen) == 3
        assert seen[0] == initial
        # Later passes use the previous pass's start time (recent, tz-aware).
        assert seen[1] is not None and seen[1] > initial
        assert seen[2] is not None and seen[2] >= seen[1]
        assert sleeps == [60, 60, 60]

    def test_first_pass_can_have_no_cutoff(self):
        seen = []

        def fake_sleep(_):
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            _watch_loop(seen.append, 5, None, sleep=fake_sleep)

        assert seen == [None]
