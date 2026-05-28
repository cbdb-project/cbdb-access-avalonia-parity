"""Tests for cbdb_parity.build_all — the Phase 1.4 orchestrator."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from cbdb_parity import build_all as ba_mod
from cbdb_parity.build_all import build_all, cli_main
from cbdb_parity.config import ConfigError
from cbdb_parity.datadump import DatadumpError, DatadumpInfo
from cbdb_parity.refresh import RefreshError, RefreshResult


@pytest.fixture
def fake_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Patch the orchestrator's dependencies so it can run without touching
    the real .env, real Datadumps, or the real network.

    Returns the path to the fake manifest file."""
    fake_archive = tmp_path / "cbdb_data_20260101.tar.gz"
    fake_archive.write_bytes(b"unused - open_dump_stream is patched")
    fake_info = DatadumpInfo(path=fake_archive, date_tag="20260101")
    build_dir = tmp_path / "build"
    build_dir.mkdir()

    class _Cfg:
        datadump_dir = tmp_path
        build_output_dir = build_dir
        access_mysql_transfer_repo = tmp_path  # xlsx loader is patched out
        # Phase 1.6: mariadb=None keeps the orchestrator on the
        # Datadump-direct path that these tests are written against.
        # Tests that exercise MariaDB explicitly set this to a real
        # MariaDbConfig and patch `ensure_imported`.
        mariadb = None
        # Phase 1.6 added use_cache as the top-tier USE_CACHE switch.
        # Tests here cover the FULL pipeline path; set to False so the
        # short-circuit doesn't swallow them.
        use_cache = False

    monkeypatch.setattr(ba_mod, "load_config", lambda: _Cfg())
    monkeypatch.setattr(ba_mod, "find_latest_datadump", lambda _: fake_info)
    monkeypatch.setattr(ba_mod, "refresh_all", lambda _cfg: [])
    # mdb builder needs an AccessSchema from disk; fake out the loader.
    from cbdb_parity.access_schema import AccessSchema
    monkeypatch.setattr(ba_mod, "load_access_schema", lambda _path: AccessSchema())

    # Patch DatadumpInfo.sha256 to a deterministic value without re-hashing
    # the empty archive bytes (which would give a real SHA we'd then have
    # to hard-code; avoid the dance).
    monkeypatch.setattr(
        type(fake_info),
        "sha256",
        property(lambda self: "deadbeef" * 8),
    )

    # Patch the dump stream + the actual builder.
    def fake_open(_info):
        class _Ctx:
            def __enter__(self) -> io.BytesIO:
                return io.BytesIO(b"")
            def __exit__(self, *_a: object) -> None:
                pass
        return _Ctx()
    monkeypatch.setattr(ba_mod, "open_dump_stream", fake_open)

    from cbdb_parity.sqlite_builder import BuildStats as SqliteStats

    def fake_build(stream, out_path, **_kw):
        out_path.touch()
        return SqliteStats(tables_created=2, rows_inserted=5, tables_skipped=["CBDB__x"])

    monkeypatch.setattr(ba_mod, "build_sqlite", fake_build)

    # mdb builder fake: same shape, different stat class but tests only
    # check via the manifest's product entries.
    from cbdb_parity.mdb_builder import BuildStats as MdbStats

    def fake_build_mdb(stream, out_path, **_kw):
        out_path.touch()
        return MdbStats(tables_created=3, rows_inserted=7, tables_skipped=["CBDB__y"])

    monkeypatch.setattr(ba_mod, "build_mdb", fake_build_mdb)

    # Manifest path comes from `_manifest_path()` which uses
    # find_dotenv(usecwd=True). Patch it for tests so we don't depend on
    # the real .env discovery.
    manifest = tmp_path / "build_manifest.json"
    monkeypatch.setattr(ba_mod, "_manifest_path", lambda: manifest)
    return manifest


def test_build_all_writes_manifest_with_datadump_and_product(
    fake_pipeline: Path,
) -> None:
    rc = build_all()
    assert rc == 0
    assert fake_pipeline.exists()
    payload = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["datadump"]["sha256"] == "deadbeef" * 8
    assert payload["datadump"]["date_tag"] == "20260101"
    assert "sqlite" in payload["products"]
    assert payload["products"]["sqlite"]["rows_inserted"] == 5


def test_build_all_caches_when_sha_matches(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A second invocation must NOT re-run build_sqlite when the
    manifest already records the same SHA AND the output file exists."""
    rc1 = build_all()
    assert rc1 == 0
    # Track second-build invocations.
    calls: list[Path] = []
    real_build = ba_mod.build_sqlite

    def counting_build(stream, out_path, **kw):
        calls.append(out_path)
        return real_build(stream, out_path, **kw)

    monkeypatch.setattr(ba_mod, "build_sqlite", counting_build)
    rc2 = build_all()
    out = capsys.readouterr().out
    assert rc2 == 0
    assert calls == []  # not invoked on second run
    assert "[cached]" in out


def test_build_all_rebuild_flag_forces_rebuild(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc1 = build_all()
    assert rc1 == 0
    calls: list[Path] = []
    real_build = ba_mod.build_sqlite

    def counting_build(stream, out_path, **kw):
        calls.append(out_path)
        return real_build(stream, out_path, **kw)

    monkeypatch.setattr(ba_mod, "build_sqlite", counting_build)
    rc2 = build_all(rebuild=True)
    assert rc2 == 0
    assert len(calls) == 1  # rebuilt despite SHA match


def test_build_all_config_error_returns_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> object:
        raise ConfigError(".env not found")
    monkeypatch.setattr(ba_mod, "load_config", boom)
    rc = build_all()
    assert rc == 2


def test_build_all_datadump_error_returns_2(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_):
        raise DatadumpError("no archives")
    monkeypatch.setattr(ba_mod, "find_latest_datadump", boom)
    rc = build_all()
    assert rc == 2


def test_build_all_refresh_error_returns_1(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_):
        raise RefreshError("git pull failed", [])
    monkeypatch.setattr(ba_mod, "refresh_all", boom)
    rc = build_all()
    assert rc == 1


def test_build_all_preserves_same_sha_sibling_products_on_success(
    fake_pipeline: Path,
    tmp_path: Path,
) -> None:
    """If the existing manifest has the SAME SHA and a sibling product
    (e.g. mdb built earlier) AND the sibling file still exists at a
    path under the current BUILD_OUTPUT_DIR, a successful sqlite-only
    run must KEEP that sibling rather than silently overwriting the
    whole products block."""
    # Sibling lives in the current BUILD_OUTPUT_DIR with a real file.
    mdb_path = tmp_path / "build" / "cbdb_data.mdb"
    mdb_path.write_bytes(b"fake mdb")

    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {
            # Include builder_version so this counts as a same-builder
            # cache entry — without it the new (1.6c) builder-version
            # gate would invalidate and rebuild.
            "mdb": {
                "path": str(mdb_path),
                "rows_inserted": 12345,
                "builder_version": "1.3b-mysqldump-parser-overlay",
            },
        },
    }), encoding="utf-8")

    rc = build_all()
    assert rc == 0
    payload = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    # Both products present, both anchored to the same SHA.
    assert set(payload["products"]) == {"sqlite", "mdb"}
    assert payload["products"]["mdb"]["rows_inserted"] == 12345


def test_build_all_drops_sibling_when_path_outside_build_dir(
    fake_pipeline: Path,
    tmp_path: Path,
) -> None:
    """A sibling product whose recorded path is NOT under the current
    BUILD_OUTPUT_DIR (e.g. BUILD_OUTPUT_DIR was changed since the
    sibling build) must be dropped — its file is somewhere else, possibly
    gone."""
    # Sibling references a path outside the current build dir.
    stale_path = tmp_path / "other-dir" / "cbdb_data.mdb"
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {"mdb": {"path": str(stale_path), "rows_inserted": 12345}},
    }), encoding="utf-8")

    rc = build_all()
    assert rc == 0
    payload = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    # The stale-path mdb entry is dropped; a freshly-built mdb at the
    # current BUILD_OUTPUT_DIR replaces it.
    assert set(payload["products"]) == {"sqlite", "mdb"}
    assert payload["products"]["mdb"]["rows_inserted"] == 7  # the fake mdb's rowcount


def test_build_all_drops_sibling_when_file_missing(
    fake_pipeline: Path,
    tmp_path: Path,
) -> None:
    """Sibling under build dir but the actual file is gone — drop it."""
    missing = tmp_path / "build" / "cbdb_data.mdb"  # no write
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {"mdb": {"path": str(missing), "rows_inserted": 12345}},
    }), encoding="utf-8")

    rc = build_all()
    assert rc == 0
    payload = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    # Stale sibling dropped; freshly-built mdb takes its place.
    assert set(payload["products"]) == {"sqlite", "mdb"}


def test_build_all_sha_hash_failure_returns_1(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If hashing the archive fails (file deleted/locked mid-run), the
    CLI returns 1 with a clear message instead of crashing."""
    from cbdb_parity.datadump import DatadumpInfo

    def boom(self):
        raise OSError(13, "Permission denied", "archive.tar.gz")

    monkeypatch.setattr(DatadumpInfo, "sha256", property(boom))
    rc = build_all()
    assert rc == 1


def test_build_all_manifest_write_failure_returns_1(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the manifest write fails after a successful build, the CLI must
    return 1 and emit a clear message — NOT crash with a traceback."""
    def boom(*_args, **_kw):
        raise OSError(13, "Permission denied", "manifest.json")
    monkeypatch.setattr(ba_mod, "_write_manifest", boom)

    rc = build_all()
    assert rc == 1


def test_build_all_preserves_good_artifact_on_pre_build_failure(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If a rebuild fails BEFORE build_sqlite is even entered (e.g.
    open_dump_stream rejects the archive), the prior cbdb.sqlite is
    untouched and must NOT be deleted by the failure handler."""
    # Seed a "good" prior cbdb.sqlite.
    good = tmp_path / "build" / "cbdb.sqlite"
    good.write_bytes(b"PRIOR_GOOD")

    # Make open_dump_stream fail before build_sqlite can run.
    def boom(_info):
        raise DatadumpError("archive corrupt")
    monkeypatch.setattr(ba_mod, "open_dump_stream", boom)

    rc = build_all(rebuild=True)
    assert rc == 1
    # The good prior db must still be there.
    assert good.exists()
    assert good.read_bytes() == b"PRIOR_GOOD"


def test_load_manifest_treats_non_object_json_as_empty(tmp_path: Path) -> None:
    """A manifest with valid-but-non-object JSON (e.g. `[]` left by hand
    editing) must not crash the cache check; treat it as empty."""
    import json as _json

    from cbdb_parity.build_all import _load_manifest

    bad = tmp_path / "build_manifest.json"
    bad.write_text(_json.dumps([1, 2, 3]), encoding="utf-8")
    assert _load_manifest(bad) == {}
    bad.write_text(_json.dumps("a string"), encoding="utf-8")
    assert _load_manifest(bad) == {}
    bad.write_text(_json.dumps(42), encoding="utf-8")
    assert _load_manifest(bad) == {}


def test_build_all_strips_mdb_entry_when_mdb_rebuild_fails(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed mdb rebuild must remove the mdb entry from the manifest
    too — leaving it dangling would let a later run treat the (deleted/
    partial) mdb as a valid cached product."""
    # First, a successful run so the manifest has both products.
    rc1 = build_all()
    assert rc1 == 0
    payload_before = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    assert "mdb" in payload_before["products"]

    # Now force the mdb rebuild to fail.
    def failing_mdb(stream, out_path, *, on_started=None, **_kw):
        # Real build_mdb fires on_started immediately after the prior
        # file is unlinked and before win_create_mdb runs — i.e. once
        # the destination is in a "partial / unknown" state. A fake that
        # writes a partial output crosses the same boundary, so it must
        # fire the callback before raising or the orchestrator will
        # treat the file as untouched and skip cleanup.
        if on_started is not None:
            on_started()
        out_path.write_bytes(b"\x00" * 32)  # simulate a partial mdb
        raise RuntimeError("simulated mdb mid-build failure")

    monkeypatch.setattr(ba_mod, "build_mdb", failing_mdb)
    rc2 = build_all(rebuild=True)
    assert rc2 == 1

    # Partial mdb is gone.
    mdb_path = tmp_path / "build" / "cbdb_data.mdb"
    assert not mdb_path.exists()
    # Manifest stripped mdb entry (and sqlite too, since the failure
    # handler clears both same-SHA build targets).
    payload_after = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    assert "mdb" not in payload_after.get("products", {})


def test_build_all_drops_stale_siblings_on_sha_change_then_failure(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the existing manifest is for an OLDER SHA and contains other
    products, a failed sqlite rebuild must NOT stamp those stale products
    with the new SHA — drop the whole products block."""
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "old.tar.gz", "sha256": "oldsha", "date_tag": "20251201"},
        "products": {"mdb": {"path": "/x/old.mdb", "rows_inserted": 888}},
    }), encoding="utf-8")

    def failing_build(stream, out_path, **_kw):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(ba_mod, "build_sqlite", failing_build)

    rc = build_all()
    assert rc == 1
    payload = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    # Manifest now reflects the NEW SHA, but products is EMPTY (old mdb
    # came from an old SHA — we have no proof it matches the new dump).
    assert payload["datadump"]["sha256"] == "deadbeef" * 8
    assert payload.get("products", {}) == {}


def test_build_all_unlinks_partial_output_on_failure(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed rebuild leaves NO partial sqlite + NO stale manifest entry
    behind — so the next run rebuilds cleanly instead of mistaking a
    half-finished file for a complete cache entry."""
    # First, a successful build.
    rc1 = build_all()
    assert rc1 == 0
    sqlite_path = tmp_path / "build" / "cbdb.sqlite"
    assert sqlite_path.exists()

    # Now force a rebuild that will fail mid-stream.
    def failing_build(stream, out_path, *, on_started=None, **_kw):
        # Mirror real build_sqlite: fire on_started once the destructive
        # overwrite is committed (before laying down the new file). The
        # partial-write below stands in for what a mid-stream failure
        # leaves behind, and the callback is what arms the orchestrator
        # to clean it up.
        if on_started is not None:
            on_started()
        out_path.write_bytes(b"\x00" * 32)
        raise RuntimeError("simulated mid-build failure")

    monkeypatch.setattr(ba_mod, "build_sqlite", failing_build)
    rc2 = build_all(rebuild=True)
    assert rc2 == 1

    # Partial output must be gone.
    assert not sqlite_path.exists()
    # Stale sqlite entry must be cleared from manifest.
    payload = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    assert "sqlite" not in payload.get("products", {})


def test_build_all_preserves_artifact_on_pre_destructive_failure(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A builder that raises BEFORE crossing the destructive overwrite
    boundary (i.e. before firing on_started) must NOT trigger cleanup —
    the prior good file and its manifest entry stay intact."""
    # Successful baseline run.
    rc1 = build_all()
    assert rc1 == 0
    sqlite_path = tmp_path / "build" / "cbdb.sqlite"
    assert sqlite_path.is_file()
    baseline_bytes = sqlite_path.read_bytes()
    payload_before = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    assert "sqlite" in payload_before["products"]

    # Force a "pre-destructive" failure: the fake raises BEFORE firing
    # on_started, mirroring e.g. a sqlite3.connect that errored before
    # unlinking the previous file. Real build_sqlite fires on_started
    # right after the unlink, so a failure before that boundary leaves
    # the prior artifact untouched.
    def pre_destructive_fail(stream, out_path, *, on_started=None, **_kw):
        raise RuntimeError("simulated pre-destructive failure")

    monkeypatch.setattr(ba_mod, "build_sqlite", pre_destructive_fail)
    rc2 = build_all(rebuild=True)
    assert rc2 == 1

    # Prior file untouched.
    assert sqlite_path.is_file()
    assert sqlite_path.read_bytes() == baseline_bytes
    # Prior manifest entry preserved (its provenance is still valid).
    payload_after = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    assert payload_after.get("products", {}).get("sqlite") == \
        payload_before["products"]["sqlite"]


def test_build_all_does_not_use_cache_when_output_path_changed(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Same Datadump SHA but the BUILD_OUTPUT_DIR has changed since the
    previous build → must rebuild, otherwise the manifest would record
    the old path while the new target stays unbuilt."""
    # First build at the original location.
    rc1 = build_all()
    assert rc1 == 0

    # Now point BUILD_OUTPUT_DIR at a different folder; same SHA.
    new_build_dir = tmp_path / "different-build-dir"
    new_build_dir.mkdir()

    class _AltCfg:
        datadump_dir = tmp_path
        build_output_dir = new_build_dir
        access_mysql_transfer_repo = tmp_path
        mariadb = None
        use_cache = False

    monkeypatch.setattr(ba_mod, "load_config", lambda: _AltCfg())

    # Count whether build_sqlite gets called.
    calls = []
    real_build = ba_mod.build_sqlite

    def counting_build(stream, out_path, **kw):
        calls.append(out_path)
        return real_build(stream, out_path, **kw)

    monkeypatch.setattr(ba_mod, "build_sqlite", counting_build)

    rc2 = build_all()
    assert rc2 == 0
    # Must NOT be cached: output path differs, so we rebuild.
    assert len(calls) == 1
    assert calls[0] == new_build_dir / "cbdb.sqlite"


def test_build_all_datadump_streaming_error_returns_1(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed archive that passes the filename-shape check but fails
    at streaming time (e.g. missing cbdb_data.sql member) reaches the
    orchestrator as a DatadumpError; must surface as exit code 1, not a
    bare traceback."""
    def boom(_info):
        raise DatadumpError("expected member 'cbdb_data.sql' not in archive")
    monkeypatch.setattr(ba_mod, "open_dump_stream", boom)
    rc = build_all()
    assert rc == 1


def test_build_all_always_refreshes(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per AGENTS.md, the refresh gate is mandatory — there is no skip
    option. Every build_all call must invoke refresh_all."""
    calls = []
    monkeypatch.setattr(ba_mod, "refresh_all", lambda _: calls.append(_) or [])
    rc = build_all()
    assert rc == 0
    assert len(calls) == 1


def test_build_all_clears_stale_products_on_sha_change(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A previous build for SHA-A leaves products in the manifest.
    A new build for SHA-B must publish only the new build's product set;
    no leftover stale entry from SHA-A's products."""
    # Seed manifest with a previous build's product entry.
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "old.tar.gz", "sha256": "oldsha", "date_tag": "20251201"},
        "products": {
            "sqlite": {"path": "/x/old.sqlite", "rows_inserted": 999},
            "mdb": {"path": "/x/old.mdb", "rows_inserted": 888},  # from hypothetical 1.3b
        },
    }), encoding="utf-8")

    rc = build_all()
    assert rc == 0
    payload = json.loads(fake_pipeline.read_text(encoding="utf-8"))
    assert payload["datadump"]["sha256"] == "deadbeef" * 8
    # Both sqlite and mdb were rebuilt from the new SHA; the OLD stale
    # mdb entry (rows_inserted=999 from the seeded oldsha) is gone,
    # replaced by the new mdb fake (rows_inserted=7).
    assert set(payload["products"]) == {"sqlite", "mdb"}
    assert payload["products"]["sqlite"]["rows_inserted"] == 5
    assert payload["products"]["mdb"]["rows_inserted"] == 7
    # Sanity: not the stale "rows_inserted: 999" we seeded.
    assert payload["products"]["mdb"]["rows_inserted"] != 999


def test_cli_main_passes_rebuild_flag(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def captured(*, rebuild: bool) -> int:
        seen["rebuild"] = rebuild
        return 0

    monkeypatch.setattr(ba_mod, "build_all", captured)
    rc = cli_main(["--rebuild"])
    assert rc == 0
    assert seen == {"rebuild": True}


def test_cli_main_default_rebuild_false(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    def captured(*, rebuild: bool) -> int:
        seen["rebuild"] = rebuild
        return 0

    monkeypatch.setattr(ba_mod, "build_all", captured)
    rc = cli_main([])
    assert rc == 0
    assert seen == {"rebuild": False}


def test_refresh_all_succeeds_with_results(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(ba_mod, "refresh_all", lambda _cfg: [
        RefreshResult("ACCESS_TESTS_REPO", Path("/x/a"), True, "aaa", "aaa", "Already up to date."),
        RefreshResult("AVALONIA_REPO", Path("/x/b"), True, "aaa", "bbb", "Fast-forwarded."),
    ])
    rc = build_all()
    out = capsys.readouterr().out
    assert rc == 0
    assert "[up-to-date] ACCESS_TESTS_REPO" in out
    assert "[updated] AVALONIA_REPO" in out


def test_build_all_uses_mariadb_when_configured(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When `cfg.mariadb` is populated, the orchestrator calls
    `mariadb.ensure_imported(cfg, info)` BEFORE the builders and passes
    `source='mariadb'` down. The Datadump-direct path is bypassed."""
    from cbdb_parity.config import MariaDbConfig
    from cbdb_parity.mariadb import CacheStatus

    # Reconfigure the fake load_config to return a config WITH mariadb set.
    mariadb_cfg = MariaDbConfig(
        host="localhost", port=3306, user="root", password="x",
        database="cbdb_data", container_name="x",
        force_reimport=False, auto_launch=False,
    )

    class _CfgWithMariadb:
        datadump_dir = fake_pipeline.parent
        build_output_dir = fake_pipeline.parent / "build"
        access_mysql_transfer_repo = fake_pipeline.parent
        mariadb = mariadb_cfg
        use_cache = False

    monkeypatch.setattr(ba_mod, "load_config", lambda: _CfgWithMariadb())

    # Capture the source= the helpers were called with.
    calls: dict[str, str] = {}

    def fake_build_sqlite_if_needed(*, source: str, **_kw: object) -> dict[str, object]:
        calls["sqlite_source"] = source
        return {"path": "x", "rows_inserted": 0, "tables_skipped": []}

    def fake_build_mdb_if_needed(*, source: str, **_kw: object) -> dict[str, object]:
        calls["mdb_source"] = source
        return {"path": "y", "rows_inserted": 0, "tables_skipped": []}

    monkeypatch.setattr(ba_mod, "_build_sqlite_if_needed", fake_build_sqlite_if_needed)
    monkeypatch.setattr(ba_mod, "_build_mdb_if_needed", fake_build_mdb_if_needed)

    # Capture ensure_imported invocations.
    from datetime import UTC, datetime
    imported_calls: list[tuple[object, object]] = []
    def fake_ensure_imported(cfg: object, info: object) -> CacheStatus:
        imported_calls.append((cfg, info))
        return CacheStatus(
            reused=False,
            datadump_sha="deadbeef" * 8,
            elapsed_seconds=42.0,
            imported_at=datetime.now(UTC),
        )
    monkeypatch.setattr(ba_mod, "ensure_imported", fake_ensure_imported)

    rc = build_all()
    out = capsys.readouterr().out
    assert rc == 0
    assert len(imported_calls) == 1, "ensure_imported must be called exactly once"
    assert calls.get("sqlite_source") == "mariadb"
    assert calls.get("mdb_source") == "mariadb"
    assert "[mariadb] re-imported" in out


def test_build_all_mariadb_failure_returns_1(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `MariaDbError` from `ensure_imported` aborts build_all with rc=1
    and does NOT call either builder helper (no partial-write
    cleanup on artifacts the run never touched)."""
    from cbdb_parity.config import MariaDbConfig
    from cbdb_parity.mariadb import MariaDbError

    mariadb_cfg = MariaDbConfig(
        host="localhost", port=3306, user="root", password="x",
        database="cbdb_data", container_name="x",
        force_reimport=False, auto_launch=False,
    )

    class _CfgWithMariadb:
        datadump_dir = fake_pipeline.parent
        build_output_dir = fake_pipeline.parent / "build"
        access_mysql_transfer_repo = fake_pipeline.parent
        mariadb = mariadb_cfg
        use_cache = False

    monkeypatch.setattr(ba_mod, "load_config", lambda: _CfgWithMariadb())

    def fake_ensure_imported(cfg: object, info: object) -> None:
        raise MariaDbError("simulated MariaDB outage")
    monkeypatch.setattr(ba_mod, "ensure_imported", fake_ensure_imported)

    builder_calls: list[str] = []
    monkeypatch.setattr(
        ba_mod, "_build_sqlite_if_needed",
        lambda **_kw: builder_calls.append("sqlite") or {},  # type: ignore[func-returns-value]
    )
    monkeypatch.setattr(
        ba_mod, "_build_mdb_if_needed",
        lambda **_kw: builder_calls.append("mdb") or {},  # type: ignore[func-returns-value]
    )

    rc = build_all()
    assert rc == 1
    assert builder_calls == [], "builders must not run after a MariaDB cache failure"


def test_build_all_use_cache_short_circuits_when_products_exist(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CBDB_PARITY_USE_CACHE=1 + valid .build products + consistent
    manifest → exit 0 without touching Datadump / MariaDB / builders."""
    build_dir = tmp_path / "build"
    sqlite_path = build_dir / "cbdb.sqlite"
    mdb_path = build_dir / "cbdb_data.mdb"
    sqlite_path.write_bytes(b"sqlite content")
    mdb_path.write_bytes(b"mdb content")

    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {
            "sqlite": {
                "path": str(sqlite_path), "rows_inserted": 100,
                "builder_version": "1.2-python-port",
            },
            "mdb": {
                "path": str(mdb_path), "rows_inserted": 100,
                "builder_version": "1.3b-mysqldump-parser-overlay",
            },
        },
    }), encoding="utf-8")

    class _CfgCache:
        datadump_dir = tmp_path
        build_output_dir = build_dir
        access_mysql_transfer_repo = tmp_path
        mariadb = None
        use_cache = True
    monkeypatch.setattr(ba_mod, "load_config", lambda: _CfgCache())

    # Anything past the refresh step would explode if reached.
    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("USE_CACHE=1 short-circuit must not call this")
    monkeypatch.setattr(ba_mod, "find_latest_datadump", _explode)
    monkeypatch.setattr(ba_mod, "ensure_imported", _explode)
    monkeypatch.setattr(ba_mod, "_build_sqlite_if_needed", _explode)
    monkeypatch.setattr(ba_mod, "_build_mdb_if_needed", _explode)

    rc = build_all()
    out = capsys.readouterr().out
    assert rc == 0
    assert "[cache hit]" in out


def test_build_all_use_cache_falls_through_when_product_missing(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """USE_CACHE=1 + manifest claims products but one file is missing
    on disk → fall through to the full pipeline (don't trust a manifest
    that lies)."""
    build_dir = tmp_path / "build"
    sqlite_path = build_dir / "cbdb.sqlite"
    mdb_path = build_dir / "cbdb_data.mdb"
    sqlite_path.write_bytes(b"sqlite")
    # mdb_path intentionally NOT created.

    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {
            "sqlite": {"path": str(sqlite_path)},
            "mdb": {"path": str(mdb_path)},
        },
    }), encoding="utf-8")

    class _CfgCache:
        datadump_dir = tmp_path
        build_output_dir = build_dir
        access_mysql_transfer_repo = tmp_path
        mariadb = None
        use_cache = True
    monkeypatch.setattr(ba_mod, "load_config", lambda: _CfgCache())

    # Cache short-circuit must NOT fire — find_latest_datadump should run.
    called = {"datadump": False}
    def _spy_find(_dir: Path) -> object:
        called["datadump"] = True
        # Raise to short-stop the test before the rest of the pipeline.
        raise DatadumpError("test stops here after cache miss verified")
    monkeypatch.setattr(ba_mod, "find_latest_datadump", _spy_find)

    rc = build_all()
    assert called["datadump"] is True
    assert rc == 2  # DatadumpError → config-style exit


def test_build_all_mariadb_force_reimport_bypasses_use_cache(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """USE_CACHE=1 + MARIADB_FORCE_REIMPORT=1 → bypass the cache
    short-circuit. The user is signaling 'rebuild MariaDB from
    scratch', which implies the downstream products are stale too."""
    from cbdb_parity.config import MariaDbConfig

    build_dir = tmp_path / "build"
    sqlite_path = build_dir / "cbdb.sqlite"
    mdb_path = build_dir / "cbdb_data.mdb"
    sqlite_path.write_bytes(b"x")
    mdb_path.write_bytes(b"y")
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {
            "sqlite": {"path": str(sqlite_path)},
            "mdb": {"path": str(mdb_path)},
        },
    }), encoding="utf-8")

    mariadb_cfg = MariaDbConfig(
        host="localhost", port=3306, user="root", password="x",
        database="cbdb_data", container_name="x",
        force_reimport=True,  # the override
        auto_launch=False,
    )

    class _Cfg:
        datadump_dir = tmp_path
        build_output_dir = build_dir
        access_mysql_transfer_repo = tmp_path
        mariadb = mariadb_cfg
        use_cache = True
    monkeypatch.setattr(ba_mod, "load_config", lambda: _Cfg())

    called = {"datadump": False}
    def _spy_find(_dir: Path) -> object:
        called["datadump"] = True
        raise DatadumpError("test stops here after FORCE_REIMPORT bypass verified")
    monkeypatch.setattr(ba_mod, "find_latest_datadump", _spy_find)

    rc = build_all()
    assert called["datadump"] is True, (
        "MARIADB_FORCE_REIMPORT=1 must defeat the USE_CACHE=1 short-circuit"
    )
    assert rc == 2


def test_build_all_use_cache_invalidated_by_access_schema_refresh(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """USE_CACHE=1 + valid products + manifest BUT ACCESS_MYSQL_TRANSFER_REPO
    just fast-forwarded → fall through. The mdb's CREATE TABLE depends on
    that repo's TablesFields.xlsx, so a refreshed xlsx may have changed the
    expected mdb shape even when the Datadump SHA is unchanged."""
    build_dir = tmp_path / "build"
    sqlite_path = build_dir / "cbdb.sqlite"
    mdb_path = build_dir / "cbdb_data.mdb"
    sqlite_path.write_bytes(b"x")
    mdb_path.write_bytes(b"y")
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {
            "sqlite": {"path": str(sqlite_path)},
            "mdb": {"path": str(mdb_path)},
        },
    }), encoding="utf-8")

    class _CfgCache:
        datadump_dir = tmp_path
        build_output_dir = build_dir
        access_mysql_transfer_repo = tmp_path
        mariadb = None
        use_cache = True
    monkeypatch.setattr(ba_mod, "load_config", lambda: _CfgCache())

    # Simulate refresh saying ACCESS_MYSQL_TRANSFER_REPO updated.
    monkeypatch.setattr(ba_mod, "refresh_all", lambda _cfg: [
        RefreshResult("ACCESS_TESTS_REPO", Path("/a"), True, "aa", "aa", "Already up to date."),
        RefreshResult("AVALONIA_REPO", Path("/b"), True, "bb", "bb", "Already up to date."),
        RefreshResult("ONLINE_SERVER_REPO", Path("/c"), True, "cc", "cc", "Already up to date."),
        RefreshResult("ACCESS_MYSQL_TRANSFER_REPO", Path("/d"), True, "dd0", "dd1", "Fast-forwarded."),
    ])

    called = {"datadump": False}
    def _spy_find(_dir: Path) -> object:
        called["datadump"] = True
        raise DatadumpError("test stops here after invalidation verified")
    monkeypatch.setattr(ba_mod, "find_latest_datadump", _spy_find)

    rc = build_all()
    assert called["datadump"] is True, (
        "ACCESS_MYSQL_TRANSFER_REPO refresh must invalidate USE_CACHE so "
        "the full pipeline (and thus the mdb rebuild) runs"
    )
    assert rc == 2


def test_build_all_use_cache_survives_other_repo_refresh(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """USE_CACHE=1 + the OTHER three repos refreshed → still cache hit.
    The Avalonia / mdb-tests / online-server repos affect Phase 3 tests
    downstream but NOT build_all's products."""
    build_dir = tmp_path / "build"
    sqlite_path = build_dir / "cbdb.sqlite"
    mdb_path = build_dir / "cbdb_data.mdb"
    sqlite_path.write_bytes(b"x")
    mdb_path.write_bytes(b"y")
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {
            "sqlite": {
                "path": str(sqlite_path),
                "builder_version": "1.2-python-port",
            },
            "mdb": {
                "path": str(mdb_path),
                "builder_version": "1.3b-mysqldump-parser-overlay",
            },
        },
    }), encoding="utf-8")

    class _CfgCache:
        datadump_dir = tmp_path
        build_output_dir = build_dir
        access_mysql_transfer_repo = tmp_path
        mariadb = None
        use_cache = True
    monkeypatch.setattr(ba_mod, "load_config", lambda: _CfgCache())

    monkeypatch.setattr(ba_mod, "refresh_all", lambda _cfg: [
        RefreshResult("ACCESS_TESTS_REPO", Path("/a"), True, "aa0", "aa1", "Fast-forwarded."),
        RefreshResult("AVALONIA_REPO", Path("/b"), True, "bb0", "bb1", "Fast-forwarded."),
        RefreshResult("ONLINE_SERVER_REPO", Path("/c"), True, "cc0", "cc1", "Fast-forwarded."),
        RefreshResult("ACCESS_MYSQL_TRANSFER_REPO", Path("/d"), True, "dd", "dd", "Already up to date."),
    ])

    def _explode(*_a: object, **_kw: object) -> None:
        raise AssertionError("USE_CACHE=1 must short-circuit on non-schema-repo refresh")
    monkeypatch.setattr(ba_mod, "find_latest_datadump", _explode)

    rc = build_all()
    out = capsys.readouterr().out
    assert rc == 0
    assert "[cache hit]" in out


def test_build_all_rebuild_flag_overrides_use_cache(
    fake_pipeline: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """USE_CACHE=1 + --rebuild → ignore cache short-circuit and run the
    full pipeline. Lets users force a fresh rebuild without flipping
    the env switch."""
    build_dir = tmp_path / "build"
    sqlite_path = build_dir / "cbdb.sqlite"
    mdb_path = build_dir / "cbdb_data.mdb"
    sqlite_path.write_bytes(b"x")
    mdb_path.write_bytes(b"y")
    fake_pipeline.write_text(json.dumps({
        "version": 1,
        "datadump": {"filename": "x.tar.gz", "sha256": "deadbeef" * 8, "date_tag": "20260101"},
        "products": {
            "sqlite": {"path": str(sqlite_path)},
            "mdb": {"path": str(mdb_path)},
        },
    }), encoding="utf-8")

    class _CfgCache:
        datadump_dir = tmp_path
        build_output_dir = build_dir
        access_mysql_transfer_repo = tmp_path
        mariadb = None
        use_cache = True
    monkeypatch.setattr(ba_mod, "load_config", lambda: _CfgCache())

    called = {"datadump": False}
    def _spy_find(_dir: Path) -> object:
        called["datadump"] = True
        raise DatadumpError("test stops here after rebuild=True verified")
    monkeypatch.setattr(ba_mod, "find_latest_datadump", _spy_find)

    rc = build_all(rebuild=True)
    assert called["datadump"] is True
    assert rc == 2
