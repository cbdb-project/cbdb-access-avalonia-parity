"""Pytest fixtures shared across the harness test suite."""

from __future__ import annotations

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
