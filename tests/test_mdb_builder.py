"""Tests for cbdb_parity.mdb_builder.

The real pyodbc / pypyodbc + Microsoft Access Driver path can't run in
CI (Windows-only, ODBC driver required). All tests inject fake
create_db + connect callables and verify the builder's logic
(table-list filtering, batching, value normalisation, error paths).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from cbdb_parity.mdb_builder import (
    BuildStats,
    MdbBuilderError,
    _create_table_sql,
    _normalise_value,
    build_mdb,
)
from cbdb_parity.mysqldump import Column, TableSchema

# ---------- helpers ----------

class _FakeCursor:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.executemany_calls: list[tuple[str, list[tuple[Any, ...]]]] = []
        self.closed = False

    def execute(self, sql: str, *params: Any) -> Any:
        self.execute_calls.append((sql, params))

    def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> Any:
        self.executemany_calls.append((sql, list(params)))

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_db():
    """Return a tuple of (create_db_fn, connect_fn, recorded_state).

    `recorded_state` is a dict with keys:
        created_path: Path | None  — the path passed to create_db
        connection: _FakeConnection — the connection returned by connect
    """
    state: dict[str, Any] = {"created_path": None, "connection": _FakeConnection()}

    def fake_create_db(path: Path) -> None:
        state["created_path"] = path
        # Simulate pypyodbc creating the file so build_mdb's later
        # `output_path.exists()` checks see it.
        path.write_bytes(b"\x00fake_mdb\x00")

    def fake_connect(path: Path):
        return state["connection"]

    return fake_create_db, fake_connect, state


def _build(dump_bytes: bytes, tmp_path: Path, fake_db, **kwargs: object) -> tuple[Path, BuildStats, _FakeConnection]:
    create_db, connect, state = fake_db
    out = tmp_path / "out.mdb"
    stats = build_mdb(
        io.BytesIO(dump_bytes),
        out,
        create_db=create_db,
        connect=connect,
        **kwargs,  # type: ignore[arg-type]
    )
    return out, stats, state["connection"]


# ---------- _create_table_sql + _normalise_value ----------

def test_create_table_sql_brackets_identifiers() -> None:
    sch = TableSchema(
        name="ADDRESSES",
        columns=(Column("c_addr_id", "int(11)"), Column("c_name_chn", "varchar(255)")),
        create_sql=b"",
    )
    sql = _create_table_sql(sch)
    assert "[ADDRESSES]" in sql
    assert "[c_addr_id] INTEGER" in sql
    assert "[c_name_chn] VARCHAR(255)" in sql


def _overlay_schema(tables: dict[str, list[tuple[str, str | None, bool, bool]]]):
    """Build a tiny AccessSchema for testing the overlay path.

    `tables` is `{table_name: [(col_name, data_format, nullable, is_pk), ...]}`.
    """
    from cbdb_parity.access_schema import AccessColumn, AccessSchema, AccessTable

    schema = AccessSchema()
    for tname, cols in tables.items():
        col_objs = tuple(
            AccessColumn(name=n, data_format=fmt, nullable=nul, is_primary_key=pk)
            for n, fmt, nul, pk in cols
        )
        schema.tables[tname] = AccessTable(name=tname, columns=col_objs)
    return schema


def test_create_table_sql_overlay_data_format_overrides_mysql_type() -> None:
    """When the xlsx declares a DataFormat for a column, the
    Access-canonical type wins over the MySQL-derived one."""
    dump_sch = TableSchema(
        name="T",
        columns=(
            Column("a", "bigint(20)"),       # MySQL would map to INTEGER
            Column("b", "longtext"),         # MySQL would map to LONGTEXT
        ),
        create_sql=b"",
    )
    overlay = _overlay_schema({
        "T": [
            ("a", "Long", True, False),       # canonical: Long → INTEGER
            ("b", "Memo", True, False),       # canonical: Memo → LONGTEXT (same)
        ],
    })
    sql = _create_table_sql(dump_sch, overlay)
    assert "[a] INTEGER" in sql
    assert "[b] LONGTEXT" in sql


def test_create_table_sql_overlay_blank_format_falls_back_to_mysql() -> None:
    """Real xlsx has a few rows with blank DataFormat (e.g.
    POSTED_TO_ADDR_DATA.c_personid). The overlay must NOT clobber the
    MySQL-derived type in those rows."""
    dump_sch = TableSchema(
        name="T",
        columns=(Column("c_personid", "int(11)"),),
        create_sql=b"",
    )
    overlay = _overlay_schema({
        "T": [("c_personid", None, True, False)],
    })
    sql = _create_table_sql(dump_sch, overlay)
    assert "[c_personid] INTEGER" in sql


def test_create_table_sql_overlay_emits_primary_key_clause() -> None:
    dump_sch = TableSchema(
        name="ADDR_BELONGS_DATA",
        columns=(
            Column("c_addr_id", "int(11)"),
            Column("c_belongs_to", "int(11)"),
            Column("c_first_year", "int(11)"),
        ),
        create_sql=b"",
    )
    overlay = _overlay_schema({
        "ADDR_BELONGS_DATA": [
            ("c_addr_id", "Long", False, True),
            ("c_belongs_to", "Long", False, True),
            ("c_first_year", "Long", True, False),
        ],
    })
    sql = _create_table_sql(dump_sch, overlay)
    # Both PK and NOT NULL clauses are intentionally suppressed even
    # when the overlay declares them — see mdb_builder._create_table_sql
    # for the rationale (Jet IntegrityError 23000 against PK-flagged
    # cols with duplicates in the Datadump; -3701 NOT NULL violation
    # against xlsx-flagged cols with NULL rows in the Datadump). Type
    # output (DataFormat → ODBC mapping) still applies.
    assert "PRIMARY KEY" not in sql
    assert "NOT NULL" not in sql
    assert "[c_addr_id] INTEGER" in sql
    assert "[c_belongs_to] INTEGER" in sql
    assert "[c_first_year] INTEGER" in sql


def test_create_table_sql_overlay_skips_pk_when_pk_col_not_in_dump() -> None:
    """If the xlsx flags a PK column the Datadump doesn't have (drift),
    skip the PK clause — emitting an invalid PK would crash CREATE TABLE."""
    dump_sch = TableSchema(
        name="T",
        columns=(Column("a", "int(11)"),),
        create_sql=b"",
    )
    overlay = _overlay_schema({
        "T": [
            ("a", "Long", True, False),
            ("missing_col", "Long", False, True),  # PK flag on a col not in dump
        ],
    })
    sql = _create_table_sql(dump_sch, overlay)
    assert "PRIMARY KEY" not in sql


def test_create_table_sql_no_overlay_uses_mysql_types_only() -> None:
    """When no overlay is provided, behaviour is identical to before:
    pure mysql_type_to_access output, no PK clause, no NOT NULL."""
    dump_sch = TableSchema(
        name="T",
        columns=(Column("a", "int(11)"), Column("b", "varchar(50)")),
        create_sql=b"",
    )
    sql = _create_table_sql(dump_sch, None)
    assert "[a] INTEGER" in sql
    assert "[b] VARCHAR(50)" in sql
    assert "PRIMARY KEY" not in sql
    assert "NOT NULL" not in sql


def test_build_mdb_with_overlay_keeps_types_without_pk_or_not_null(tmp_path: Path, fake_db) -> None:
    """End-to-end: build_mdb consumes the overlay's DataFormat (Long →
    INTEGER, Memo → LONGTEXT) but suppresses both PK and NOT NULL
    clauses on emission. Jet IntegrityError 23000 (duplicate PK) and
    -3701 (NOT NULL violation) would otherwise abort per-table commits
    on real CBDB Datadump rows."""
    dump = b"CREATE TABLE `T` (`id` int(11), `payload` text);INSERT INTO `T` VALUES (1,'x');"
    overlay = _overlay_schema({
        "T": [
            ("id", "Long", False, True),
            ("payload", "Memo", True, False),
        ],
    })
    create_db, connect, state = fake_db
    out = tmp_path / "out.mdb"
    build_mdb(io.BytesIO(dump), out, access_schema=overlay,
              create_db=create_db, connect=connect)
    create_sql = next(c[0] for c in state["connection"].cursor_obj.execute_calls if "CREATE TABLE" in c[0])
    assert "[id] INTEGER" in create_sql
    assert "[payload] LONGTEXT" in create_sql
    assert "PRIMARY KEY" not in create_sql
    assert "NOT NULL" not in create_sql


def test_normalise_value_bytes_bool() -> None:
    assert _normalise_value(b"\x00") == 0
    assert _normalise_value(b"\x01") == 1


def test_no_such_error_is_baseexception_subclass() -> None:
    """The sentinel class used as the absent-driver placeholder MUST
    inherit from BaseException — otherwise its presence in an
    `except (...)` tuple raises TypeError for every exception that
    enters the try block (Python validates all elements before
    matching)."""
    from cbdb_parity.mdb_builder import _NoSuchError
    assert issubclass(_NoSuchError, BaseException)
    # And it can sit in a real except tuple alongside a normal
    # exception without poisoning the catch.
    try:
        raise ValueError("test")
    except (_NoSuchError, ValueError) as e:
        assert str(e) == "test"


def test_normalise_value_str_nul_and_soh_bool() -> None:
    """The mysqldump parser decodes `\\0` and `\\x01` escapes into a
    Python str containing a single NUL/SOH code-point, NOT bytes.
    Access SMALLINT needs 0/1 not the raw control char string."""
    assert _normalise_value("\x00") == 0
    assert _normalise_value("\x01") == 1


def test_normalise_value_zero_datetime_to_none() -> None:
    assert _normalise_value("0000-00-00 00:00:00") is None


def test_normalise_value_zero_date_to_none() -> None:
    """Bare zero DATE sentinel must also normalise — Access DATETIME
    rejects '0000-00-00' the same way it rejects the datetime form."""
    assert _normalise_value("0000-00-00") is None


def test_normalise_value_passes_through_normal_values() -> None:
    assert _normalise_value(42) == 42
    assert _normalise_value("hello") == "hello"
    assert _normalise_value(None) is None
    assert _normalise_value(3.14) == 3.14


# ---------- end-to-end build (with fake db) ----------

def test_build_creates_table_and_inserts(tmp_path: Path, fake_db) -> None:
    dump = (
        b"CREATE TABLE `t` (`id` int(11), `name` varchar(50));"
        b"INSERT INTO `t` VALUES (1,'a'),(2,'b'),(3,'c');"
    )
    out, stats, conn = _build(dump, tmp_path, fake_db)

    assert out.exists()
    assert stats.tables_created == 1
    assert stats.rows_inserted == 3
    assert conn.committed
    assert conn.closed
    assert conn.cursor_obj.closed

    # CREATE TABLE was issued via .execute().
    create_calls = [c for c in conn.cursor_obj.execute_calls if "CREATE TABLE" in c[0]]
    assert len(create_calls) == 1
    assert "[t]" in create_calls[0][0]

    # INSERTs went via .executemany() with the 3-row batch.
    assert len(conn.cursor_obj.executemany_calls) == 1
    insert_sql, rows = conn.cursor_obj.executemany_calls[0]
    assert "INSERT INTO [t]" in insert_sql
    assert "[id]" in insert_sql and "[name]" in insert_sql
    assert rows == [(1, "a"), (2, "b"), (3, "c")]


def test_build_skips_cbdb_internal_tables_by_default(tmp_path: Path, fake_db) -> None:
    dump = (
        b"CREATE TABLE `BIOG_MAIN` (`id` int(11));"
        b"INSERT INTO `BIOG_MAIN` VALUES (1),(2);"
        b"CREATE TABLE `CBDB__internal` (`x` int(11));"
        b"INSERT INTO `CBDB__internal` VALUES (99);"
    )
    _out, stats, _conn = _build(dump, tmp_path, fake_db)
    assert stats.tables_created == 1
    assert stats.rows_inserted == 2
    assert stats.tables_skipped == ["CBDB__internal"]


def test_build_skips_notebook_ops_tables_always(tmp_path: Path, fake_db) -> None:
    """`oauth_clients`, `migrations`, `users`, etc. come from Laravel ops
    and are never useful in the CBDB Access stack. Skipped even when
    with_internal=True (which only opens the CBDB__ gate)."""
    dump = (
        b"CREATE TABLE `BIOG_MAIN` (`id` int(11));"
        b"INSERT INTO `BIOG_MAIN` VALUES (1);"
        b"CREATE TABLE `users` (`id` int(11));"
        b"INSERT INTO `users` VALUES (10);"
        b"CREATE TABLE `oauth_clients` (`id` int(11));"
        b"INSERT INTO `oauth_clients` VALUES (20);"
        b"CREATE TABLE `migrations` (`id` int(11));"
        b"INSERT INTO `migrations` VALUES (30);"
    )
    _out, stats, _conn = _build(dump, tmp_path, fake_db, with_internal=True)
    assert stats.tables_created == 1
    assert stats.rows_inserted == 1
    assert set(stats.tables_skipped) == {"users", "oauth_clients", "migrations"}


def test_build_with_internal_admits_cbdb_tables(tmp_path: Path, fake_db) -> None:
    dump = (
        b"CREATE TABLE `CBDB__a` (`x` int(11));"
        b"INSERT INTO `CBDB__a` VALUES (42);"
    )
    _out, stats, _conn = _build(dump, tmp_path, fake_db, with_internal=True)
    assert stats.tables_created == 1
    assert stats.rows_inserted == 1


def test_build_normalises_special_values(tmp_path: Path, fake_db) -> None:
    """`b'\\x00'` → 0 and `'0000-00-00 00:00:00'` → None pass through
    `_normalise_value` per the notebook's cell 2 logic."""
    # A row with a zero-datetime literal in the dump. The parser keeps
    # it as the string `"0000-00-00 00:00:00"`; the builder normalises
    # it to None before binding.
    dump = (
        b"CREATE TABLE `t` (`id` int(11), `created` datetime);"
        b"INSERT INTO `t` VALUES (1,'0000-00-00 00:00:00'),(2,'2024-01-01 12:00:00');"
    )
    _out, _stats, conn = _build(dump, tmp_path, fake_db)
    rows = conn.cursor_obj.executemany_calls[0][1]
    assert rows == [(1, None), (2, "2024-01-01 12:00:00")]


def test_build_batches_at_1000_rows(tmp_path: Path, fake_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2500-row INSERT exercises the batch-flush path."""
    import cbdb_parity.mdb_builder as mb_mod
    monkeypatch.setattr(mb_mod, "_BATCH_ROWS", 1000)

    rows_sql = ",".join(f"({i},'r{i}')" for i in range(2500))
    dump = (
        b"CREATE TABLE `t` (`id` int(11), `s` varchar(50));"
        b"INSERT INTO `t` VALUES " + rows_sql.encode() + b";"
    )
    _out, stats, conn = _build(dump, tmp_path, fake_db)
    assert stats.rows_inserted == 2500
    # 2500 / 1000 = 3 batches (1000 + 1000 + 500).
    assert len(conn.cursor_obj.executemany_calls) == 3
    batch_sizes = [len(rows) for _sql, rows in conn.cursor_obj.executemany_calls]
    assert batch_sizes == [1000, 1000, 500]


def test_build_flushes_on_cross_table_interleaving(tmp_path: Path, fake_db) -> None:
    dump = (
        b"CREATE TABLE `a` (`x` int(11));"
        b"INSERT INTO `a` VALUES (1);"
        b"CREATE TABLE `b` (`x` int(11));"
        b"INSERT INTO `b` VALUES (10);"
        b"INSERT INTO `a` VALUES (2);"
        b"INSERT INTO `b` VALUES (20);"
    )
    _out, stats, conn = _build(dump, tmp_path, fake_db)
    assert stats.rows_inserted == 4
    # 4 separate executemany calls because each INSERT targets a different
    # table than the previous batch_table.
    assert len(conn.cursor_obj.executemany_calls) == 4


def test_build_row_before_schema_raises(tmp_path: Path, fake_db) -> None:
    dump = b"INSERT INTO `orphan` VALUES (1);"
    out = tmp_path / "out.mdb"
    create_db, connect, _state = fake_db
    with pytest.raises(MdbBuilderError, match=r"before its CREATE TABLE"):
        build_mdb(io.BytesIO(dump), out, create_db=create_db, connect=connect)


def test_build_overwrites_existing_file(tmp_path: Path, fake_db) -> None:
    out = tmp_path / "out.mdb"
    out.write_bytes(b"\x00" * 100)
    dump = b"CREATE TABLE `t` (`x` int(11));INSERT INTO `t` VALUES (1);"
    create_db, connect, _state = fake_db
    build_mdb(io.BytesIO(dump), out, create_db=create_db, connect=connect)
    # The fake create_db rewrote the file with its sentinel bytes,
    # proving the old file was unlinked first.
    assert b"fake_mdb" in out.read_bytes()


def test_build_unicode_strings_pass_through(tmp_path: Path, fake_db) -> None:
    """Chinese strings must reach the cursor untouched — the parser
    decodes UTF-8, and bytes-to-str pass straight through to pyodbc."""
    dump = "CREATE TABLE `t` (`n` varchar(255));INSERT INTO `t` VALUES ('中華民國');".encode()
    _out, _stats, conn = _build(dump, tmp_path, fake_db)
    rows = conn.cursor_obj.executemany_calls[0][1]
    assert rows == [("中華民國",)]


def test_build_uses_brackets_not_backticks_in_sql(tmp_path: Path, fake_db) -> None:
    """Access ODBC wants `[name]`, not the MySQL backtick form. The
    sqlite_builder uses double-quotes; mdb_builder must use brackets."""
    dump = b"CREATE TABLE `t` (`id` int(11));INSERT INTO `t` VALUES (1);"
    _out, _stats, conn = _build(dump, tmp_path, fake_db)
    all_sql = "\n".join(c[0] for c in conn.cursor_obj.execute_calls)
    all_sql += "\n".join(c[0] for c in conn.cursor_obj.executemany_calls)
    assert "`" not in all_sql
    assert "[t]" in all_sql or "[id]" in all_sql
