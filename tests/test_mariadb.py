"""Tests for cbdb_parity.mariadb — Phase 1.6 intermediate cache layer.

These tests stub pymysql / subprocess / tarfile so they exercise the
control flow (cache-hit, cache-miss, force-reimport, container down,
provenance read/write) without touching a real Docker container or
Datadump archive. End-to-end against the real container is done by
the user invoking `cbdb-parity-import-mariadb` after these pass.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cbdb_parity import mariadb as mdb_mod
from cbdb_parity.config import Config, MariaDbConfig
from cbdb_parity.datadump import DatadumpInfo
from cbdb_parity.mariadb import (
    MariaDbError,
    _build_mysql_cli_cmd,
    _require_mariadb_cfg,
    ensure_container_running,
    ensure_imported,
)


def _mariadb_cfg(**over: Any) -> MariaDbConfig:
    base = dict(
        host="localhost", port=3306, user="root", password="pw",
        database="cbdb_data", container_name="cbdb-parity-mariadb",
        force_reimport=False, auto_launch=False,
    )
    base.update(over)
    return MariaDbConfig(**base)  # type: ignore[arg-type]


def _config_with_mariadb(tmp_path: Path, **mdb_over: Any) -> Config:
    base = tmp_path / "base"
    base.mkdir()
    for sub in ("d", "a", "v", "o", "x", "y", "b"):
        (base / sub).mkdir()
    (base / "a" / ".git").mkdir()
    (base / "v" / ".git").mkdir()
    (base / "o" / ".git").mkdir()
    (base / "x" / ".git").mkdir()
    user_mdb = base / "u.mdb"
    user_mdb.write_bytes(b"")
    return Config(
        datadump_dir=base / "d",
        cbdb_user_mdb=user_mdb,
        access_tests_repo=base / "a",
        avalonia_repo=base / "v",
        online_server_repo=base / "o",
        access_mysql_transfer_repo=base / "x",
        mysql2access_dir=base / "y",
        build_output_dir=base / "b",
        mariadb=_mariadb_cfg(**mdb_over),
    )


def _datadump_info(tmp_path: Path, sha: str = "a" * 64) -> DatadumpInfo:
    """Synthetic DatadumpInfo whose sha256 returns a fixed value.

    The real archive isn't read by the tests below — they stub the
    import path. The .path attribute just needs to be a real file so
    the lazy sha256 attribute can be replaced via monkeypatch.
    """
    archive = tmp_path / "cbdb_data_20260101.tar.gz"
    # Create a minimal tar.gz containing one empty `cbdb_data.sql`
    # member so any test that does walk the tar finds it.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        sql = b"-- empty test dump\n"
        ti = tarfile.TarInfo(name="cbdb_data.sql")
        ti.size = len(sql)
        tar.addfile(ti, io.BytesIO(sql))
    archive.write_bytes(buf.getvalue())
    info = DatadumpInfo(path=archive, date_tag="20260101")
    # DatadumpInfo.sha256 re-hashes the file each call; monkeypatch the
    # PROPERTY (not the instance) so it returns our synthetic SHA.
    return info


class _FakeCursor:
    def __init__(self, owner: _FakeConnection) -> None:
        self.owner = owner
        self._last_rows: list[tuple[Any, ...]] = []
        self.executed: list[str] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append(sql)
        self.owner._executed.append((sql, params))
        s = sql.strip().upper()
        if s.startswith("SELECT DATADUMP_SHA"):
            if self.owner._provenance is None:
                self._last_rows = []
            else:
                # Real SELECT picks (datadump_sha, imported_at) — only
                # those two columns. The fake stores the full row
                # (sha, filename, ts) so the INSERT params line up;
                # project here to match the production projection.
                sha, _filename, imported_at = self.owner._provenance
                self._last_rows = [(sha, imported_at)]
        elif s.startswith("DELETE FROM"):
            self.owner._provenance = None
        elif s.startswith("INSERT INTO"):
            assert params is not None
            self.owner._provenance = tuple(params)  # type: ignore[assignment]
        # SHOW / CREATE / DROP statements are no-ops for the fake.

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._last_rows[0] if self._last_rows else None


class _FakeConnection:
    """Minimal pymysql-like stub used by mariadb tests."""

    def __init__(self) -> None:
        self._provenance: tuple[str, str, datetime] | None = None
        self._executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_pymysql(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace `_connect()` so it returns shared `_FakeConnection` instances.

    The fake remembers the in-DB provenance row across opens of the
    same database so cache-hit logic can be exercised end-to-end.
    """
    state: dict[str, _FakeConnection] = {}

    def fake_connect(mdb: MariaDbConfig, *, database: str | None) -> _FakeConnection:
        key = database or "<server>"
        if key not in state:
            state[key] = _FakeConnection()
        # pymysql is autocommit=True in mariadb._connect so the cached
        # FakeConnection's state survives close() — emulate that here.
        return state[key]

    monkeypatch.setattr(mdb_mod, "_connect", fake_connect)
    return state


# --- ensure_container_running -------------------------------------------------

def test_container_running_no_op_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mdb_mod, "_resolves_to_local_machine", lambda host: True)
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: "running")
    ensure_container_running(_mariadb_cfg())  # no raise, no docker calls


def test_container_running_raises_when_stopped_without_auto_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stopped LOCAL container raises even though `docker port` (which
    would skip stopped containers) is not consulted here — the
    existence + state check is sufficient to fire the auto-launch /
    guidance branch."""
    monkeypatch.setattr(mdb_mod, "_resolves_to_local_machine", lambda host: True)
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: "exited")
    with pytest.raises(MariaDbError, match="not running"):
        ensure_container_running(_mariadb_cfg(auto_launch=False))


def test_container_running_skips_when_docker_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No docker on PATH (or no such container) → don't error, let the
    eventual connection attempt surface the issue."""
    monkeypatch.setattr(mdb_mod, "_resolves_to_local_machine", lambda host: True)
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: None)
    ensure_container_running(_mariadb_cfg())


def test_container_check_skipped_for_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stopped local container with the same name must NOT block a
    configured remote MariaDB endpoint."""
    monkeypatch.setattr(mdb_mod, "_resolves_to_local_machine", lambda host: False)
    # Even if the container is stopped, the helper should return cleanly
    # because the configured host isn't local to this machine.
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: "exited")
    ensure_container_running(_mariadb_cfg(host="db.elsewhere.example"))


# --- _require_mariadb_cfg -----------------------------------------------------

def test_require_mariadb_cfg_raises_when_absent(tmp_path: Path) -> None:
    """A Config without MariaDB raises with a clear actionable hint."""
    cfg = _config_with_mariadb(tmp_path)
    cfg_no_mariadb = type(cfg)(
        datadump_dir=cfg.datadump_dir,
        cbdb_user_mdb=cfg.cbdb_user_mdb,
        access_tests_repo=cfg.access_tests_repo,
        avalonia_repo=cfg.avalonia_repo,
        online_server_repo=cfg.online_server_repo,
        access_mysql_transfer_repo=cfg.access_mysql_transfer_repo,
        mysql2access_dir=cfg.mysql2access_dir,
        build_output_dir=cfg.build_output_dir,
        mariadb=None,
    )
    with pytest.raises(MariaDbError, match="not configured"):
        _require_mariadb_cfg(cfg_no_mariadb)


# --- _build_mysql_cli_cmd -----------------------------------------------------

def test_cli_cmd_prefers_docker_exec_when_endpoint_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docker-exec wins only when host is local AND container's port maps."""
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: "running")
    monkeypatch.setattr(
        mdb_mod, "_container_targets_configured_endpoint", lambda mdb: True
    )
    cmd = _build_mysql_cli_cmd(_mariadb_cfg(container_name="my-mariadb"))
    assert cmd[:4] == ["docker", "exec", "-i", "my-mariadb"]
    assert cmd[4] == "mysql"
    # docker-exec path uses container-internal port 3306, not host port.
    assert "-h" in cmd and cmd[cmd.index("-h") + 1] == "127.0.0.1"


def test_cli_cmd_does_not_use_docker_exec_when_remote_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P1: a remote MARIADB_HOST + a local container with the
    SAME name must NOT trick us into docker-exec'ing the wrong server."""
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: "running")
    # _container_targets_configured_endpoint must refuse when host is
    # not local — simulate that here with a fake that respects the host.
    monkeypatch.setattr(
        mdb_mod, "_container_targets_configured_endpoint",
        lambda mdb: mdb.host in {"localhost", "127.0.0.1", "::1"},
    )
    cmd = _build_mysql_cli_cmd(_mariadb_cfg(host="db.elsewhere.example"))
    assert cmd[0] == "mysql"  # host mysql path, NOT docker exec
    assert "-h" in cmd and cmd[cmd.index("-h") + 1] == "db.elsewhere.example"


def test_cli_cmd_falls_back_to_host_mysql_when_no_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda binary: "/usr/bin/mysql" if binary == "mysql" else None,
    )
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: None)
    monkeypatch.setattr(
        mdb_mod, "_container_targets_configured_endpoint", lambda mdb: False
    )
    cmd = _build_mysql_cli_cmd(_mariadb_cfg(host="db.host", port=3307))
    assert cmd[0] == "mysql"
    assert "-h" in cmd and cmd[cmd.index("-h") + 1] == "db.host"
    assert "-P" in cmd and cmd[cmd.index("-P") + 1] == "3307"


def test_cli_cmd_raises_when_no_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda binary: None)
    monkeypatch.setattr(mdb_mod, "_container_state", lambda name: None)
    monkeypatch.setattr(
        mdb_mod, "_container_targets_configured_endpoint", lambda mdb: False
    )
    with pytest.raises(MariaDbError, match="No `mysql` CLI"):
        _build_mysql_cli_cmd(_mariadb_cfg())


def test_read_cached_sha_re_raises_on_non_missing_table_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P2: a real DB error (not the 1146 missing-table case) must
    propagate, NOT be silently treated as a cache miss."""
    import pymysql

    class _ExplodingCursor:
        def __enter__(self) -> _ExplodingCursor:
            return self
        def __exit__(self, *exc: Any) -> None:
            pass
        def execute(self, *_a: Any, **_kw: Any) -> None:
            # Code 1142: permission denied — typical real-world fault.
            raise pymysql.err.ProgrammingError(1142, "permission denied")
        def fetchone(self) -> Any:
            return None

    class _Conn:
        def cursor(self) -> _ExplodingCursor:
            return _ExplodingCursor()

    with pytest.raises(pymysql.err.ProgrammingError):
        mdb_mod._read_cached_sha(_Conn())


def test_read_cached_sha_returns_none_on_missing_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1146 = table doesn't exist → treat as fresh cache (None)."""
    import pymysql

    class _MissingTableCursor:
        def __enter__(self) -> _MissingTableCursor:
            return self
        def __exit__(self, *exc: Any) -> None:
            pass
        def execute(self, *_a: Any, **_kw: Any) -> None:
            raise pymysql.err.ProgrammingError(1146, "no such table")
        def fetchone(self) -> Any:
            return None

    class _Conn:
        def cursor(self) -> _MissingTableCursor:
            return _MissingTableCursor()

    assert mdb_mod._read_cached_sha(_Conn()) is None


# --- ensure_imported (control flow) ------------------------------------------

def _patch_sha(monkeypatch: pytest.MonkeyPatch, sha: str) -> None:
    """Override DatadumpInfo.sha256 to return a fixed value across calls."""
    monkeypatch.setattr(DatadumpInfo, "sha256", property(lambda self: sha))


def test_ensure_imported_cache_hit_skips_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_pymysql: dict[str, _FakeConnection],
) -> None:
    """When the in-DB provenance row matches the Datadump SHA, no
    `mysql` CLI call is issued."""
    cfg = _config_with_mariadb(tmp_path)
    info = _datadump_info(tmp_path)
    _patch_sha(monkeypatch, "b" * 64)
    monkeypatch.setattr(mdb_mod, "ensure_container_running", lambda mdb: None)

    # Seed the fake "DB" with a matching provenance row BEFORE invoking
    # ensure_imported so it reads back as a cache hit.
    db_fake = _FakeConnection()
    db_fake._provenance = ("b" * 64, "cbdb_data_20260101.tar.gz", datetime.now(UTC))
    fake_pymysql["cbdb_data"] = db_fake

    cli_called = {"yes": False}
    def _explode_if_called(*_a: Any, **_kw: Any) -> None:
        cli_called["yes"] = True
        raise AssertionError("import should NOT have been invoked on cache hit")
    monkeypatch.setattr(mdb_mod, "_import_via_mysql_cli", _explode_if_called)

    status = ensure_imported(cfg, info)
    assert status.reused is True
    assert status.datadump_sha == "b" * 64
    assert cli_called["yes"] is False


def test_ensure_imported_force_reimport_drops_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_pymysql: dict[str, _FakeConnection],
) -> None:
    """`force_reimport=True` re-runs the import even if the SHA matches."""
    cfg = _config_with_mariadb(tmp_path, force_reimport=True)
    info = _datadump_info(tmp_path)
    _patch_sha(monkeypatch, "c" * 64)
    monkeypatch.setattr(mdb_mod, "ensure_container_running", lambda mdb: None)

    db_fake = _FakeConnection()
    db_fake._provenance = ("c" * 64, "any.tar.gz", datetime.now(UTC))
    fake_pymysql["cbdb_data"] = db_fake

    imports: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        mdb_mod, "_import_via_mysql_cli",
        lambda mdb, info: imports.append((mdb, info)),
    )

    status = ensure_imported(cfg, info)
    assert status.reused is False
    assert len(imports) == 1, "import must run when force_reimport=True"
    # Provenance got rewritten to the new SHA.
    assert db_fake._provenance is not None
    assert db_fake._provenance[0] == "c" * 64


def test_ensure_imported_cache_miss_runs_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_pymysql: dict[str, _FakeConnection],
) -> None:
    """SHA mismatch → drop + re-import + provenance row updated."""
    cfg = _config_with_mariadb(tmp_path)
    info = _datadump_info(tmp_path)
    _patch_sha(monkeypatch, "d" * 64)
    monkeypatch.setattr(mdb_mod, "ensure_container_running", lambda mdb: None)

    # Existing provenance is for a different SHA.
    db_fake = _FakeConnection()
    db_fake._provenance = ("stale" * 12 + "----", "old.tar.gz", datetime.now(UTC))
    fake_pymysql["cbdb_data"] = db_fake

    monkeypatch.setattr(mdb_mod, "_import_via_mysql_cli", lambda mdb, info: None)

    status = ensure_imported(cfg, info)
    assert status.reused is False
    assert db_fake._provenance is not None
    assert db_fake._provenance[0] == "d" * 64


def test_ensure_imported_empty_cache_runs_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_pymysql: dict[str, _FakeConnection],
) -> None:
    """First-ever run: empty provenance table → import + write row."""
    cfg = _config_with_mariadb(tmp_path)
    info = _datadump_info(tmp_path)
    _patch_sha(monkeypatch, "e" * 64)
    monkeypatch.setattr(mdb_mod, "ensure_container_running", lambda mdb: None)
    monkeypatch.setattr(mdb_mod, "_import_via_mysql_cli", lambda mdb, info: None)

    status = ensure_imported(cfg, info)
    assert status.reused is False
    db_fake = fake_pymysql["cbdb_data"]
    assert db_fake._provenance is not None
    assert db_fake._provenance[0] == "e" * 64


def test_ensure_imported_subprocess_failure_propagates_as_mariadberror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_pymysql: dict[str, _FakeConnection],
) -> None:
    """An import failure (mysql CLI rc != 0) surfaces as MariaDbError —
    no half-written provenance row left behind."""
    cfg = _config_with_mariadb(tmp_path)
    info = _datadump_info(tmp_path)
    _patch_sha(monkeypatch, "f" * 64)
    monkeypatch.setattr(mdb_mod, "ensure_container_running", lambda mdb: None)

    def boom(mdb: Any, info: Any) -> None:
        raise MariaDbError("mysql CLI exited rc=1; stderr=...")
    monkeypatch.setattr(mdb_mod, "_import_via_mysql_cli", boom)

    with pytest.raises(MariaDbError, match="mysql CLI"):
        ensure_imported(cfg, info)
    # The DB-level provenance row must NOT have been updated to the
    # broken SHA — callers see the import failed and try again.
    db_fake = fake_pymysql.get("cbdb_data")
    if db_fake is not None and db_fake._provenance is not None:
        assert db_fake._provenance[0] != "f" * 64


# --- mismatched CLI args / docker plumbing -----------------------------------

def test_container_state_returns_none_when_docker_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `docker` on PATH → _container_state returns None, doesn't raise."""
    monkeypatch.setattr("shutil.which", lambda binary: None)
    assert mdb_mod._container_state("anything") is None


def test_container_state_parses_docker_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """When `docker inspect` succeeds, the trimmed stdout is returned."""
    monkeypatch.setattr("shutil.which", lambda binary: "/usr/bin/docker")

    class _Done:
        returncode = 0
        stdout = "running\n"
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Done())
    assert mdb_mod._container_state("c") == "running"
