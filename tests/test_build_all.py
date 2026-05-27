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
            "mdb": {"path": str(mdb_path), "rows_inserted": 12345},
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
