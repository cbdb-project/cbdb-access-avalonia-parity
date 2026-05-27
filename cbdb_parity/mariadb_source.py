"""MariaDB → (TableSchema | Row) event source (Phase 1.6b, §4d).

The two builders consume an iterable of TableSchema + Row events from
`cbdb_parity.mysqldump.parse_dump()` to write their products. This
module produces the SAME event shape by SELECT-ing each table out of
a MariaDB connection, so both builders can swap data sources by
swapping iterables — no change to `_drain()` machinery on either side.

Why this exists: Phase 1.6's MariaDB cache holds the Datadump rows
in structured form. SELECT-ing rows is dramatically faster than
re-parsing the mysqldump text from the .tar.gz on every build, and
the existing `_drain()` already handles the schema-then-rows
ordering invariant the dump parser guarantees.

Schema inference:
  - Column names and MySQL type strings come from
    `INFORMATION_SCHEMA.COLUMNS` (ORDINAL_POSITION-ordered).
  - Each table is SELECT-ed in primary-key / ORDINAL_POSITION order
    so per-run output is deterministic.

Skip-list semantics match `cbdb_parity.mysqldump.parse_dump()`'s
position: CBDB__* tables and the notebook SKIP_TABLES list are
filtered AT THE BUILDER level (sqlite_builder._drain / mdb_builder.
_drain), so this source can yield every table and the builders apply
their own filters.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cbdb_parity.mysqldump import Column, Row, TableSchema

# The provenance table is internal to Phase 1.6's MariaDB cache; the
# builders should never see it (it would confuse downstream parity
# checks that count tables). Filtered out at the source.
_INTERNAL_PROVENANCE_TABLE = "_cbdb_parity_provenance"


def _fetch_table_names(conn: Any, database: str) -> list[str]:
    """List every table in `database`, ordered alphabetically.

    The mysqldump emit order in CBDB is alphabetical (modulo a few
    historical exceptions); mirroring that here keeps per-table commit
    boundaries comparable across the two builder paths.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME",
            (database,),
        )
        return [row[0] for row in cur.fetchall() if row[0] != _INTERNAL_PROVENANCE_TABLE]


def _fetch_columns(conn: Any, database: str, table: str) -> tuple[Column, ...]:
    """Return the column tuple in SELECT-positional order.

    `COLUMN_TYPE` carries the full type expression (e.g.
    `varchar(255)`, `int(11)`, `bigint(20) unsigned`) — exactly the
    same surface that `mysqldump`'s `CREATE TABLE` emits and that the
    builders' type translators (`mysql_type_to_sqlite`, `mysql_type_
    to_access`) already know how to consume. Anything else (column
    comments, character sets) is dropped — the builders ignore them
    too.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
            (database, table),
        )
        return tuple(Column(name=row[0], sql_type=row[1]) for row in cur.fetchall())


def _iter_rows(conn: Any, table: str, columns: tuple[Column, ...]) -> Iterable[Row]:
    """Yield Row events for `table`. Streams via a server-side cursor
    (`SSCursor`) so memory stays bounded on tables with millions of
    rows. Falls back to a buffered cursor if `pymysql.cursors.SSCursor`
    isn't available (e.g. mocked tests).
    """
    try:
        import pymysql.cursors
        cur = conn.cursor(pymysql.cursors.SSCursor)
    except (ImportError, AttributeError):
        cur = conn.cursor()
    try:
        # Backtick-quote the table name; CBDB has no funny characters
        # in identifiers but defensive quoting matches what mysqldump
        # itself writes into the dump.
        cur.execute(f"SELECT * FROM `{table}`")
        for row in cur:
            yield Row(table=table, values=tuple(row))
    finally:
        cur.close()


def iter_events(
    conn: Any,
    database: str,
) -> Iterable[TableSchema | Row]:
    """Yield (TableSchema, Row, Row, ..., TableSchema, Row, ...) for
    every base table in `database`, mirroring `parse_dump()`'s shape.

    Each table emits exactly one TableSchema event followed by N Row
    events. The `_drain()` consumers in sqlite_builder / mdb_builder
    already rely on this ordering invariant; we preserve it here so
    the rest of the build path is data-source-agnostic.
    """
    for table in _fetch_table_names(conn, database):
        columns = _fetch_columns(conn, database, table)
        # Synthetic create_sql kept empty: the builders re-derive their
        # own CREATE TABLE from the TableSchema's columns, so the raw
        # bytes mysqldump emits aren't used. (The parser populates it
        # only because the bytes are already on the wire there.)
        yield TableSchema(name=table, columns=columns, create_sql=b"")
        yield from _iter_rows(conn, table, columns)


__all__ = ["iter_events"]
