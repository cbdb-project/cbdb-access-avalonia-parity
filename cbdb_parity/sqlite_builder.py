"""Datadump → cbdb.sqlite builder (Python port of `db:export-to-sqlite`).

Stream-parses a CBDB Datadump and emits a SQLite file that is structurally
equivalent to what `php artisan db:export-to-sqlite` would produce from
the same MySQL connection. Same defaults: internal `CBDB__*` tables and
indexes are skipped unless explicitly opted in.

Type mapping mirrors `ExportMysqlToSqlite::convertColumnType` in the
Laravel source-of-truth command. Schema decisions intentionally kept
minimal (no per-column COMMENT, no CHARACTER SET, no COLLATE — SQLite
doesn't support them anyway) so the diff against the Laravel output stays
human-auditable.

Phase 1.2 scope: this builder produces the bulk-loaded SQLite. The
auxiliary index/address rebuilders (RebuildIndexAddress, RebuildIndexYear,
RebuildNameSearchIndex, RegenerateAddresses, ImportTradSimpMap) are NOT
ported here — they will land as separate modules invoked by Phase 1.4's
build_all orchestrator.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from cbdb_parity.config import ConfigError, load_config
from cbdb_parity.datadump import (
    DatadumpError,
    DatadumpInfo,
    find_latest_datadump,
    open_dump_stream,
)
from cbdb_parity.mysqldump import Column, MysqlDumpError, Row, TableSchema, parse_dump

# MySQL → SQLite type-token rewriter. Patterns mirror Laravel's
# `convertColumnType` exactly: case-insensitive, word-boundary anchored,
# applied in declaration order. The full type string (e.g. "varchar(255)")
# becomes the SQLite affinity (e.g. "TEXT").
_TYPE_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bTINYINT\(\d+\)", re.I), "INTEGER"),
    (re.compile(r"\bSMALLINT\(\d+\)", re.I), "INTEGER"),
    (re.compile(r"\bMEDIUMINT\(\d+\)", re.I), "INTEGER"),
    (re.compile(r"\bBIGINT\(\d+\)", re.I), "INTEGER"),
    (re.compile(r"\bINT\(\d+\)", re.I), "INTEGER"),
    (re.compile(r"\bBIGINT\b", re.I), "INTEGER"),
    (re.compile(r"\bINT\b", re.I), "INTEGER"),
    (re.compile(r"\bDOUBLE\b", re.I), "REAL"),
    (re.compile(r"\bFLOAT\b", re.I), "REAL"),
    (re.compile(r"\bDECIMAL\([^)]*\)", re.I), "NUMERIC"),
    (re.compile(r"\bNUMERIC\([^)]*\)", re.I), "NUMERIC"),
    (re.compile(r"\bVARBINARY\(\d+\)", re.I), "BLOB"),
    (re.compile(r"\bBINARY\(\d+\)", re.I), "BLOB"),
    (re.compile(r"\bLONGTEXT\b", re.I), "TEXT"),
    (re.compile(r"\bMEDIUMTEXT\b", re.I), "TEXT"),
    (re.compile(r"\bTINYTEXT\b", re.I), "TEXT"),
    (re.compile(r"\bTEXT\b", re.I), "TEXT"),
    (re.compile(r"\bVARCHAR\(\d+\)", re.I), "TEXT"),
    (re.compile(r"\bCHAR\(\d+\)", re.I), "TEXT"),
    (re.compile(r"\bDATETIME\b", re.I), "TEXT"),
    (re.compile(r"\bTIMESTAMP\b", re.I), "TEXT"),
    (re.compile(r"\bDATE\b", re.I), "TEXT"),
    (re.compile(r"\bTIME\b", re.I), "TEXT"),
    (re.compile(r"\bENUM\([^)]+\)", re.I), "TEXT"),
    (re.compile(r"\bSET\([^)]+\)", re.I), "TEXT"),
)

_INTERNAL_PREFIX = "CBDB__"

# A SQLite INSERT with 1000 rows x ~30 columns lands well under the
# default SQLITE_MAX_VARIABLE_NUMBER (32766 on the .venv interpreter).
_BATCH_ROWS = 1000


def mysql_type_to_sqlite(mysql_type: str) -> str:
    """Translate a single MySQL column type string to its SQLite equivalent.

    Public for unit-testing the mapping in isolation; the builder calls
    this for every Column it sees.
    """
    out = mysql_type
    for pat, repl in _TYPE_MAP:
        out = pat.sub(repl, out)
    return out.strip()


def _create_table_sql(schema: TableSchema) -> str:
    """Render a CREATE TABLE statement for SQLite from a parsed schema."""
    col_defs = [
        f'"{c.name}" {mysql_type_to_sqlite(c.sql_type)}' for c in schema.columns
    ]
    sep = ",\n    "
    return f'CREATE TABLE "{schema.name}" (\n    {sep.join(col_defs)}\n);'


@dataclass(slots=True)
class BuildStats:
    """Per-build summary: how many tables, how many rows, which were skipped."""

    tables_created: int = 0
    rows_inserted: int = 0
    tables_skipped: list[str] = field(default_factory=list)


def build_sqlite(
    dump_stream: IO[bytes],
    output_path: Path,
    *,
    with_internal: bool = False,
    on_started: Callable[[], None] | None = None,
) -> BuildStats:
    """Stream-source variant: parse `dump_stream` then call `build_sqlite_from_events`.

    Retained for the Datadump-direct fallback path (`source='datadump'`
    on the orchestrator). Per WORK_PLAN §4d the MariaDB cache path
    becomes the default, and that path goes through
    `build_sqlite_from_events` directly with a MariaDB-sourced
    iterable. Shape / contract are otherwise identical.
    """
    return build_sqlite_from_events(
        parse_dump(dump_stream),
        output_path,
        with_internal=with_internal,
        on_started=on_started,
    )


def build_sqlite_from_events(
    events: Iterable[TableSchema | Row],
    output_path: Path,
    *,
    with_internal: bool = False,
    on_started: Callable[[], None] | None = None,
) -> BuildStats:
    """Consume a TableSchema/Row event stream, write `output_path`, return stats.

    `output_path` is overwritten if it exists. The destination is opened
    with WAL disabled and synchronous=OFF for the duration of the bulk
    load — same trick mysqldump-to-sqlite tools use to avoid fsync-per-
    transaction overhead on millions of rows.

    `with_internal=False` (the default, matching Laravel's
    `--with-internal` flag default) skips tables whose name starts with
    `CBDB__`. Set to True to include them.

    `on_started` (optional) fires AFTER the destructive overwrite step
    has crossed the point of no return — i.e. after the prior file (if
    any) is removed and we are about to (or have just begun to) write
    the new one. A caller using `on_started` to gate partial-write
    cleanup can therefore distinguish "build never touched the
    destination" (callback never fires, previous artifact still valid)
    from "build started writing then failed" (callback fired, partial
    output needs cleanup).

    Events are typically produced either by
    `cbdb_parity.mysqldump.parse_dump()` (Datadump-direct) or
    `cbdb_parity.mariadb_source.iter_events()` (MariaDB cache path).
    """
    if output_path.exists():
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Crossed the destructive boundary: any prior good file is now gone.
    # Fire the started signal BEFORE sqlite3.connect creates the new
    # empty file so the caller's cleanup is armed even if connect itself
    # raises (rare but possible on permission / disk-full errors).
    if on_started is not None:
        on_started()

    stats = BuildStats()
    conn = sqlite3.connect(output_path)
    try:
        # Bulk-load tuning. PRAGMAs are session-scoped and don't persist
        # into the file, so the resulting sqlite is a normal durable DB.
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -65536")  # 64 MiB cache (negative = KiB)

        _drain(events, conn, stats, with_internal=with_internal)
        conn.commit()
    finally:
        conn.close()
    return stats


def _drain(
    events: Iterable[TableSchema | Row],
    conn: sqlite3.Connection,
    stats: BuildStats,
    *,
    with_internal: bool,
) -> None:
    """Consume the parser event stream into `conn`."""
    table_columns: dict[str, tuple[Column, ...]] = {}
    skipped: set[str] = set()
    batch: list[tuple[int | float | str | None, ...]] = []
    batch_table: str | None = None
    batch_insert_sql: str | None = None

    def flush() -> None:
        nonlocal batch, batch_insert_sql, batch_table
        if not batch or batch_insert_sql is None:
            return
        conn.executemany(batch_insert_sql, batch)
        stats.rows_inserted += len(batch)
        batch = []

    for ev in events:
        if isinstance(ev, TableSchema):
            # Switching tables — flush the current batch first.
            flush()
            if not with_internal and ev.name.startswith(_INTERNAL_PREFIX):
                stats.tables_skipped.append(ev.name)
                skipped.add(ev.name)
                continue
            conn.execute(_create_table_sql(ev))
            table_columns[ev.name] = ev.columns
            stats.tables_created += 1
            placeholders = ", ".join("?" * len(ev.columns))
            cols_quoted = ", ".join(f'"{c.name}"' for c in ev.columns)
            batch_insert_sql = (
                f'INSERT INTO "{ev.name}" ({cols_quoted}) VALUES ({placeholders})'
            )
            batch_table = ev.name
            continue

        # Row event
        if ev.table in skipped:
            continue
        if ev.table not in table_columns:
            # mysqldump always emits CREATE before INSERT for the same
            # table; a row before its schema means the dump is malformed
            # in a way we cannot recover from.
            raise RuntimeError(
                f"INSERT for table `{ev.table}` arrived before its CREATE TABLE"
            )
        if ev.table != batch_table:
            # Cross-table interleaving (rare but mysqldump can emit it
            # for a re-issued INSERT). Flush before re-aiming the batch.
            flush()
            cols = table_columns[ev.table]
            placeholders = ", ".join("?" * len(cols))
            cols_quoted = ", ".join(f'"{c.name}"' for c in cols)
            batch_insert_sql = (
                f'INSERT INTO "{ev.table}" ({cols_quoted}) VALUES ({placeholders})'
            )
            batch_table = ev.table

        batch.append(ev.values)
        if len(batch) >= _BATCH_ROWS:
            flush()

    flush()


def _write_manifest(
    manifest_path: Path,
    info: DatadumpInfo,
    sha: str,
    out_path: Path,
    stats: BuildStats,
    elapsed: float,
) -> None:
    """Merge the sqlite product info into `build_manifest.json` so every
    cbdb.sqlite produced by this CLI has provenance pinned to a Datadump.

    Critical invariant: every entry in `products` came from the same
    Datadump SHA recorded at the top level. If the existing manifest
    references a DIFFERENT SHA, we discard the stale `products` block —
    otherwise downstream reports would believe both mdb and sqlite came
    from the new dump even when only sqlite was rebuilt.
    """
    payload: dict[str, object]
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    else:
        payload = {}

    existing_sha = (
        payload.get("datadump", {}).get("sha256") if isinstance(payload.get("datadump"), dict) else None
    )
    if existing_sha is not None and existing_sha != sha:
        # Datadump has changed since the last write — anything in
        # `products` came from the OLD dump and is now stale. Drop it.
        payload.pop("products", None)

    payload["version"] = 1
    payload["datadump"] = {
        "filename": info.filename,
        "sha256": sha,
        "date_tag": info.date_tag,
    }
    products = payload.setdefault("products", {})
    assert isinstance(products, dict)
    products["sqlite"] = {
        "path": str(out_path),
        "tables_created": stats.tables_created,
        "tables_skipped": stats.tables_skipped,
        "rows_inserted": stats.rows_inserted,
        "built_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        # Stamped so build_all's cache check (which now gates on
        # builder_version) reuses standalone-built sqlite without
        # rebuilding. Must stay in sync with
        # `cbdb_parity.build_all._SQLITE_BUILDER_VERSION`.
        "builder_version": "1.2-python-port",
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def cli_main() -> int:
    """Console-script entry point: build cbdb.sqlite from the newest Datadump.

    On success, updates `build_manifest.json` (under the repo root) with
    the source archive's filename + SHA so reports can tie back to a
    specific data version.

    NOTE: this CLI does NOT call `cbdb_parity.refresh.refresh_all()` —
    cross-repo refresh is the orchestrator's responsibility (Phase 1.4's
    `build_all`). Running `cbdb-parity-build-sqlite` is a sub-tool, useful
    when only the SQLite half needs rebuilding (e.g. iterating on the
    Avalonia query layer); the parity-comparison entrypoint refreshes
    upstream first.

    Exit codes:
      0 — build complete, manifest written
      1 — build failed (dump parse error, sqlite error, OS error)
      2 — .env config error or no Datadump found
    """
    try:
        cfg = load_config()
        info = find_latest_datadump(cfg.datadump_dir)
    except (ConfigError, DatadumpError) as exc:
        print(f"config / discovery error: {exc}", file=sys.stderr)
        return 2

    out_path = cfg.build_output_dir / "cbdb.sqlite"
    archive_mb = info.path.stat().st_size / (1 << 20)
    print(f"Source       : {info.path}  ({archive_mb:,.1f} MB compressed)")
    print(f"Target       : {out_path}")
    print(f"Date         : {info.date_tag}")
    print(f"Hashing source archive ({archive_mb:.0f} MB, ~1s)...")
    sha = info.sha256
    print(f"SHA256       : {sha}")
    print()

    t0 = time.time()
    try:
        with open_dump_stream(info) as stream:
            stats = build_sqlite(stream, out_path)
    except (MysqlDumpError, RuntimeError, sqlite3.Error, OSError) as exc:
        print(f"build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0

    # Manifest sits at the workspace root (next to .env), discovered
    # via find_dotenv so non-editable installs don't end up writing
    # provenance under site-packages. Same helper used by
    # `cbdb_parity.mdb_builder` and `cbdb_parity.build_all` — keeps
    # the standalone CLIs and the orchestrator pointed at the same
    # manifest file.
    from cbdb_parity.mdb_builder import _workspace_root_manifest_path
    manifest_path = _workspace_root_manifest_path()
    try:
        _write_manifest(manifest_path, info, sha, out_path, stats, elapsed)
    except OSError as exc:
        print(f"warning: could not write {manifest_path}: {exc}", file=sys.stderr)

    print(f"Tables created : {stats.tables_created}")
    print(f"Tables skipped : {len(stats.tables_skipped)} (CBDB__* internal)")
    print(f"Rows inserted  : {stats.rows_inserted:,}")
    print(f"Elapsed        : {elapsed:.1f}s ({stats.rows_inserted / max(elapsed, 0.001):,.0f} rows/s)")
    print(f"Output         : {out_path}  ({out_path.stat().st_size / (1<<20):,.1f} MB)")
    print(f"Manifest       : {manifest_path}")
    return 0
