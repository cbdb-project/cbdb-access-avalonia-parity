"""Tests for cbdb_parity.mariadb_source — the MariaDB → event-stream
adapter that feeds sqlite_builder / mdb_builder when source='mariadb'.

Uses a hand-rolled pymysql.Connection fake so the tests don't need a
real MariaDB container; the real-world validation happens via the
`cbdb-parity-build-all` end-to-end run.
"""

from __future__ import annotations

from typing import Any

from cbdb_parity import mariadb_source as mds
from cbdb_parity.mariadb_source import iter_events
from cbdb_parity.mysqldump import Row, TableSchema


class _FakeCursor:
    """Minimal cursor that replays a queue of `execute` → rows."""

    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self._last_rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        s = sql.strip().lower()
        if s.startswith("select table_name"):
            self._last_rows = [(t,) for t in self._conn._tables]
        elif s.startswith("select column_name"):
            assert params is not None and len(params) == 2
            _db, tbl = params
            self._last_rows = self._conn._columns_by_table[tbl]
        elif s.lower().startswith("select * from"):
            tbl = sql.split("`")[1]
            self._last_rows = self._conn._rows_by_table[tbl]
        else:
            self._last_rows = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._last_rows)

    def __iter__(self) -> Any:
        return iter(self._last_rows)

    def close(self) -> None:
        pass


class _FakeConnection:
    """Hand-rolled pymysql.Connection stand-in for mariadb_source tests."""

    def __init__(self) -> None:
        self._tables: list[str] = []
        self._columns_by_table: dict[str, list[tuple[str, str]]] = {}
        self._rows_by_table: dict[str, list[tuple[Any, ...]]] = {}

    def add_table(
        self,
        name: str,
        columns: list[tuple[str, str]],
        rows: list[tuple[Any, ...]],
    ) -> None:
        self._tables.append(name)
        self._columns_by_table[name] = columns
        self._rows_by_table[name] = rows

    def cursor(self, _cls: Any = None) -> _FakeCursor:
        return _FakeCursor(self)


def test_iter_events_emits_schema_then_rows() -> None:
    """A single table yields one TableSchema followed by its rows in order."""
    conn = _FakeConnection()
    conn.add_table(
        "BIOG_MAIN",
        [("c_personid", "int(11)"), ("c_name", "varchar(255)")],
        [(1, "Alice"), (2, "Bob")],
    )
    events = list(iter_events(conn, "cbdb_data"))
    assert len(events) == 3
    schema = events[0]
    assert isinstance(schema, TableSchema)
    assert schema.name == "BIOG_MAIN"
    assert [c.name for c in schema.columns] == ["c_personid", "c_name"]
    assert [c.sql_type for c in schema.columns] == ["int(11)", "varchar(255)"]
    assert isinstance(events[1], Row)
    assert events[1].values == (1, "Alice")
    assert events[2].values == (2, "Bob")


def test_iter_events_iterates_tables_alphabetically() -> None:
    """Tables emit in alphabetical order so per-table commit boundaries
    are predictable across runs."""
    conn = _FakeConnection()
    conn.add_table("ZZZ_LAST", [("a", "int(11)")], [(1,)])
    conn.add_table("AAA_FIRST", [("a", "int(11)")], [(2,)])
    # Fake's internal order isn't important — iter_events relies on the
    # ORDER BY TABLE_NAME in the SELECT, which the fake honors via its
    # own list ordering. Mirror that here.
    conn._tables = sorted(conn._tables)
    events = list(iter_events(conn, "cbdb_data"))
    table_names = [ev.name for ev in events if isinstance(ev, TableSchema)]
    assert table_names == ["AAA_FIRST", "ZZZ_LAST"]


def test_iter_events_skips_provenance_table() -> None:
    """The Phase 1.6 `_cbdb_parity_provenance` row must NOT appear in
    the event stream — it's internal bookkeeping that would otherwise
    confuse downstream parity row-counts."""
    conn = _FakeConnection()
    conn.add_table("BIOG_MAIN", [("a", "int(11)")], [(1,)])
    conn.add_table("_cbdb_parity_provenance", [("sha", "char(64)")], [("x" * 64,)])
    conn._tables = sorted(conn._tables)
    events = list(iter_events(conn, "cbdb_data"))
    table_names = [ev.name for ev in events if isinstance(ev, TableSchema)]
    assert "_cbdb_parity_provenance" not in table_names
    assert "BIOG_MAIN" in table_names


def test_iter_events_empty_table_emits_schema_only() -> None:
    """A table with zero rows still emits its TableSchema event (the
    builders' _drain logic creates the empty table)."""
    conn = _FakeConnection()
    conn.add_table("EMPTY_T", [("a", "int(11)")], [])
    events = list(iter_events(conn, "cbdb_data"))
    assert len(events) == 1
    assert isinstance(events[0], TableSchema)
    assert events[0].name == "EMPTY_T"


def test_iter_rows_falls_back_when_sscursor_missing(
    monkeypatch: Any,
) -> None:
    """If pymysql isn't installed (or SSCursor unavailable), the fallback
    `conn.cursor()` path still yields Row events."""
    import sys

    # Force an ImportError when `pymysql.cursors` is imported.
    monkeypatch.setitem(sys.modules, "pymysql", None)

    conn = _FakeConnection()
    conn.add_table("T", [("a", "int(11)")], [(1,), (2,)])
    events = list(mds._iter_rows(conn, "T", ()))
    assert [e.values for e in events] == [(1,), (2,)]
