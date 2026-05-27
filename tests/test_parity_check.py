"""Tests for cbdb_parity.parity_check — row-count parity between mdb/sqlite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cbdb_parity.parity_check import (
    ParityReport,
    TableCount,
    compare_row_counts,
    count_sqlite_tables,
)

# ---------- sqlite introspection ----------

def _seed_sqlite(path: Path, tables: dict[str, int]) -> None:
    conn = sqlite3.connect(path)
    try:
        for name, n_rows in tables.items():
            conn.execute(f'CREATE TABLE "{name}" (x INTEGER)')
            conn.executemany(f'INSERT INTO "{name}" VALUES (?)', [(i,) for i in range(n_rows)])
        conn.commit()
    finally:
        conn.close()


def test_count_sqlite_tables_empty_db(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    sqlite3.connect(db).close()
    counts = count_sqlite_tables(db)
    assert counts == []


def test_count_sqlite_tables_basic(tmp_path: Path) -> None:
    db = tmp_path / "x.sqlite"
    _seed_sqlite(db, {"A": 5, "B": 0, "C": 12345})
    counts = count_sqlite_tables(db)
    assert counts == [
        TableCount("A", 5),
        TableCount("B", 0),
        TableCount("C", 12345),
    ]


def test_count_sqlite_tables_skips_sqlite_internal(tmp_path: Path) -> None:
    """An AUTOINCREMENT PK causes SQLite to maintain its own
    `sqlite_sequence` housekeeping table; the user-table filter must hide
    it from the count list."""
    db = tmp_path / "x.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE BIOG_MAIN (id INTEGER PRIMARY KEY AUTOINCREMENT, x TEXT)")
        conn.execute("INSERT INTO BIOG_MAIN(x) VALUES ('a'), ('b')")
        conn.commit()
    finally:
        conn.close()

    counts = count_sqlite_tables(db)
    # sqlite_sequence exists in sqlite_master but must be filtered out.
    assert [t.name for t in counts] == ["BIOG_MAIN"]
    assert counts[0].rows == 2


def test_count_sqlite_tables_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"sqlite file not found"):
        count_sqlite_tables(tmp_path / "nope.sqlite")


# ---------- compare_row_counts ----------

def test_compare_row_counts_all_matching() -> None:
    s = [TableCount("A", 10), TableCount("B", 20)]
    m = [TableCount("A", 10), TableCount("B", 20)]
    rep = compare_row_counts(s, m)
    assert not rep.has_mismatch
    assert rep.matching == [("A", 10), ("B", 20)]
    assert rep.mismatched == []
    assert rep.sqlite_only == []
    assert rep.mdb_only == []


def test_compare_row_counts_mismatched_rows() -> None:
    s = [TableCount("A", 10), TableCount("B", 50)]
    m = [TableCount("A", 10), TableCount("B", 49)]
    rep = compare_row_counts(s, m)
    assert rep.has_mismatch
    assert rep.matching == [("A", 10)]
    assert rep.mismatched == [("B", 50, 49)]


def test_compare_row_counts_table_only_in_sqlite() -> None:
    s = [TableCount("A", 1), TableCount("EXTRA", 99)]
    m = [TableCount("A", 1)]
    rep = compare_row_counts(s, m)
    assert rep.has_mismatch
    assert rep.sqlite_only == ["EXTRA"]
    assert rep.mdb_only == []
    assert rep.matching == [("A", 1)]


def test_compare_row_counts_table_only_in_mdb() -> None:
    s = [TableCount("A", 1)]
    m = [TableCount("A", 1), TableCount("EXTRA", 99)]
    rep = compare_row_counts(s, m)
    assert rep.has_mismatch
    assert rep.mdb_only == ["EXTRA"]
    assert rep.sqlite_only == []


def test_compare_row_counts_input_order_does_not_matter() -> None:
    s = [TableCount("B", 2), TableCount("A", 1)]
    m = [TableCount("A", 1), TableCount("B", 2)]
    rep = compare_row_counts(s, m)
    assert not rep.has_mismatch
    assert rep.matching == [("A", 1), ("B", 2)]  # output is alphabetised


def test_compare_row_counts_case_sensitive() -> None:
    """Case-divergent table names are NOT coerced into a match. This is
    the contract the real-world smoke proved valuable: mdb-side
    `CopyTablesDefault` vs sqlite-side `COPYMISSINGTABLES` is a real
    finding that Phase 3's harness needs to handle, not paper over.
    """
    s = [TableCount("A", 5), TableCount("Mixed", 1)]
    m = [TableCount("a", 5), TableCount("mixed", 1)]
    rep = compare_row_counts(s, m)
    assert rep.has_mismatch
    assert rep.sqlite_only == ["A", "Mixed"]
    assert rep.mdb_only == ["a", "mixed"]
    assert rep.matching == []


def test_compare_row_counts_mixed_report() -> None:
    """All four buckets populated at once — mirrors the shape of the
    actual `cbdb_data_20260430` vs `cbdb.sqlite (20260527)` comparison."""
    s = [TableCount("MATCH", 10), TableCount("DRIFT", 100), TableCount("ONLY_SQLITE", 1)]
    m = [TableCount("MATCH", 10), TableCount("DRIFT", 99),  TableCount("ONLY_MDB", 1)]
    rep = compare_row_counts(s, m)
    assert rep.matching == [("MATCH", 10)]
    assert rep.mismatched == [("DRIFT", 100, 99)]
    assert rep.sqlite_only == ["ONLY_SQLITE"]
    assert rep.mdb_only == ["ONLY_MDB"]
    assert rep.has_mismatch


def test_parity_report_has_mismatch_property() -> None:
    rep = ParityReport()
    assert not rep.has_mismatch
    rep.matching.append(("A", 1))
    assert not rep.has_mismatch
    rep.mismatched.append(("B", 2, 3))
    assert rep.has_mismatch
