"""Row-count parity check between cbdb_data.mdb and cbdb.sqlite.

Pre-flight diagnostic for Phase 3 (the differential query harness). If
both databases came from the same Datadump (Phase 1.4 orchestrator
guarantees this), every common table should have identical row counts;
any mismatch is a sign that one of the two build pipelines dropped rows.

Per WORK_PLAN §1's strict-pipeline rule, the mdb side this check joins
against MUST be the Phase 1.3b-generated `cbdb_data.mdb` built from the
SAME Datadump archive that produced `cbdb.sqlite`. Pre-existing mdb
files on the user's machine are NOT acceptable inputs — they would
inject data-version drift into the comparison. While Phase 1.3b is
still deferred, only `count_sqlite_tables` is callable in practice;
`count_mdb_tables` and `compare_row_counts` remain exposed for Phase 3
once 1.3b lands.

Table-name matching is case-sensitive on purpose: case-divergence
between mdb and sqlite (e.g. mdb's `CopyTablesDefault` vs sqlite's
`COPYMISSINGTABLES`) is a real finding that Phase 3's query harness
needs to know about, surfaced here as paired `sqlite_only` /
`mdb_only` entries rather than silently coerced into a match.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# pyodbc is Windows-only and the harness only runs on Windows, but
# importing it at module scope would break cross-platform tooling
# (linters, type checkers, the schema-loader tests). Import lazily
# inside `count_mdb_tables` so the rest of this module is portable.


@dataclass(frozen=True, slots=True)
class TableCount:
    name: str
    rows: int


@dataclass(slots=True)
class ParityReport:
    """Side-by-side row-count diff for the same set of CBDB tables."""

    sqlite_only: list[str] = field(default_factory=list)
    mdb_only: list[str] = field(default_factory=list)
    matching: list[tuple[str, int]] = field(default_factory=list)
    mismatched: list[tuple[str, int, int]] = field(default_factory=list)
    # (table, sqlite_count, mdb_count) — sqlite_count first to match the
    # left-side-is-Avalonia convention used elsewhere in the harness.

    @property
    def has_mismatch(self) -> bool:
        return bool(self.mismatched or self.sqlite_only or self.mdb_only)


def count_sqlite_tables(sqlite_path: Path) -> list[TableCount]:
    """Return alphabetised row counts for every user table in `sqlite_path`.

    Tables prefixed `sqlite_` are SQLite internals and excluded.
    """
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"sqlite file not found: {sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    try:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        counts: list[TableCount] = []
        for n in names:
            # Identifiers in CBDB are alphanumeric + underscore; safe to
            # interpolate after the sqlite_master whitelist.
            rows = conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
            counts.append(TableCount(name=n, rows=int(rows)))
        return counts
    finally:
        conn.close()


def count_mdb_tables(mdb_path: Path) -> list[TableCount]:
    """Return alphabetised row counts for every user table in `mdb_path`.

    Imports `pyodbc` lazily so module-level import works on non-Windows.
    Skips Access-internal `MSys*` tables.
    """
    if not mdb_path.is_file():
        raise FileNotFoundError(f"mdb file not found: {mdb_path}")
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError(
            "pyodbc not installed — install the [access] extra: "
            "pip install -e .[access]"
        ) from exc

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    conn = pyodbc.connect(conn_str)
    try:
        cursor = conn.cursor()
        # ODBC catalog: tables() yields (catalog, schema, name, type, ...).
        # We want type == 'TABLE' (Access also reports 'SYSTEM TABLE' and
        # 'VIEW' which we exclude).
        names = sorted(
            row.table_name
            for row in cursor.tables(tableType="TABLE")
            if not row.table_name.upper().startswith("MSYS")
        )
        counts: list[TableCount] = []
        for n in names:
            cursor.execute(f'SELECT COUNT(*) FROM [{n}]')
            counts.append(TableCount(name=n, rows=int(cursor.fetchone()[0])))
        return counts
    finally:
        conn.close()


def compare_row_counts(
    sqlite_counts: list[TableCount],
    mdb_counts: list[TableCount],
) -> ParityReport:
    """Diff two equal-shape table-count lists into a ParityReport.

    Both inputs may come in any order; this function does its own keying.
    """
    sqlite_by_name = {t.name: t.rows for t in sqlite_counts}
    mdb_by_name = {t.name: t.rows for t in mdb_counts}

    report = ParityReport()
    only_in_sqlite = set(sqlite_by_name) - set(mdb_by_name)
    only_in_mdb = set(mdb_by_name) - set(sqlite_by_name)
    common = set(sqlite_by_name) & set(mdb_by_name)

    report.sqlite_only = sorted(only_in_sqlite)
    report.mdb_only = sorted(only_in_mdb)
    for name in sorted(common):
        s = sqlite_by_name[name]
        m = mdb_by_name[name]
        if s == m:
            report.matching.append((name, s))
        else:
            report.mismatched.append((name, s, m))
    return report
