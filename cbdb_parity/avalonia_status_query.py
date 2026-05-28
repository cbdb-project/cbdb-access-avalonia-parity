"""Python re-execution of Avalonia SqliteStatusQueryService.QueryAsync
(Phase 3e). Mirrors the entry / office Phase 3c-3d pattern: load the
raw SQL from `$AVALONIA_REPO/Cbdb.App.Data/SqliteStatusQueryService.cs`,
substitute the C# template slots in Python, execute against
cbdb.sqlite, return row dicts shaped like `Cbdb.App.Core.StatusQueryRecord`.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_query_sql import find_sql_block


@dataclass(frozen=True, slots=True)
class StatusQueryRequest:
    """Mirror of `Cbdb.App.Core.StatusQueryRequest`. Positional field
    order matches the C# record so positional construction binds the
    correct values."""

    person_keyword: str | None = None
    status_codes: Sequence[str] = ()
    place_ids: Sequence[int] = ()
    include_subordinate_units: bool = False
    use_index_year_range: bool = False
    index_year_from: int = 0
    index_year_to: int = 0
    dynasty_ids: Sequence[int] = ()
    limit: int = 5000


# Snake-case mirror of `Cbdb.App.Core.StatusQueryRecord` positional
# property order. The C# reader's column indices match SELECT order
# (no swap like the office query has), so SELECT-order zip-mapping is
# semantically correct here.
_STATUS_RECORD_FIELDS: tuple[str, ...] = (
    "person_id",                # 0
    "name_chn",                 # 1
    "name",                     # 2
    "index_year",               # 3
    "index_year_type",          # 4
    "sex",                      # 5
    "dynasty",                  # 6
    "index_address_id",         # 7
    "index_address",            # 8
    "index_address_type",       # 9
    "x_coord",                  # 10
    "y_coord",                  # 11
    "sequence",                 # 12
    "status",                   # 13
    "status_code",              # 14  CAST(... AS TEXT)
    "first_year",               # 15
    "first_nianhao_code",       # 16
    "first_nianhao",            # 17
    "first_nianhao_pinyin",     # 18
    "first_nianhao_year",       # 19
    "first_range_code",         # 20
    "first_range_desc",         # 21
    "first_range",              # 22
    "last_year",                # 23
    "last_nianhao_code",        # 24
    "last_nianhao",             # 25
    "last_nianhao_pinyin",      # 26
    "last_nianhao_year",        # 27
    "last_range_code",          # 28
    "last_range_desc",          # 29
    "last_range",               # 30
    "supplement",               # 31
    "source_id",                # 32
    "source",                   # 33
    "pages",                    # 34
    "notes",                    # 35
)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_query_async_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "FROM STATUS_DATA sd")


def _build_status_query_sql(
    template: str,
    request: StatusQueryRequest,
) -> tuple[str, dict[str, Any]]:
    """Apply the dynamic concatenation the C# code does at runtime,
    mirroring SqliteStatusQueryService.QueryAsync lines 182-307.
    """
    if request.dynasty_ids:
        dynasty_in = ", ".join(f":dynastyId{i}" for i in range(len(request.dynasty_ids)))
        dynasty_filter = f"\n       AND b.c_dy IN ({dynasty_in})"
    else:
        dynasty_filter = ""

    sql = template.replace("{dynastyFilter}", dynasty_filter)

    if request.status_codes:
        codes_in = ", ".join(f":statusCode{i}" for i in range(len(request.status_codes)))
        sql += f"\n  AND sd.c_status_code IN ({codes_in})"
    if request.place_ids:
        place_in = ", ".join(f":placeId{i}" for i in range(len(request.place_ids)))
        if request.include_subordinate_units:
            sql += (
                f"\n  AND (b.c_index_addr_id IN ({place_in}) "
                f"OR EXISTS (SELECT 1 FROM ZZZ_BELONGS_TO bt "
                f"WHERE bt.c_addr_id = b.c_index_addr_id "
                f"AND bt.c_belongs_to IN ({place_in})))"
            )
        else:
            sql += f"\n  AND b.c_index_addr_id IN ({place_in})"

    sql += "\n\nORDER BY status_label, b.c_personid, sd.c_sequence\nLIMIT :limit;"
    sql = _csharp_params_to_sqlite(sql)

    params: dict[str, Any] = {
        "personKeyword": (
            None if not request.person_keyword or not request.person_keyword.strip()
            else f"%{request.person_keyword.strip().replace(chr(34), '')}%"
        ),
        "useIndexYear": 1 if request.use_index_year_range else 0,
        "indexYearFrom": min(request.index_year_from, request.index_year_to),
        "indexYearTo": max(request.index_year_from, request.index_year_to),
        "limit": max(1, min(request.limit, 100000)),
    }
    for i, c in enumerate(request.status_codes):
        params[f"statusCode{i}"] = c
    for i, p in enumerate(request.place_ids):
        params[f"placeId{i}"] = p
    for i, d in enumerate(request.dynasty_ids):
        params[f"dynastyId{i}"] = d
    return sql, params


def status_query(
    sqlite_path: Path,
    request: StatusQueryRequest,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    """Execute the Avalonia status query against `sqlite_path`."""
    # Picker-contract short-circuit (mirrors the upstream C# guard at
    # SqliteStatusQueryService.QueryAsync): empty status_codes ⇒ no
    # rows. Without this, the downstream SQL drops the IN-filter and
    # runs unfiltered.
    if not request.status_codes:
        return []
    cs_path = avalonia_data_dir / "SqliteStatusQueryService.cs"
    template = _load_query_async_sql(cs_path)
    sql, params = _build_status_query_sql(template, request)

    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, params)
        for row in cursor.fetchall():
            assert len(row) == len(_STATUS_RECORD_FIELDS), (
                f"row width {len(row)} != expected {len(_STATUS_RECORD_FIELDS)}"
            )
            record = dict(zip(_STATUS_RECORD_FIELDS, row, strict=True))
            # Mirror the C# reader's per-column normalisation. The
            # Avalonia SELECT writes `sd.c_sequence` raw (no SQL-level
            # COALESCE like the office query has), but the C# reader at
            # SqliteStatusQueryService.cs:324 applies a NULL-to-0
            # fallback via `reader.IsDBNull(12) ? 0 : reader.GetInt32(12)`.
            # `sequence` is also part of the diff key in the Phase 3e
            # smoke test, so forwarding raw None would produce false
            # only-in-X mismatches for STATUS_DATA rows whose
            # c_sequence is NULL.
            if record.get("sequence") is None:
                record["sequence"] = 0
            rows.append(record)
    return rows


def status_query_field_names() -> tuple[str, ...]:
    return _STATUS_RECORD_FIELDS


__all__ = [
    "StatusQueryRequest",
    "status_query",
    "status_query_field_names",
]
