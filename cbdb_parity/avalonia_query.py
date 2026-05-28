"""Python re-execution of Avalonia query SQL against cbdb.sqlite.

Phase 3a — runs the exact SQL templates extracted from
`cbdb-desktop-app/Cbdb.App.Data/Sqlite*QueryService.cs` via Python's
`sqlite3`, returning rows shaped like the C# query-record dataclasses.

Why this works: each `Sqlite*QueryService.cs` builds its query as a C#
raw-string SQL template with `$parameter` placeholders, sends the
template to SQLite via Microsoft.Data.Sqlite, and converts rows
positionally into a `Cbdb.App.Core.*QueryRecord`. Microsoft.Data.Sqlite
and Python's `sqlite3` both wrap the same SQLite engine, so running
the same SQL with the same parameter values produces bit-identical
result rows.

The .NET layer also has post-processing (e.g.
`SqliteEntryQueryService.QueryAsync` groups `EntryQueryRecord`s into
`EntryQueryPerson`s in LINQ before returning). Phase 3 compares at the
RECORD level — that's what Access Form_LookAt* shows the user.
Phase 4 can layer person-level grouping if needed.

Parameter syntax: C# uses `$name`, Python sqlite3 uses `:name`. The
helper functions in this module rewrite the templates as they load.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_query_sql import extract_sql_blocks


@dataclass(frozen=True, slots=True)
class EntryQueryRequest:
    """Mirror of `Cbdb.App.Core.EntryQueryRequest` (the C# record)."""

    person_keyword: str | None = None
    entry_codes: Sequence[str] = ()
    place_ids: Sequence[int] = ()
    include_subordinate_units: bool = False
    use_index_year_range: bool = False
    index_year_from: int = 0
    index_year_to: int = 0
    use_entry_year_range: bool = False
    entry_year_from: int = 0
    entry_year_to: int = 0
    dynasty_ids: Sequence[int] = ()
    limit: int = 5000


# The 35 columns (in order) that `SqliteEntryQueryService.QueryAsync`
# SELECTs. Matches `Cbdb.App.Core.EntryQueryRecord` exactly.
_ENTRY_RECORD_FIELDS: tuple[str, ...] = (
    "person_id", "name_chn", "name", "index_year", "index_year_type",
    "sex", "dynasty", "index_address_id", "index_address", "index_address_type",
    "sequence", "entry_code", "entry_method", "entry_year",
    "nianhao", "nianhao_year", "range", "exam_rank", "age",
    "kinship", "kin_person", "association", "associate_person", "institution",
    "exam_field", "entry_address_id", "entry_address", "entry_x_coord", "entry_y_coord",
    "entry_xy_count", "parental_status", "attempt_count",
    "source", "pages", "notes", "posting_notes",
)


def _csharp_params_to_sqlite(sql: str) -> str:
    """Rewrite `$name` placeholders to `:name` for Python sqlite3."""
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_main_entry_query_sql(cs_path: Path) -> str:
    """Pick the SqliteEntryQueryService.cs block that contains the main
    QueryAsync SQL (joins ENTRY_DATA + BIOG_MAIN) and rewrite params."""
    blocks = extract_sql_blocks(cs_path)
    for b in blocks:
        if "FROM ENTRY_DATA" in b and "JOIN BIOG_MAIN" in b and "$personKeyword" in b:
            return _csharp_params_to_sqlite(b)
    raise LookupError(
        f"{cs_path}: no SQL block contains the main entry-query shape "
        f"(FROM ENTRY_DATA + JOIN BIOG_MAIN + $personKeyword)"
    )


def _build_entry_query_sql(
    template: str,
    request: EntryQueryRequest,
) -> tuple[str, dict[str, Any]]:
    """Apply the C# code's dynamic SQL concatenation in Python.

    Source-of-truth: `SqliteEntryQueryService.QueryAsync` lines ~178-329
    in `cbdb-desktop-app`. The dynamic bits are:
      - `dynastyFilter` injected into both BIOG_MAIN WHEREs in the CTE
      - `entry_code IN (...)` added after the static template
      - `entry_addr_id IN (...)` or the EXISTS subordinate-units variant
      - trailing `ORDER BY ... LIMIT $limit;`
    """
    # 1. Dynasty filter — injected INTO the extracted template via the
    # token the C# code uses for substitution.
    if request.dynasty_ids:
        dynasty_in = ", ".join(
            f":dynastyId{i}" for i in range(len(request.dynasty_ids))
        )
        dynasty_filter = f"\n       AND b.c_dy IN ({dynasty_in})"
    else:
        dynasty_filter = ""
    sql = template.replace("{dynastyFilter}", dynasty_filter)

    # 2. entry_code IN (...) appended.
    if request.entry_codes:
        codes_in = ", ".join(f":entryCode{i}" for i in range(len(request.entry_codes)))
        sql += f"\n  AND ed.c_entry_code IN ({codes_in})"

    # 3. place_id IN (...) — plain or subordinate-units variant.
    if request.place_ids:
        place_in = ", ".join(f":placeId{i}" for i in range(len(request.place_ids)))
        if request.include_subordinate_units:
            sql += (
                f"\n  AND (ed.c_entry_addr_id IN ({place_in}) "
                f"OR EXISTS (SELECT 1 FROM ZZZ_BELONGS_TO bt "
                f"WHERE bt.c_addr_id = ed.c_entry_addr_id "
                f"AND bt.c_belongs_to IN ({place_in})))"
            )
        else:
            sql += f"\n  AND ed.c_entry_addr_id IN ({place_in})"

    # 4. trailing ORDER BY + LIMIT.
    # Faithful replay: keep Avalonia's exact ORDER BY. The Access bridge
    # in `access_query.entry_query_access` mirrors this ordering via a
    # post-fetch entry_label lookup so the LIMIT cutoffs align.
    sql += "\n\nORDER BY entry_label, ed.c_year, b.c_personid, ed.c_sequence\nLIMIT :limit;"

    # Bind values.
    params: dict[str, Any] = {
        "personKeyword": (
            None if not request.person_keyword or not request.person_keyword.strip()
            else f"%{request.person_keyword.strip().replace(chr(34), '')}%"
        ),
        "useIndexYear": 1 if request.use_index_year_range else 0,
        "indexYearFrom": min(request.index_year_from, request.index_year_to),
        "indexYearTo": max(request.index_year_from, request.index_year_to),
        "useEntryYear": 1 if request.use_entry_year_range else 0,
        "entryYearFrom": min(request.entry_year_from, request.entry_year_to),
        "entryYearTo": max(request.entry_year_from, request.entry_year_to),
        "limit": max(1, min(request.limit, 100000)),
    }
    for i, c in enumerate(request.entry_codes):
        params[f"entryCode{i}"] = c
    for i, p in enumerate(request.place_ids):
        params[f"placeId{i}"] = p
    for i, d in enumerate(request.dynasty_ids):
        params[f"dynastyId{i}"] = d

    return sql, params


def entry_query(
    sqlite_path: Path,
    request: EntryQueryRequest,
    *,
    avalonia_data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Execute the Avalonia entry query against `sqlite_path`.

    Returns a list of dicts keyed by `_ENTRY_RECORD_FIELDS`. Matches
    the row order produced by Avalonia's `EntryQueryResult.Records`.

    `avalonia_data_dir` defaults to `$AVALONIA_REPO/Cbdb.App.Data` per
    `.env`; callers pass an explicit path in tests or when scanning a
    pinned commit.
    """
    if avalonia_data_dir is None:
        raise ValueError(
            "avalonia_data_dir must be provided (resolve from cfg.avalonia_repo "
            "/ 'Cbdb.App.Data' at the call site)"
        )

    cs_path = avalonia_data_dir / "SqliteEntryQueryService.cs"
    template = _load_main_entry_query_sql(cs_path)
    sql, params = _build_entry_query_sql(template, request)

    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, params)
        for row in cursor.fetchall():
            assert len(row) == len(_ENTRY_RECORD_FIELDS), (
                f"row width {len(row)} != expected {len(_ENTRY_RECORD_FIELDS)}"
            )
            rows.append(dict(zip(_ENTRY_RECORD_FIELDS, row, strict=True)))
    return rows


def entry_query_field_names() -> tuple[str, ...]:
    """Public accessor for the canonical column order; used by Phase 3b's
    Access-side bridge to align column ordering."""
    return _ENTRY_RECORD_FIELDS


__all__ = [
    "EntryQueryRequest",
    "entry_query",
    "entry_query_field_names",
]
# Re-export Iterable for callers that want to import alongside.
_ = Iterable  # silence unused-import linter
