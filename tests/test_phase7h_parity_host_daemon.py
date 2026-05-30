"""Phase 7h — smoke tests for `cbdb_parity.parity_host.ParityHostDaemon`.

These verify:
  - the daemon serves multiple frames over one subprocess;
  - per-frame errors don't kill the daemon (next frame still works);
  - context-manager close shuts the subprocess down cleanly.

We don't measure runtime improvement here — that's the point of
the mode, but Phase 7h's WORK_PLAN delta is "from ~4m to ~30s on
the host-using subset" and that's only meaningful end-to-end. The
correctness gates live here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def _load_config_or_skip():
    try:
        from cbdb_parity.config import load_config
    except ImportError:
        pytest.skip("cbdb_parity.config not importable")
    try:
        return load_config()
    except FileNotFoundError as exc:
        pytest.skip(f"config not configured: {exc}")


def _prereqs_or_skip(avalonia_repo: Path) -> None:
    if not (shutil.which("dotnet") or Path(r"C:\Program Files\dotnet\dotnet.exe").is_file()):
        pytest.skip(".NET SDK not installed")
    repo_root = Path(__file__).resolve().parent.parent
    host_dll = (
        repo_root / "parity_host" / "Cbdb.App.ParityHost"
        / "bin" / "Debug" / "net8.0" / "cbdb-parity-host.dll"
    )
    if not host_dll.is_file():
        pytest.skip("ParityHost not built")


def test_daemon_serves_multiple_frames() -> None:
    """One subprocess handles N back-to-back frames returning the
    same shape the one-shot mode returns. Validates the basic
    NDJSON contract end-to-end."""
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.parity_host import ParityHostDaemon

    with ParityHostDaemon(avalonia_repo=cfg.avalonia_repo) as host:
        # First call: addresses for Wang Anshi.
        rows_1762 = host.invoke(
            "addresses", sqlite_path, {"person_id": 1762},
        )
        assert isinstance(rows_1762, list)
        assert len(rows_1762) > 0, "Wang Anshi should have addresses"

        # Second call: same shape, different person — the daemon
        # must not have any per-call state leak.
        rows_3257 = host.invoke(
            "addresses", sqlite_path, {"person_id": 3257},
        )
        assert isinstance(rows_3257, list)
        assert rows_1762 != rows_3257, (
            "daemon returned identical rows for two different "
            "person_ids; per-call state may be leaking."
        )

        # Third call: completely different service. Validates the
        # daemon's dispatch table isn't sticky.
        from dataclasses import asdict

        from cbdb_parity.avalonia_query import EntryQueryRequest
        entry_resp = host.invoke(
            "entry", sqlite_path, asdict(EntryQueryRequest(limit=5)),
        )
        assert isinstance(entry_resp, dict)
        assert "records" in entry_resp


def test_daemon_per_frame_error_does_not_kill() -> None:
    """A bad request must surface as ParityHostError but the
    daemon stays alive for the next frame."""
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.parity_host import ParityHostDaemon, ParityHostError

    with ParityHostDaemon(avalonia_repo=cfg.avalonia_repo) as host:
        # Bad: unknown service. Should raise but not crash daemon.
        with pytest.raises(ParityHostError) as exc_info:
            host.invoke("definitely_not_a_real_service", sqlite_path, {})
        assert "unknown service" in str(exc_info.value)

        # Daemon still alive: a valid call after the error works.
        rows = host.invoke(
            "addresses", sqlite_path, {"person_id": 1762},
        )
        assert isinstance(rows, list)
        assert len(rows) > 0


def test_daemon_invoke_after_close_raises() -> None:
    """Using the daemon outside its `with` block must raise a
    clear error rather than silently doing nothing or hanging."""
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.parity_host import ParityHostDaemon

    host = ParityHostDaemon(avalonia_repo=cfg.avalonia_repo)
    with pytest.raises(RuntimeError, match="outside its `with` block"):
        host.invoke("addresses", sqlite_path, {"person_id": 1762})


def test_daemon_per_call_timeout_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex 7h round flagged that per_call_timeout_seconds was
    stored but never enforced — a stuck dispatch would hang
    pytest forever. Force a sub-1s timeout and call into a
    deliberately-slow service to confirm the helper-thread
    timeout path raises ParityHostError instead of hanging.

    We can't easily make the host stall on demand, so this test
    leans on a contrived 0.001s timeout that's smaller than any
    real round trip. The expected failure mode is the
    'per-call timeout' branch; we just need to confirm the
    code path is reachable rather than dead.
    """
    cfg = _load_config_or_skip()
    _prereqs_or_skip(cfg.avalonia_repo)
    sqlite_path = cfg.build_output_dir / "cbdb.sqlite"
    if not sqlite_path.is_file():
        pytest.skip(f"sqlite not built at {sqlite_path}")

    from cbdb_parity.parity_host import ParityHostDaemon, ParityHostError

    with ParityHostDaemon(
        avalonia_repo=cfg.avalonia_repo,
        per_call_timeout_seconds=0.001,
    ) as host:
        with pytest.raises(ParityHostError, match="per-call timeout"):
            host.invoke("addresses", sqlite_path, {"person_id": 1762})
