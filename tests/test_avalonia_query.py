"""Tests for cbdb_parity.avalonia_query — Python re-execution of
Avalonia query SQL against cbdb.sqlite.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cbdb_parity.avalonia_query import (
    EntryQueryRequest,
    _build_entry_query_sql,
    _csharp_params_to_sqlite,
    entry_query_field_names,
)

# ---------- _csharp_params_to_sqlite ----------

def test_csharp_param_rewrite_simple() -> None:
    src = "SELECT * FROM t WHERE id = $personKeyword AND year = $entryYear"
    out = _csharp_params_to_sqlite(src)
    assert ":personKeyword" in out
    assert ":entryYear" in out
    assert "$personKeyword" not in out


def test_csharp_param_rewrite_handles_numbered_params() -> None:
    src = "x IN ($dynastyId0, $dynastyId1, $dynastyId2)"
    out = _csharp_params_to_sqlite(src)
    assert ":dynastyId0" in out
    assert ":dynastyId2" in out
    assert "$" not in out


def test_csharp_param_rewrite_leaves_literal_dollars_alone() -> None:
    """A `$` not followed by an identifier (rare but possible in LIKE
    patterns or function names) must NOT be rewritten."""
    src = "SELECT '$5.00' AS price, $personKeyword AS k"
    out = _csharp_params_to_sqlite(src)
    # '$5.00' has $5 — that DOES start with [A-Z]... oh wait, $5 ->
    # $5 isn't [A-Za-z_] so the regex SHOULDN'T match it.
    assert "'$5.00'" in out
    assert ":personKeyword" in out


# ---------- _build_entry_query_sql ----------

_MINIMAL_TEMPLATE = """\
WITH matched_people AS (
    SELECT DISTINCT b.c_personid
    FROM BIOG_MAIN b
    WHERE ($useIndexYear = 0 OR b.c_index_year BETWEEN $indexYearFrom AND $indexYearTo)
{dynastyFilter}
)
SELECT ed.c_personid FROM ENTRY_DATA ed
JOIN matched_people mp ON mp.c_personid = ed.c_personid
WHERE 1 = 1
  AND ($useEntryYear = 0 OR ed.c_year BETWEEN $entryYearFrom AND $entryYearTo)
"""


def test_build_sql_no_dynamic_clauses() -> None:
    sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(limit=100),
    )
    assert "{dynastyFilter}" not in sql
    # No dynamic entry/place/dynasty IN clauses got appended.
    assert "c_entry_code IN" not in sql
    assert "c_entry_addr_id IN" not in sql
    assert "c_dy IN" not in sql
    assert "LIMIT :limit" in sql
    assert params["limit"] == 100
    assert params["useIndexYear"] == 0


def test_build_sql_with_entry_codes() -> None:
    sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(entry_codes=("197", "198", "200")),
    )
    assert "c_entry_code IN (:entryCode0, :entryCode1, :entryCode2)" in sql
    assert params["entryCode0"] == "197"
    assert params["entryCode2"] == "200"


def test_build_sql_with_dynasty_filter() -> None:
    sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(dynasty_ids=(15, 17)),
    )
    assert "b.c_dy IN (:dynastyId0, :dynastyId1)" in sql
    assert "{dynastyFilter}" not in sql
    assert params["dynastyId0"] == 15
    assert params["dynastyId1"] == 17


def test_build_sql_with_subordinate_units() -> None:
    sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(place_ids=(100, 200), include_subordinate_units=True),
    )
    assert "ZZZ_BELONGS_TO" in sql
    assert "EXISTS (SELECT 1" in sql
    assert ":placeId0" in sql
    assert params["placeId0"] == 100


def test_build_sql_without_subordinate_units() -> None:
    sql, _params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(place_ids=(100, 200), include_subordinate_units=False),
    )
    assert "ZZZ_BELONGS_TO" not in sql
    assert "ed.c_entry_addr_id IN (:placeId0, :placeId1)" in sql


def test_build_sql_year_swap_handled() -> None:
    """If from > to, the C# code clamps via Math.Min/Max so callers can't
    pass inverted ranges; Python mirror does the same."""
    _sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(use_index_year_range=True, index_year_from=1500, index_year_to=1200),
    )
    assert params["indexYearFrom"] == 1200
    assert params["indexYearTo"] == 1500


def test_build_sql_keyword_strips_double_quotes() -> None:
    """Reproduces the C# behaviour: `request.PersonKeyword.Trim().Replace("\\"", "")`
    + `%...%` wrapping."""
    _sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(person_keyword='  Wang "Bo"  '),
    )
    assert params["personKeyword"] == "%Wang Bo%"


def test_build_sql_keyword_blank_is_null() -> None:
    _sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(person_keyword=""),
    )
    assert params["personKeyword"] is None


def test_build_sql_limit_clamped() -> None:
    """C# uses Math.Clamp(limit, 1, 100000) (bumped from 10000)."""
    _sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(limit=999999),
    )
    assert params["limit"] == 100000
    _sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(limit=0),
    )
    assert params["limit"] == 1


# ---------- field-name accessor ----------

def test_field_names_count_matches_csharp_record() -> None:
    """EntryQueryRecord in `cbdb-desktop-app/Cbdb.App.Core/EntryQueryRecord.cs`
    has 36 positional fields; the Python column list must match in width."""
    assert len(entry_query_field_names()) == 36


def test_field_names_first_and_last() -> None:
    fields = entry_query_field_names()
    assert fields[0] == "person_id"
    # The C# record ends with PostingNotes (the 35th field).
    assert fields[-1] == "posting_notes"


# ---------- end-to-end with a fake sqlite ----------

def _make_minimal_db(path: Path) -> None:
    """A tiny database with just enough tables for the test template
    to run without errors."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE BIOG_MAIN (c_personid INTEGER, c_index_year INTEGER, c_dy INTEGER);
        CREATE TABLE ENTRY_DATA (c_personid INTEGER, c_year INTEGER);
        INSERT INTO BIOG_MAIN VALUES (1, 1500, 15), (2, 1600, 17), (3, 1700, 19);
        INSERT INTO ENTRY_DATA VALUES (1, 1500), (2, 1600), (3, 1700);
    """)
    conn.commit()
    conn.close()


def test_e2e_with_minimal_db(tmp_path: Path) -> None:
    """Smoke that the build_sql + sqlite3.execute path is wired up.
    Uses a template WITHOUT the trailing entry_label ORDER BY (which
    the real query relies on as a SELECT alias) — proves the build path
    produces valid SQLite syntax + binds params correctly."""
    db = tmp_path / "tiny.sqlite"
    _make_minimal_db(db)

    # Use a template that already supplies its own ORDER BY/LIMIT,
    # so the auto-appended trailer can be tested separately.
    # Run the inner WITH ... SELECT directly to confirm parameter binding.
    sql, params = _build_entry_query_sql(
        _csharp_params_to_sqlite(_MINIMAL_TEMPLATE),
        EntryQueryRequest(limit=10),
    )
    # The appended ORDER BY references entry_label, which the test DB
    # doesn't define — strip the trailing clause to test ONLY param
    # binding + the join.
    sql_stripped = sql.split("ORDER BY entry_label")[0] + " LIMIT :limit;"
    conn = sqlite3.connect(db)
    rows = conn.execute(sql_stripped, params).fetchall()
    conn.close()
    # The minimal SELECT only projects c_personid; three rows in
    # ENTRY_DATA match three rows in matched_people via the join.
    assert len(rows) == 3
