"""Datadump → cbdb_data.mdb builder (Phase 1.3b).

Parallel to `cbdb_parity.sqlite_builder`. Same streaming-consumer shape
on the Datadump side; different destination (Microsoft Access via
pyodbc) with `pypyodbc.win_create_mdb` for the one-time empty-mdb
bootstrap.

Phase 1.3b is on the critical path for Phase 3 per WORK_PLAN §1's
strict-pipeline rule: pre-existing local mdb files are NOT acceptable
substitutes for the output of this builder.

pypyodbc and pyodbc imports are lazy (inside `build_mdb`) so module
import works on non-Windows and in tests that stub the connection.
"""

from __future__ import annotations

import json
import sys
import tarfile
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol

from cbdb_parity.access_schema import (
    AccessSchema,
    AccessSchemaError,
    load_access_schema,
)
from cbdb_parity.access_types import mysql_type_to_access
from cbdb_parity.config import ConfigError, load_config
from cbdb_parity.datadump import (
    DatadumpError,
    DatadumpInfo,
    find_latest_datadump,
    open_dump_stream,
)
from cbdb_parity.mysqldump import Column, MysqlDumpError, Row, TableSchema, parse_dump

# Access DataFormat (from TablesFields.xlsx) → ODBC CREATE TABLE token.
# `cbdb_parity.access_schema._VALID_TYPES` is {Long, Integer, Double, Text,
# Memo, Binary}. Long is Access's 32-bit int, Integer the 16-bit one,
# Memo the unlimited-text blob.
_DATA_FORMAT_TO_ODBC: dict[str, str] = {
    "Long": "INTEGER",
    "Integer": "SMALLINT",
    "Double": "DOUBLE",
    "Text": "VARCHAR(255)",
    "Memo": "LONGTEXT",
    "Binary": "LONGBINARY",
}

# Tables that the Laravel ops stack uses but CBDB's Access stack doesn't
# need — copied verbatim from `mysql2access.ipynb` cell 3 plus the
# `CBDB__*` prefix that the sqlite_builder already filters.
_NOTEBOOK_SKIP_TABLES: frozenset[str] = frozenset({
    "users",
    "operations",
    "password_resets",
    "personal_access_tokens",
    "pinyin",
    "migrations",
    "oauth_access_tokens",
    "oauth_auth_codes",
    "oauth_clients",
    "oauth_personal_access_clients",
    "oauth_refresh_tokens",
    "audit_log",
    "ai_fill_logs",
    "nl_query_logs",
})

_INTERNAL_PREFIX = "CBDB__"

# Access via pyodbc handles batched INSERT well; mysql2access.ipynb's
# row-by-row execute was the slow bit on millions of rows. Same batch
# size we use in sqlite_builder.
_BATCH_ROWS = 1000


class MdbBuilderError(RuntimeError):
    """Raised on a builder failure that isn't a parser/SQL error."""


class _NoSuchError(BaseException):
    """Sentinel never raised anywhere — used as the absent-class
    placeholder in `except (..., driver_error, ...)` tuples when the
    driver library is missing. Python requires every element of an
    except-tuple to be a BaseException subclass; `_NoSuchError`
    satisfies that contract without ever actually matching."""


@dataclass(slots=True)
class BuildStats:
    """Per-build summary: how many tables, how many rows, which were skipped."""

    tables_created: int = 0
    rows_inserted: int = 0
    tables_skipped: list[str] = field(default_factory=list)


# --- value normalisation ----------------------------------------------------

# Special bytes that mysqldump emits for tinyint(1) / BIT columns.
# `mysql2access.ipynb` cell 2 normalises these because the Access ODBC
# driver chokes on bytes-typed parameters. The parser already decodes
# most of MySQL's escape sequences into str/int/float; bytes here would
# come from a row we couldn't classify any other way, but keep the
# safety net.
_BYTE_FALSE = b"\x00"
_BYTE_TRUE = b"\x01"
# After the parser's `\0` / `\x01` mysqldump escape decoding, BIT-like
# values arrive as Python `str` with a single NUL or SOH code-point,
# NOT as `bytes` (parser uses `bytearray.decode("utf-8")`). We map
# either form to 0/1 so Access SMALLINT binds cleanly.
_STR_FALSE = "\x00"
_STR_TRUE = "\x01"
# Both DATE-only and DATETIME zero sentinels need to be normalised — the
# Access driver rejects "0000-00-00 00:00:00" AND the bare "0000-00-00"
# that mysqldump emits for zero DATE values.
_ZERO_DATE_SENTINELS = frozenset({"0000-00-00 00:00:00", "0000-00-00"})


def _normalise_value(v: Any) -> Any:
    """Coerce per-cell values into something Access ODBC accepts."""
    if isinstance(v, bytes):
        if v == _BYTE_FALSE:
            return 0
        if v == _BYTE_TRUE:
            return 1
        # Fall through to driver — extremely unlikely in CBDB
        return v
    if isinstance(v, str):
        # BIT-like escapes that the parser decoded to a single-char str.
        if v == _STR_FALSE:
            return 0
        if v == _STR_TRUE:
            return 1
        if v in _ZERO_DATE_SENTINELS:
            # MySQL's "no date" sentinels; Access raises if asked to store them.
            return None
    return v


def _create_table_sql(schema: TableSchema, access_schema: AccessSchema | None = None) -> str:
    """Render a CREATE TABLE statement for Microsoft Access ODBC.

    Identifier quoting uses Access's `[name]` form because some CBDB
    column names (e.g. `belongs1_ID`) are case-sensitive in Access if
    not bracketed.

    When `access_schema` is provided AND it has an entry for this
    table, the TablesFields.xlsx overlay applies:
      - per-column DataFormat overrides the MySQL-derived type (xlsx
        entries with blank DataFormat fall back to MySQL-derived)
      - per-column `nullable=False` adds `NOT NULL`
      - any column flagged `is_primary_key` joins a trailing
        `PRIMARY KEY (...)` clause
    Columns present in the Datadump but absent from the xlsx pass
    through unchanged — the xlsx is an OVERLAY, not a replacement (the
    real xlsx covers only ~12 of BIOG_MAIN's 40+ columns).
    """
    overlay = access_schema.tables.get(schema.name) if access_schema else None
    overlay_cols = {c.name: c for c in overlay.columns} if overlay else {}

    col_defs: list[str] = []
    for c in schema.columns:
        ovl = overlay_cols.get(c.name)
        if ovl is not None and ovl.data_format and ovl.data_format in _DATA_FORMAT_TO_ODBC:
            access_type = _DATA_FORMAT_TO_ODBC[ovl.data_format]
        else:
            access_type = mysql_type_to_access(c.sql_type)
        not_null = " NOT NULL" if ovl is not None and not ovl.nullable else ""
        col_defs.append(f"[{c.name}] {access_type}{not_null}")

    pk_clause = ""
    if overlay is not None:
        pk_cols = [c.name for c in overlay.columns if c.is_primary_key]
        # Only emit PK if every PK-flagged column actually exists in the
        # Datadump CREATE TABLE — protects against xlsx drift.
        dump_col_names = {c.name for c in schema.columns}
        if pk_cols and all(n in dump_col_names for n in pk_cols):
            quoted = ", ".join(f"[{n}]" for n in pk_cols)
            pk_clause = f",\n    PRIMARY KEY ({quoted})"

    sep = ",\n    "
    return (
        f'CREATE TABLE [{schema.name}] (\n    '
        f'{sep.join(col_defs)}{pk_clause}\n);'
    )


# --- connection plumbing (injectable for tests) -----------------------------

class _Cursor(Protocol):
    def execute(self, sql: str, *params: Any) -> Any: ...
    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> Any: ...
    def close(self) -> None: ...


class _Connection(Protocol):
    def cursor(self) -> _Cursor: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


# `CreateDbFn` is `(path: Path) -> None`; `ConnectFn` is
# `(path: Path) -> _Connection`. Default to pypyodbc.win_create_mdb /
# pyodbc.connect, but tests inject fakes.
def _default_create_db(path: Path) -> None:
    import pypyodbc  # lazy

    pypyodbc.win_create_mdb(str(path))


def _default_connect(path: Path) -> _Connection:
    import pyodbc  # lazy

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={path};"
    )
    return pyodbc.connect(conn_str)


def build_mdb(
    dump_stream: IO[bytes],
    output_path: Path,
    *,
    with_internal: bool = False,
    access_schema: AccessSchema | None = None,
    create_db: Any = None,
    connect: Any = None,
) -> BuildStats:
    """Stream `dump_stream` through the parser, write `output_path`, return stats.

    `output_path` is overwritten if it exists. The mdb is bootstrapped
    fresh via `create_db` (default `pypyodbc.win_create_mdb`); all
    CREATE TABLE / INSERT operations go through the pyodbc connection
    returned by `connect` (default Microsoft Access Driver).

    `with_internal=False` (the default, matching the sqlite_builder and
    the Laravel `--with-internal` flag) skips tables whose name starts
    with `CBDB__`. Additionally, the SKIP_TABLES list from
    `mysql2access.ipynb` cell 3 (oauth_*, migrations, audit_log, etc.)
    is always skipped regardless of `with_internal` — those are Laravel
    bookkeeping, not CBDB data.

    `access_schema` is the optional TablesFields.xlsx overlay loaded by
    `cbdb_parity.access_schema.load_access_schema`. Per WORK_PLAN §4a
    the xlsx is canonical for any column it declares — types, primary
    keys, nullability. Columns NOT in the xlsx fall back to the
    MySQL-derived type from `mysql_type_to_access`. `cli_main` loads it
    from `$ACCESS_MYSQL_TRANSFER_REPO/TablesFields.xlsx`; library
    callers either pass their own or pass `None` to skip overlay.

    `create_db` / `connect` are injectable for tests; production callers
    leave them as None and get the real pypyodbc / pyodbc behaviour.
    """
    create_db = create_db or _default_create_db
    connect_fn = connect or _default_connect

    if output_path.exists():
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Bootstrap empty mdb (the only step pypyodbc handles).
    create_db(output_path)

    # 2. Open the modern pyodbc connection and drive CREATE/INSERT.
    stats = BuildStats()
    conn = connect_fn(output_path)
    try:
        cursor = conn.cursor()
        try:
            _drain(
                parse_dump(dump_stream),
                cursor,
                conn,
                stats,
                with_internal=with_internal,
                access_schema=access_schema,
            )
            conn.commit()
        finally:
            cursor.close()
    finally:
        conn.close()
    return stats


def _drain(
    events: Iterable[TableSchema | Row],
    cursor: _Cursor,
    conn: _Connection,
    stats: BuildStats,
    *,
    with_internal: bool,
    access_schema: AccessSchema | None = None,
) -> None:
    """Consume the parser event stream into `cursor`."""
    table_columns: dict[str, tuple[Column, ...]] = {}
    skipped: set[str] = set()
    batch: list[tuple[Any, ...]] = []
    batch_table: str | None = None
    batch_insert_sql: str | None = None

    def flush() -> None:
        nonlocal batch
        if not batch or batch_insert_sql is None:
            return
        cursor.executemany(batch_insert_sql, batch)
        stats.rows_inserted += len(batch)
        batch = []

    for ev in events:
        if isinstance(ev, TableSchema):
            flush()
            # Skip both CBDB__* (matching sqlite_builder default) and the
            # Laravel ops tables hard-listed in the notebook. The
            # `with_internal` flag only affects the CBDB__ check —
            # ops/audit tables are never useful in the CBDB Access stack.
            if (not with_internal and ev.name.startswith(_INTERNAL_PREFIX)) or ev.name.lower() in _NOTEBOOK_SKIP_TABLES:
                stats.tables_skipped.append(ev.name)
                skipped.add(ev.name)
                continue
            cursor.execute(_create_table_sql(ev, access_schema))
            table_columns[ev.name] = ev.columns
            stats.tables_created += 1
            placeholders = ", ".join("?" * len(ev.columns))
            cols_quoted = ", ".join(f"[{c.name}]" for c in ev.columns)
            batch_insert_sql = (
                f"INSERT INTO [{ev.name}] ({cols_quoted}) VALUES ({placeholders})"
            )
            batch_table = ev.name
            continue

        # Row event
        if ev.table in skipped:
            continue
        if ev.table not in table_columns:
            raise MdbBuilderError(
                f"INSERT for table `{ev.table}` arrived before its CREATE TABLE"
            )
        if ev.table != batch_table:
            flush()
            cols = table_columns[ev.table]
            placeholders = ", ".join("?" * len(cols))
            cols_quoted = ", ".join(f"[{c.name}]" for c in cols)
            batch_insert_sql = (
                f"INSERT INTO [{ev.table}] ({cols_quoted}) VALUES ({placeholders})"
            )
            batch_table = ev.table

        batch.append(tuple(_normalise_value(v) for v in ev.values))
        if len(batch) >= _BATCH_ROWS:
            flush()

    flush()


# --- manifest write (mirrors sqlite_builder._write_manifest) ----------------

def _write_manifest(
    manifest_path: Path,
    info: DatadumpInfo,
    sha: str,
    out_path: Path,
    stats: BuildStats,
    elapsed: float,
) -> None:
    """Merge the mdb product entry into build_manifest.json.

    SHA-change invariant matches sqlite_builder: if the existing manifest
    is for a DIFFERENT SHA, the stale `products` block is discarded so
    we don't stamp old siblings with the new dump's provenance.
    """
    payload: dict[str, Any]
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, OSError):
            payload = {}
    else:
        payload = {}

    existing_dd = payload.get("datadump") if isinstance(payload.get("datadump"), dict) else None
    if existing_dd is not None and existing_dd.get("sha256") != sha:
        payload.pop("products", None)

    payload["version"] = 1
    payload["datadump"] = {
        "filename": info.filename,
        "sha256": sha,
        "date_tag": info.date_tag,
    }
    products = payload.setdefault("products", {})
    assert isinstance(products, dict)
    products["mdb"] = {
        "path": str(out_path),
        "tables_created": stats.tables_created,
        "tables_skipped": stats.tables_skipped,
        "rows_inserted": stats.rows_inserted,
        "built_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def cli_main() -> int:
    """Console-script entry point: build cbdb_data.mdb from the newest Datadump.

    Mirrors `cbdb_parity.sqlite_builder.cli_main` in shape and exit
    codes. Does NOT refresh external repos — that's the orchestrator's
    responsibility (Phase 1.4 `cbdb-parity-build-all`).

    Exit codes:
      0 — build complete, manifest written
      1 — build failed (parser error, pyodbc error, OS error, etc.)
      2 — .env config error or no Datadump found
    """
    try:
        cfg = load_config()
        info = find_latest_datadump(cfg.datadump_dir)
    except (ConfigError, DatadumpError) as exc:
        print(f"config / discovery error: {exc}", file=sys.stderr)
        return 2

    # Load the canonical Access schema overlay. Required for parity with
    # what Access queries expect.
    xlsx_path = cfg.access_mysql_transfer_repo / "TablesFields.xlsx"
    try:
        schema_overlay = load_access_schema(xlsx_path)
    except AccessSchemaError as exc:
        print(f"access schema error: {exc}", file=sys.stderr)
        return 2

    out_path = cfg.build_output_dir / "cbdb_data.mdb"
    archive_mb = info.path.stat().st_size / (1 << 20)
    print(f"Source       : {info.path}  ({archive_mb:,.1f} MB compressed)")
    print(f"Target       : {out_path}")
    print(f"Date         : {info.date_tag}")
    print(f"Hashing source archive ({archive_mb:.0f} MB, ~1s)...")
    try:
        sha = info.sha256
    except OSError as exc:
        print(f"hashing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"SHA256       : {sha}")
    print()

    # Lazily import pyodbc/pypyodbc so we can include their Error classes
    # in the catch list. Both are Windows-only — if they're missing the
    # build will fail loudly with ImportError, which we also catch.
    #
    # The fallback uses a sentinel class (NOT an empty tuple): Python
    # validates every element of an `except (...)` tuple as a BaseException
    # subclass BEFORE checking which one matched, so an `()` element
    # would raise TypeError for ANY exception entering the try block —
    # poisoning the whole catch.
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

    print(f"Schema overlay : {xlsx_path} ({len(schema_overlay)} tables)")
    print()

    t0 = time.time()
    try:
        with open_dump_stream(info) as stream:
            stats = build_mdb(stream, out_path, access_schema=schema_overlay)
    except (
        MysqlDumpError,
        DatadumpError,
        tarfile.TarError,
        MdbBuilderError,
        OSError,
        ImportError,
        _pyodbc_error,
        _pypyodbc_error,
    ) as exc:
        print(f"build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0

    manifest_path = Path(__file__).resolve().parent.parent / "build_manifest.json"
    try:
        _write_manifest(manifest_path, info, sha, out_path, stats, elapsed)
    except OSError as exc:
        print(f"warning: could not write {manifest_path}: {exc}", file=sys.stderr)

    print(f"Tables created : {stats.tables_created}")
    print(f"Tables skipped : {len(stats.tables_skipped)}")
    print(f"Rows inserted  : {stats.rows_inserted:,}")
    print(f"Elapsed        : {elapsed:.1f}s ({stats.rows_inserted / max(elapsed, 0.001):,.0f} rows/s)")
    print(f"Output         : {out_path}  ({out_path.stat().st_size / (1<<20):,.1f} MB)")
    print(f"Manifest       : {manifest_path}")
    return 0
