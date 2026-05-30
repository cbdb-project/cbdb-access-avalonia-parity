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
def parity_host_daemon() -> Iterator[object]:
    """Phase 8a — session-scoped fixture that starts one
    `ParityHostDaemon` and binds it as the process-active
    daemon for the duration of the session. Any test that
    declares `parity_host_daemon` (directly or transitively)
    gets every subsequent `invoke_parity_host` /
    `invoke_person_accessor_via_host` call routed through
    the daemon's NDJSON loop instead of a per-call
    `dotnet run` subprocess.

    The fixture skips cleanly when the prereqs that the
    one-shot Phase 5c tests already check are missing
    (config not loadable, `.NET SDK` absent, ParityHost DLL
    not built, sqlite not built). That mirrors the
    same-test behaviour: tests declaring the fixture skip
    instead of fail when local infra isn't there.

    Yields the daemon for callers that want to use the
    explicit `daemon.invoke(...)` API; tests that only want
    the routing don't have to do anything with it.
    """
    try:
        from cbdb_parity.config import load_config
    except ImportError:
        pytest.skip("cbdb_parity.config not importable")
    try:
        cfg = load_config()
    except FileNotFoundError as exc:
        pytest.skip(f"config not configured: {exc}")

    if not (shutil.which("dotnet") or Path(r"C:\Program Files\dotnet\dotnet.exe").is_file()):
        pytest.skip(".NET SDK not installed")
    repo_root = Path(__file__).resolve().parent.parent
    host_dll = (
        repo_root / "parity_host" / "Cbdb.App.ParityHost"
        / "bin" / "Debug" / "net8.0" / "cbdb-parity-host.dll"
    )
    if not host_dll.is_file():
        pytest.skip("ParityHost DLL not built")

    from cbdb_parity.parity_host import ParityHostDaemon, bind_active_daemon

    with ParityHostDaemon(avalonia_repo=cfg.avalonia_repo) as daemon:
        with bind_active_daemon(daemon):
            yield daemon
