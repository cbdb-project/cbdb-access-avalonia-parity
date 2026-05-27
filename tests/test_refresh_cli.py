"""Tests for the `cbdb_parity.refresh.cli_main` entry point.

Locks the exit-code contract documented in AGENTS.md and the script docstring:
0 = all green, 1 = pull failed, 2 = config error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cbdb_parity import refresh as refresh_mod
from cbdb_parity.config import REFRESH_KEYS, ConfigError
from cbdb_parity.refresh import RefreshError, RefreshResult, cli_main


def _ok(key: str) -> RefreshResult:
    return RefreshResult(key, Path(f"/fake/{key}"), True, "aaaa", "aaaa", "Already up to date.")


def _fail(key: str) -> RefreshResult:
    return RefreshResult(key, Path(f"/fake/{key}"), False, "aaaa", "aaaa", "fatal: divergent")


def test_cli_exit_0_on_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(refresh_mod, "refresh_all", lambda: [_ok(k) for k in REFRESH_KEYS])

    rc = cli_main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "[up-to-date]" in out
    assert "FAILED" not in out


def test_cli_exit_1_on_refresh_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    bad = [
        _ok("ACCESS_TESTS_REPO"),
        _fail("AVALONIA_REPO"),
        _ok("ONLINE_SERVER_REPO"),
        _ok("ACCESS_MYSQL_TRANSFER_REPO"),
    ]

    def raises() -> list[RefreshResult]:
        raise RefreshError("1 of 4 refresh target(s) failed:\n  AVALONIA_REPO ...", bad)

    monkeypatch.setattr(refresh_mod, "refresh_all", raises)

    rc = cli_main()
    captured = capsys.readouterr()
    assert rc == 1
    # Every repo's status must appear, not just the failed one — otherwise
    # the user can't tell what's still healthy.
    assert "[up-to-date] ACCESS_TESTS_REPO" in captured.out
    assert "[FAILED]     AVALONIA_REPO" in captured.out
    assert "[up-to-date] ONLINE_SERVER_REPO" in captured.out
    assert "[up-to-date] ACCESS_MYSQL_TRANSFER_REPO" in captured.out
    assert "1 of 4 refresh target(s) failed" in captured.err


def test_cli_exit_2_on_config_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def raises() -> list[RefreshResult]:
        raise ConfigError(".env not found at /nope")

    monkeypatch.setattr(refresh_mod, "refresh_all", raises)

    rc = cli_main()
    captured = capsys.readouterr()
    assert rc == 2
    assert "config error" in captured.err
    assert ".env not found" in captured.err
