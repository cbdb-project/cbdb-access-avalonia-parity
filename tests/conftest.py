"""Pytest fixtures shared across the harness test suite."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def fake_env(tmp_path: Path) -> Path:
    """Build a fake .env pointing at tmp_path-rooted dirs/files.

    Creates the directories and a placeholder mdb file so that
    `cbdb_parity.config.load_config` can succeed in tests without touching
    the real environment.
    """
    base = tmp_path / "fake"
    base.mkdir()

    dirs = {
        "DATADUMP_DIR": base / "datadump",
        "ACCESS_TESTS_REPO": base / "cbdb-user-mdb-tests",
        "AVALONIA_REPO": base / "cbdb-desktop-app",
        "ONLINE_SERVER_REPO": base / "cbdb-online-main-server",
        "ACCESS_MYSQL_TRANSFER_REPO": base / "accessAndMySQLTransfer",
        "MYSQL2ACCESS_DIR": base / "mysql2access",
        "BUILD_OUTPUT_DIR": base / "build",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    # The four REFRESH_KEYS dirs must look like git repos for the
    # refresh-target validation; create a placeholder `.git/` in each.
    for key in (
        "ACCESS_TESTS_REPO",
        "AVALONIA_REPO",
        "ONLINE_SERVER_REPO",
        "ACCESS_MYSQL_TRANSFER_REPO",
    ):
        (dirs[key] / ".git").mkdir(parents=True, exist_ok=True)

    user_mdb = base / "CBDB_BJ_User.mdb"
    user_mdb.write_bytes(b"")

    env = tmp_path / ".env"
    lines = [f"CBDB_USER_MDB={user_mdb}"]
    lines += [f"{k}={v}" for k, v in dirs.items()]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env


@pytest.fixture(scope="session")
def _parity_host_session_daemon() -> Iterator[object | None]:
    """Phase 8a — internal session-scoped fixture. Starts ONE
    ParityHostDaemon subprocess for the whole pytest session so
    we only pay the ~1s `dotnet run` cold-start once.

    Critically does NOT skip the whole module/session when
    prereqs are missing — yields `None` instead. The per-test
    `parity_host_daemon` fixture below decides what to do with
    a None session daemon (it just yields None too; tests
    opting into the fixture still run via the legacy one-shot
    path).

    Codex 8a round flagged that an earlier draft of this
    fixture skipped on missing prereqs at session scope, which
    caused the `usefixtures("parity_host_daemon")` mark on
    `test_phase4_replay_scan.py` to skip Access-only entry/
    office/status cases on machines without ParityHost built —
    a coverage regression for tests that never needed the host.
    Yielding None preserves coverage for those cases.
    """
    try:
        from cbdb_parity.config import load_config
    except ImportError:
        yield None
        return
    try:
        cfg = load_config()
    except FileNotFoundError:
        yield None
        return

    if not (shutil.which("dotnet") or Path(r"C:\Program Files\dotnet\dotnet.exe").is_file()):
        yield None
        return
    repo_root = Path(__file__).resolve().parent.parent
    host_dll = (
        repo_root / "parity_host" / "Cbdb.App.ParityHost"
        / "bin" / "Debug" / "net8.0" / "cbdb-parity-host.dll"
    )
    if not host_dll.is_file():
        yield None
        return

    from cbdb_parity.parity_host import ParityHostDaemon

    with ParityHostDaemon(avalonia_repo=cfg.avalonia_repo) as daemon:
        yield daemon


@pytest.fixture(scope="function")
def parity_host_daemon(_parity_host_session_daemon: object | None) -> Iterator[object | None]:
    """Phase 8a — per-test binding of the session daemon to the
    process-active `_active_daemon` ContextVar. Codex 8a round
    flagged that a session-scope binding stayed set in the main
    pytest context for the entire run, which:
      - leaks the daemon to subsequent tests that don't declare
        the fixture (order-dependent behaviour);
      - amplifies a single host crash into a session-wide
        cascade.

    Function-scope binding fixes both: every test that opts in
    gets the daemon bound on entry and reset on exit, so a test
    not declaring this fixture never sees a stale binding.

    When the session daemon is None (prereqs missing — e.g. on a
    machine without ParityHost built), yields None and skips the
    binding. Tests that opted in via `usefixtures` still run;
    `invoke_parity_host` falls back to the legacy one-shot path,
    which is also what an out-of-bind call would do.
    """
    if _parity_host_session_daemon is None:
        yield None
        return
    from cbdb_parity.parity_host import bind_active_daemon
    with bind_active_daemon(_parity_host_session_daemon):
        yield _parity_host_session_daemon
