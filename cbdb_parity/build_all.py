"""Single-entrypoint build orchestrator (Phase 1.4).

Picks the latest Datadump, refreshes the four external repos, and runs
each sub-builder (Phase 1.2 sqlite, Phase 1.3b mdb) IF the
build_manifest.json doesn't already record a successful build of that
product against the current Datadump SHA. Pass `--rebuild` to force a
full rebuild even when the manifest matches.

This is the only entrypoint that's allowed to write the top-level
`datadump` block in build_manifest.json — the sub-builders' standalone
CLIs (Phase 1.2 `cbdb-parity-build-sqlite`, Phase 1.3b `cbdb-parity-
build-mdb`) overwrite their own product slot but rely on the orchestrator
to anchor everything to one SHA.

Both sub-builders run in a single invocation, with same-SHA caching and
shared partial-write protection (failed rebuilds unlink the partial
output and strip the stale manifest entry).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tarfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from dotenv import find_dotenv

from cbdb_parity.access_schema import AccessSchemaError, load_access_schema
from cbdb_parity.config import Config, ConfigError, load_config
from cbdb_parity.datadump import (
    DatadumpError,
    DatadumpInfo,
    find_latest_datadump,
    open_dump_stream,
)
from cbdb_parity.mariadb import MariaDbError, ensure_imported
from cbdb_parity.mariadb_source import iter_events as mariadb_iter_events
from cbdb_parity.mdb_builder import MdbBuilderError, build_mdb, build_mdb_from_events
from cbdb_parity.mysqldump import MysqlDumpError
from cbdb_parity.refresh import RefreshError, RefreshResult, refresh_all
from cbdb_parity.sqlite_builder import build_sqlite, build_sqlite_from_events

_MANIFEST_NAME = "build_manifest.json"


def _workspace_root() -> Path:
    """The directory holding `.env` — repo root for editable installs,
    the user's working directory for non-editable installs. NOT `__file__`-
    based (that would resolve to site-packages for installed console
    scripts).
    """
    found = find_dotenv(usecwd=True)
    if found:
        return Path(found).resolve().parent
    # Fallback: cwd. This only fires if .env discovery failed AND
    # load_config didn't raise (which shouldn't happen, but the function
    # has to return *something*).
    return Path.cwd().resolve()


def _manifest_path() -> Path:
    """Manifest lives at the workspace root (next to .env), where AGENTS.md
    and the repo's .gitignore commentary place it for committed provenance.
    """
    return _workspace_root() / _MANIFEST_NAME


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        # Treat anything other than a JSON object (e.g. `[]`, a bare string,
        # or a number left behind by hand-editing) as an empty manifest so
        # downstream `.get(...)` calls don't blow up with AttributeError.
        return {}
    return payload


def _existing_product_sha_matches(
    manifest: dict[str, object],
    product: str,
    target_sha: str,
) -> bool:
    """Has `product` already been built from `target_sha` per the manifest?"""
    if not isinstance(manifest.get("datadump"), dict):
        return False
    if manifest["datadump"].get("sha256") != target_sha:  # type: ignore[index]
        return False
    products = manifest.get("products", {})
    if not isinstance(products, dict):
        return False
    return product in products


def _write_manifest(
    path: Path,
    info: DatadumpInfo,
    sha: str,
    products: dict[str, dict[str, object]],
) -> None:
    """Single authoritative write of the orchestrator's manifest view."""
    payload = {
        "version": 1,
        "built_at": datetime.now(UTC).isoformat(),
        "datadump": {
            "filename": info.filename,
            "sha256": sha,
            "date_tag": info.date_tag,
        },
        "products": products,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _try_use_cache(
    cfg: Config,
    refresh_results: list[RefreshResult],
) -> str | None:
    """Top-tier cache check (CBDB_PARITY_USE_CACHE=1 path).

    Returns a human-readable success message when the cache should be
    reused (caller exits 0), or None when the cache is incomplete /
    inconsistent (caller falls through to the full pipeline).

    Conditions for a cache hit, ALL of which must hold:
      1. `build_manifest.json` exists, parses as a dict, and records a
         non-empty `datadump.sha256` plus both `products.sqlite` and
         `products.mdb` entries.
      2. The recorded `products.sqlite.path` resolves to
         `cfg.build_output_dir / 'cbdb.sqlite'`, exists on disk, and
         is non-empty.
      3. The recorded `products.mdb.path` resolves to
         `cfg.build_output_dir / 'cbdb_data.mdb'`, exists on disk, and
         is non-empty.
      4. `ACCESS_MYSQL_TRANSFER_REPO` did NOT fast-forward during this
         run's refresh — `mdb_builder` derives column types and the
         skip list from `$ACCESS_MYSQL_TRANSFER_REPO/TablesFields.xlsx`,
         so a refreshed repo can change the EXPECTED mdb shape even
         when the Datadump SHA is unchanged. The other three external
         repos affect downstream parity tests (cbdb-desktop-app SQL,
         cbdb-user-mdb-tests cbdb_replay code, cbdb-online-main-server
         reference) but not the build products themselves.

    This short-circuit deliberately does NOT consult `cfg.datadump_dir`
    — when the cache is valid the user has told us (via USE_CACHE=1)
    not to invalidate the artifacts just because a newer Datadump
    archive sits in the input folder. To pick up a new Datadump set
    USE_CACHE=0 (or pass `--rebuild`, or delete `.build/` products,
    or `MARIADB_FORCE_REIMPORT=1` if only MariaDB is stale).
    """
    # (4) Schema repo updated → invalidate the cached mdb whose
    # CREATE TABLE was derived from the OLD xlsx.
    for r in refresh_results:
        if r.key == "ACCESS_MYSQL_TRANSFER_REPO" and r.updated:
            return None

    manifest = _manifest_path()
    existing = _load_manifest(manifest)
    if not existing:
        return None
    dd = existing.get("datadump")
    if not isinstance(dd, dict):
        return None
    sha = dd.get("sha256")
    if not isinstance(sha, str) or not sha:
        return None
    products = existing.get("products")
    if not isinstance(products, dict):
        return None

    expected = {
        "sqlite": cfg.build_output_dir / "cbdb.sqlite",
        "mdb": cfg.build_output_dir / "cbdb_data.mdb",
    }
    for key, target in expected.items():
        entry = products.get(key)
        if not isinstance(entry, dict):
            return None
        recorded = entry.get("path")
        if not isinstance(recorded, str):
            return None
        try:
            if Path(recorded).resolve() != target.resolve():
                return None
        except OSError:
            return None
        if not target.is_file() or target.stat().st_size == 0:
            return None
    return (
        f"[cache hit] using existing products at SHA {sha[:12]}; "
        f"set CBDB_PARITY_USE_CACHE=0 (or pass --rebuild) to force a "
        f"fresh Datadump scan / rebuild."
    )


def _build_mdb_if_needed(
    info: DatadumpInfo,
    sha: str,
    out_path: Path,
    cfg: Config,
    existing: dict[str, object],
    *,
    rebuild: bool,
    source: str = "datadump",
    on_started: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Build cbdb_data.mdb unless the manifest already records it for
    this SHA at this path, with the file present. Mirrors
    `_build_sqlite_if_needed` invariants.

    `on_started` (if provided) is forwarded to `build_mdb()` and fires
    INSIDE the builder, AFTER the prior file (if any) has been unlinked
    and we are about to write the fresh mdb. The caller uses this to
    flag "destination is now in a partial state on failure" — pre-
    builder errors (open_dump_stream, schema load) leave the flag
    untouched so cached artifacts are preserved.
    """
    cached_entry: dict[str, object] | None = None
    if _existing_product_sha_matches(existing, "mdb", sha):
        candidate = existing.get("products", {}).get("mdb")  # type: ignore[union-attr]
        if isinstance(candidate, dict) and candidate.get("path") == str(out_path):
            cached_entry = candidate
    if not rebuild and cached_entry is not None and out_path.is_file():
        print(f"  [cached]   mdb     ({cached_entry.get('rows_inserted', 0):,} rows from prior build)")
        return cached_entry

    # Load the Access schema overlay (TablesFields.xlsx) — same content
    # the standalone cbdb-parity-build-mdb CLI uses.
    xlsx_path = cfg.access_mysql_transfer_repo / "TablesFields.xlsx"
    schema_overlay = load_access_schema(xlsx_path)

    t0 = time.time()
    print(f"  [building] mdb     -> {out_path}  (source={source})")
    if source == "mariadb":
        assert cfg.mariadb is not None, "_build_mdb_if_needed got source='mariadb' but cfg.mariadb is None"
        # Lazy import + scoped pymysql connection so the Datadump path
        # never imports pymysql or holds a MariaDB socket.
        from cbdb_parity.mariadb import _connect
        conn = _connect(cfg.mariadb, database=cfg.mariadb.database)
        try:
            stats = build_mdb_from_events(
                mariadb_iter_events(conn, cfg.mariadb.database),
                out_path,
                access_schema=schema_overlay,
                on_started=on_started,
            )
        finally:
            conn.close()
    else:
        with open_dump_stream(info) as stream:
            stats = build_mdb(
                stream,
                out_path,
                access_schema=schema_overlay,
                on_started=on_started,
            )
    elapsed = time.time() - t0
    print(
        f"             {stats.tables_created} tables, "
        f"{stats.rows_inserted:,} rows in {elapsed:.1f}s"
    )
    return {
        "path": str(out_path),
        "tables_created": stats.tables_created,
        "tables_skipped": stats.tables_skipped,
        "rows_inserted": stats.rows_inserted,
        "built_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
    }


def _build_sqlite_if_needed(
    info: DatadumpInfo,
    sha: str,
    out_path: Path,
    existing: dict[str, object],
    cfg: Config,
    *,
    rebuild: bool,
    source: str = "datadump",
    on_started: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Build cbdb.sqlite unless the manifest already records it for this
    SHA *at the same output path*. A BUILD_OUTPUT_DIR change invalidates
    the cache even if a stale `cbdb.sqlite` happens to sit at the new
    target — otherwise we'd rewrite the manifest with the old path while
    leaving the requested target unbuilt.

    `on_started` (if provided) is forwarded to `build_sqlite()` and
    fires INSIDE the builder, AFTER the prior file (if any) has been
    unlinked and we are about to lay down a fresh one. Pre-builder
    errors (e.g. `open_dump_stream` failing) leave the flag untouched
    so any cached artifact is preserved.
    """
    cached_entry: dict[str, object] | None = None
    if _existing_product_sha_matches(existing, "sqlite", sha):
        candidate = existing.get("products", {}).get("sqlite")  # type: ignore[union-attr]
        if isinstance(candidate, dict) and candidate.get("path") == str(out_path):
            cached_entry = candidate
    if not rebuild and cached_entry is not None and out_path.is_file():
        print(f"  [cached]   sqlite  ({cached_entry.get('rows_inserted', 0):,} rows from prior build)")
        return cached_entry

    t0 = time.time()
    print(f"  [building] sqlite  -> {out_path}  (source={source})")
    if source == "mariadb":
        assert cfg.mariadb is not None, "_build_sqlite_if_needed got source='mariadb' but cfg.mariadb is None"
        from cbdb_parity.mariadb import _connect
        conn = _connect(cfg.mariadb, database=cfg.mariadb.database)
        try:
            stats = build_sqlite_from_events(
                mariadb_iter_events(conn, cfg.mariadb.database),
                out_path,
                on_started=on_started,
            )
        finally:
            conn.close()
    else:
        with open_dump_stream(info) as stream:
            stats = build_sqlite(stream, out_path, on_started=on_started)
    elapsed = time.time() - t0
    print(
        f"             {stats.tables_created} tables, "
        f"{stats.rows_inserted:,} rows in {elapsed:.1f}s"
    )
    return {
        "path": str(out_path),
        "tables_created": stats.tables_created,
        "tables_skipped": stats.tables_skipped,
        "rows_inserted": stats.rows_inserted,
        "built_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
    }


def build_all(
    *,
    rebuild: bool = False,
) -> int:
    """Run the full Datadump → cbdb.sqlite (+ later cbdb_data.mdb) pipeline.

    Returns shell-style exit code: 0 success, 1 build failure, 2 config error.

    Per AGENTS.md and WORK_PLAN §3.4, the mandatory cross-repo refresh is
    ALWAYS run first. There is no opt-out — if the local checkout of one
    of the four external repos can't fast-forward, fix the checkout (e.g.
    `git checkout master` on a divergent branch) rather than skipping the
    gate.
    """
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    print("[refresh] git pull --ff-only on the four external repos...")
    try:
        results = refresh_all(cfg)
    except RefreshError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for r in results:
        tag = "updated" if r.updated else "up-to-date"
        print(f"  [{tag}] {r.key}")

    # Top-tier cache short-circuit (CBDB_PARITY_USE_CACHE=1, default).
    # If both products exist on disk AND the manifest records them at
    # those exact paths with the same datadump SHA, we trust the cache
    # and skip the Datadump scan / MariaDB import / builders entirely.
    # `--rebuild` and `MARIADB_FORCE_REIMPORT=1` both override this
    # path so users can still force fresh work without flipping the
    # env switch.
    # Any of `--rebuild`, `MARIADB_FORCE_REIMPORT=1`, or `use_cache=0`
    # bypasses the top-tier short-circuit so the user's documented
    # repair controls stay effective even at the default USE_CACHE=1.
    mariadb_force = cfg.mariadb is not None and cfg.mariadb.force_reimport
    if cfg.use_cache and not rebuild and not mariadb_force:
        cached_status = _try_use_cache(cfg, results)
        if cached_status is not None:
            print(cached_status)
            return 0

    # Datadump selection.
    try:
        info = find_latest_datadump(cfg.datadump_dir)
    except DatadumpError as exc:
        print(f"datadump error: {exc}", file=sys.stderr)
        return 2
    print(f"[datadump] {info.filename} ({info.date_tag})")
    print("[datadump] hashing source archive...")
    try:
        sha = info.sha256
    except OSError as exc:
        print(f"datadump hashing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"[datadump] sha256 = {sha}")

    manifest = _manifest_path()
    existing = _load_manifest(manifest)

    sqlite_out = cfg.build_output_dir / "cbdb.sqlite"
    # Touched-detection: an explicit "we entered the builder" flag, NOT
    # mtime delta. mtime nanoseconds aren't reliable on FAT/exFAT/some
    # network shares (a same-tick rebuild+fail looks untouched even
    # though the file was recreated and possibly corrupted). The flag
    # is conservatively pessimistic: anything reaching the builder is
    # treated as "touched" on failure so we unlink the (possibly
    # partial) output rather than risk caching a corrupt artifact.
    sqlite_build_started = False
    mdb_build_started = False
    # Seed `products` with same-SHA sibling entries from the existing
    # manifest. A sqlite-only successful run must NOT silently drop the
    # mdb (or other product) that was built from the same dump earlier —
    # but only when the sibling's recorded `path` lives under the current
    # BUILD_OUTPUT_DIR. A changed BUILD_OUTPUT_DIR invalidates siblings
    # (their files don't exist at the new location).
    products: dict[str, dict[str, object]] = {}
    existing_dd = existing.get("datadump") if isinstance(existing.get("datadump"), dict) else None
    build_dir_resolved = cfg.build_output_dir.resolve()
    if existing_dd and existing_dd.get("sha256") == sha:  # type: ignore[union-attr]
        existing_products = existing.get("products", {})
        if isinstance(existing_products, dict):
            for k, v in existing_products.items():
                if not isinstance(v, dict) or k == "sqlite":
                    continue
                sib_path = v.get("path")
                if not isinstance(sib_path, str):
                    continue
                try:
                    sib_resolved = Path(sib_path).resolve()
                except OSError:
                    continue
                # Only carry forward siblings whose recorded path is
                # inside the current BUILD_OUTPUT_DIR AND whose file
                # actually still exists.
                try:
                    sib_resolved.relative_to(build_dir_resolved)
                except ValueError:
                    continue
                if not sib_resolved.is_file():
                    continue
                products[k] = v
    mdb_out = cfg.build_output_dir / "cbdb_data.mdb"

    # Lazy import of the Access driver Error classes so the orchestrator
    # can include them in the catch list without forcing pyodbc/pypyodbc
    # to be importable on non-Windows. Uses a sentinel class (NOT empty
    # tuple) — see mdb_builder._NoSuchError for the rationale.
    from cbdb_parity.mdb_builder import _NoSuchError
    _pyodbc_error: type[BaseException] = _NoSuchError
    try:
        import pyodbc as _pyodbc
        _pyodbc_error = _pyodbc.Error
    except ImportError:
        pass
    _pypyodbc_error: type[BaseException] = _NoSuchError
    try:
        import pypyodbc as _pypyodbc
        _pypyodbc_error = _pypyodbc.Error  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        pass

    # The "started" flags are set by callbacks INSIDE the helpers
    # right before they enter build_sqlite / build_mdb (i.e. AFTER
    # open_dump_stream succeeds). That way a pre-builder failure
    # (corrupt archive, missing schema xlsx) doesn't mistakenly mark
    # a destination as "touched" — its previous-good content stays
    # intact and its manifest entry is preserved.
    def _mark_sqlite_started() -> None:
        nonlocal sqlite_build_started
        sqlite_build_started = True

    def _mark_mdb_started() -> None:
        nonlocal mdb_build_started
        mdb_build_started = True

    # Pick the import source. Phase 1.6 §4d makes 'mariadb' the default
    # when `cfg.mariadb` is configured (= all 5 required MARIADB_* keys
    # set in .env); otherwise fall back to the Datadump-direct path so
    # non-Docker hosts still work. If 'mariadb' is selected, populate
    # the cache up front via ensure_imported() so both builders read
    # from a guaranteed-fresh DB.
    source = "mariadb" if cfg.mariadb is not None else "datadump"
    if source == "mariadb":
        try:
            cache_status = ensure_imported(cfg, info)
            verb = "reused cached" if cache_status.reused else "re-imported"
            print(
                f"[mariadb] {verb} Datadump SHA {cache_status.datadump_sha[:12]} "
                f"in {cache_status.elapsed_seconds:.1f}s"
            )
        except MariaDbError as exc:
            print(f"MariaDB cache step failed: {exc}", file=sys.stderr)
            return 1

    try:
        products["sqlite"] = _build_sqlite_if_needed(
            info=info,
            sha=sha,
            out_path=sqlite_out,
            existing=existing,
            cfg=cfg,
            rebuild=rebuild,
            source=source,
            on_started=_mark_sqlite_started,
        )
        products["mdb"] = _build_mdb_if_needed(
            info=info,
            sha=sha,
            out_path=mdb_out,
            cfg=cfg,
            existing=existing,
            rebuild=rebuild,
            source=source,
            on_started=_mark_mdb_started,
        )
    except (
        MysqlDumpError,
        DatadumpError,
        tarfile.TarError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        MdbBuilderError,
        AccessSchemaError,
        MariaDbError,
        ImportError,
        _pyodbc_error,
        _pypyodbc_error,
    ) as exc:
        # DatadumpError reaches us through `open_dump_stream` for malformed
        # archives (e.g. missing cbdb_data.sql member); tarfile.TarError
        # covers the case where the archive itself is corrupt (not a valid
        # tar/gzip stream) and never gets far enough to raise DatadumpError.
        print(f"build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # Partial-write protection: build_sqlite unlinks the destination
        # before writing, so a mid-stream failure leaves a partial file
        # behind. BUT a pre-build failure (e.g. open_dump_stream rejected
        # a corrupt archive) never touched the destination — the old good
        # artifact is intact and we must NOT delete it. Distinguish via
        # mtime: a touch implies build_sqlite started writing.
        if sqlite_build_started and sqlite_out.is_file():
            try:
                sqlite_out.unlink()
            except OSError:
                pass
        if mdb_build_started and mdb_out.is_file():
            try:
                mdb_out.unlink()
            except OSError:
                pass
        # Reconcile the manifest. Two cases:
        #   - existing SHA matches new SHA: only the sqlite entry is stale
        #     (other products may be fine); strip just sqlite.
        #   - existing SHA differs OR there's no existing manifest: we
        #     would have OVERWRITTEN those siblings under the new SHA; to
        #     avoid stamping them with provenance they don't own, drop
        #     the whole `products` block.
        if isinstance(existing.get("products"), dict):
            existing_dd = existing.get("datadump")
            existing_sha = existing_dd.get("sha256") if isinstance(existing_dd, dict) else None
            if existing_sha == sha:
                # Same SHA: strip ONLY the side(s) that this run tried
                # to build. A pre-builder failure (config / refresh
                # error) doesn't touch either output and leaves their
                # manifest entries intact.
                if sqlite_build_started:
                    existing["products"].pop("sqlite", None)  # type: ignore[union-attr]
                if mdb_build_started:
                    existing["products"].pop("mdb", None)  # type: ignore[union-attr]
                products_to_write = existing.get("products", {})
            else:
                products_to_write = {}
            try:
                _write_manifest(manifest, info, sha, products_to_write)  # type: ignore[arg-type]
            except OSError:
                pass
        return 1

    try:
        _write_manifest(manifest, info, sha, products)
    except OSError as exc:
        # Build artefacts exist on disk but provenance write failed
        # (read-only workspace, locked file, full disk, …). Surface as a
        # build failure rather than crashing — the user needs to fix the
        # workspace permission and re-run.
        print(
            f"build artefacts written but manifest write failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"[manifest] {manifest}")
    print("[done] all products in sync with Datadump SHA " + sha[:12])
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cbdb-parity-build-all")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="force rebuild even if the manifest already records this Datadump SHA",
    )
    args = parser.parse_args(argv)
    return build_all(rebuild=args.rebuild)
