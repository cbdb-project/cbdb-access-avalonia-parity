"""Python re-execution of Avalonia SqliteOfficeQueryService.QueryAsync.

Phase 3d analogue of `cbdb_parity.avalonia_query` (entry). Loads the
raw SQL template from
`$AVALONIA_REPO/Cbdb.App.Data/SqliteOfficeQueryService.cs`, fills in
the C# `$\"\"\"...\"\"\"` substitution slots from a Python request, executes
the result against `cbdb.sqlite`, and returns row dicts shaped like
`Cbdb.App.Core.OfficeQueryRecord`.

Source-of-truth alignment notes:
  - The C# code embeds four template slots inside the QueryAsync (using
    raw string: `{dynastyFilter}` (used twice), `{personPlaceMatchExpr}`,
    `{officePlaceMatchExpr}`, `{placeWorkflowExpr}`. We rebuild those
    expressions in Python with the exact same shapes, so the SQL string
    we send to SQLite is byte-identical to what the C# code sends.
  - The 65-column SELECT list is mirrored in `_OFFICE_RECORD_FIELDS`.
    Field names use Python `snake_case` derived from the C# property
    names (PascalCase → snake_case). The diff layer keys by the
    snake_case names.
  - The C# `OfficeQueryRecord` constructor lists fields in a different
    visual order from the SELECT (SourceId etc appear before
    OfficePlaceCount in the constructor call, even though SQL column 57
    is place_count and 58 is c_source). Each `reader.GetXxx(N)` still
    pulls SQL column N, so there is no actual swap — both backends see
    the same value at the same column index. We zip-map SELECT order to
    our field names directly.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_query_sql import find_sql_block


@dataclass(frozen=True, slots=True)
class OfficeQueryRequest:
    """Mirror of `Cbdb.App.Core.OfficeQueryRequest` (the C# record)."""

    person_keyword: str | None = None
    office_codes: Sequence[int] = ()
    dynasty_ids: Sequence[int] = ()
    use_index_year_range: bool = False
    index_year_from: int = 0
    index_year_to: int = 0
    use_office_year_range: bool = False
    office_year_from: int = 0
    office_year_to: int = 0
    person_place_ids: Sequence[int] = ()
    office_place_ids: Sequence[int] = ()
    include_subordinate_person_units: bool = False
    include_subordinate_office_units: bool = False
    limit: int = 5000


# Mirrors the QueryAsync SELECT list (.cs:287-356). 65 columns total.
# Names match the C# `OfficeQueryRecord` properties (snake_case form)
# and the indices align with SQL SELECT order. The C# constructor's
# parameter listing on lines 468-534 visually orders SourceId / Source /
# Pages / Notes / *Match / PlaceWorkflow / OfficePlaceCount, but each
# `reader.GetXxx(N)` still reads SQL column N — there is no swap to
# replicate here.
_OFFICE_RECORD_FIELDS: tuple[str, ...] = (
    "person_id",                  # 0  pto.c_personid
    "name_chn",                   # 1
    "name",                       # 2
    "index_year",                 # 3
    "index_year_type",            # 4
    "sex_label",                  # 5
    "person_dynasty",             # 6
    "posting_dynasty",            # 7
    "index_addr_id",              # 8
    "index_address",              # 9
    "index_address_type",         # 10
    "posting_id",                 # 11
    "sequence",                   # 12
    "office_code",                # 13 — CAST(pto.c_office_id AS TEXT)
    "office_label",               # 14
    "appt_type_code",             # 15
    "appointment_type",           # 16
    "assume_office_code",         # 17
    "assume_office",              # 18
    "office_category_id",         # 19
    "category_label",             # 20
    "first_year",                 # 21
    "first_nianhao_code",         # 22
    "first_nianhao",              # 23
    "first_nianhao_pinyin",       # 24
    "first_nianhao_year",         # 25
    "first_range_code",           # 26
    "first_range_desc",           # 27
    "first_range",                # 28
    "first_month",                # 29
    "first_intercalary",          # 30
    "first_day",                  # 31
    "first_day_gz",               # 32
    "first_ganzhi",               # 33
    "first_ganzhi_pinyin",        # 34
    "last_year",                  # 35
    "last_nianhao_code",          # 36
    "last_nianhao",               # 37
    "last_nianhao_pinyin",        # 38
    "last_nianhao_year",          # 39
    "last_range_code",            # 40
    "last_range_desc",            # 41
    "last_range",                 # 42
    "last_month",                 # 43
    "last_intercalary",           # 44
    "last_day",                   # 45
    "last_day_gz",                # 46
    "last_ganzhi",                # 47
    "last_ganzhi_pinyin",         # 48
    "inst_code",                  # 49
    "inst_name_code",             # 50
    "institution_label",          # 51
    "office_addr_id",             # 52
    "office_address",             # 53
    "office_x_coord",             # 54
    "office_y_coord",             # 55
    "office_xy_count",            # 56
    "office_place_count",         # 57  posting_place_count.place_count
    "source_id",                  # 58  pto.c_source
    "source_label",               # 59
    "pages",                      # 60
    "notes",                      # 61
    "person_place_match",         # 62
    "office_place_match",         # 63
    "place_workflow",             # 64
)


def _csharp_params_to_sqlite(sql: str) -> str:
    """Rewrite `$name` C# placeholders to `:name` for Python sqlite3."""
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_query_async_sql(cs_path: Path) -> str:
    """Pick the `SqliteOfficeQueryService.QueryAsync` SQL block.

    The service file has four raw-string blocks: picker SELECT
    (OFFICE_CODES), office-type-tree SELECT, office-code-type-rel
    SELECT, and the main QueryAsync. The QueryAsync block is the only
    one that joins `POSTED_TO_OFFICE_DATA pto`.
    """
    return find_sql_block(cs_path, "FROM POSTED_TO_OFFICE_DATA pto")


def _person_place_match_expr(personPlaceExactExpr: str, personPlaceSubordinateExpr: str) -> str:
    """Re-creates the `personPlaceMatchExpr` C# branch verbatim."""
    return f"""
CASE
    WHEN {personPlaceExactExpr} THEN 'Exact'
    WHEN {personPlaceSubordinateExpr} THEN 'Subordinate'
    ELSE 'No match'
END
"""


def _office_place_match_expr_unfiltered() -> str:
    """`officePlaceMatchExpr` C# branch when no office_place_ids."""
    return """
CASE
    WHEN pta.c_addr_id IS NULL THEN 'No office place'
    ELSE 'Unfiltered'
END
"""


def _office_place_match_expr_filtered(officePlaceExactExpr: str, officePlaceSubordinateExpr: str) -> str:
    return f"""
CASE
    WHEN {officePlaceExactExpr} THEN 'Exact'
    WHEN {officePlaceSubordinateExpr} THEN 'Subordinate'
    WHEN pta.c_addr_id IS NULL THEN 'No office place'
    ELSE 'No match'
END
"""


def _build_place_workflow_expr(
    has_person_place_filter: bool,
    has_office_place_filter: bool,
    person_place_match_expr: str,
    office_place_match_expr: str,
) -> str:
    """Direct port of `BuildPlaceWorkflowExpression` (.cs:607-626)."""
    if has_person_place_filter and has_office_place_filter:
        return f"({person_place_match_expr} || ' person / ' || {office_place_match_expr} || ' office')"
    if has_person_place_filter:
        return f"({person_place_match_expr} || ' person place')"
    if has_office_place_filter:
        return f"({office_place_match_expr} || ' office place')"
    return "'Unfiltered'"


def _build_office_query_sql(
    template: str,
    request: OfficeQueryRequest,
) -> tuple[str, dict[str, Any]]:
    """Apply the C# code's dynamic SQL concatenation in Python.

    Mirrors `SqliteOfficeQueryService.QueryAsync` lines ~211-450.
    """
    # 1. Place-id IN lists + the four "match" expressions.
    person_place_param_list = ", ".join(
        f":personPlaceId{i}" for i in range(len(request.person_place_ids))
    )
    office_place_param_list = ", ".join(
        f":officePlaceId{i}" for i in range(len(request.office_place_ids))
    )

    personPlaceExactExpr = (
        f"b.c_index_addr_id IN ({person_place_param_list})"
        if request.person_place_ids
        else "0"
    )
    personPlaceSubordinateExpr = (
        f"EXISTS (SELECT 1 FROM ZZZ_BELONGS_TO bt WHERE bt.c_addr_id = b.c_index_addr_id AND bt.c_belongs_to IN ({person_place_param_list}))"
        if request.person_place_ids
        else "0"
    )
    officePlaceExactExpr = (
        f"pta.c_addr_id IN ({office_place_param_list})"
        if request.office_place_ids
        else "0"
    )
    officePlaceSubordinateExpr = (
        f"EXISTS (SELECT 1 FROM ZZZ_BELONGS_TO bt WHERE bt.c_addr_id = pta.c_addr_id AND bt.c_belongs_to IN ({office_place_param_list}))"
        if request.office_place_ids
        else "0"
    )

    person_place_match_expr = (
        "'Unfiltered'"
        if not request.person_place_ids
        else _person_place_match_expr(personPlaceExactExpr, personPlaceSubordinateExpr)
    )
    office_place_match_expr = (
        _office_place_match_expr_unfiltered()
        if not request.office_place_ids
        else _office_place_match_expr_filtered(officePlaceExactExpr, officePlaceSubordinateExpr)
    )
    place_workflow_expr = _build_place_workflow_expr(
        has_person_place_filter=bool(request.person_place_ids),
        has_office_place_filter=bool(request.office_place_ids),
        person_place_match_expr=person_place_match_expr,
        office_place_match_expr=office_place_match_expr,
    )

    # 2. Dynasty filter (injected at two sites in the matched_people CTE).
    if request.dynasty_ids:
        dynasty_in = ", ".join(f":dynastyId{i}" for i in range(len(request.dynasty_ids)))
        dynasty_filter = f"\n       AND b.c_dy IN ({dynasty_in})"
    else:
        dynasty_filter = ""

    # 3. Substitute the four template slots into the extracted SQL body.
    sql = (
        template
        .replace("{dynastyFilter}", dynasty_filter)
        .replace("{personPlaceMatchExpr}", person_place_match_expr)
        .replace("{officePlaceMatchExpr}", office_place_match_expr)
        .replace("{placeWorkflowExpr}", place_workflow_expr)
    )

    # 4. Append office_code / place IN clauses (lines .cs:413-443).
    if request.office_codes:
        codes_in = ", ".join(f":officeCode{i}" for i in range(len(request.office_codes)))
        sql += f"\n  AND pto.c_office_id IN ({codes_in})"
    if request.person_place_ids:
        if request.include_subordinate_person_units:
            sql += f"\n  AND ({personPlaceExactExpr} OR {personPlaceSubordinateExpr})"
        else:
            sql += f"\n  AND {personPlaceExactExpr}"
    if request.office_place_ids:
        if request.include_subordinate_office_units:
            sql += f"\n  AND ({officePlaceExactExpr} OR {officePlaceSubordinateExpr})"
        else:
            sql += f"\n  AND {officePlaceExactExpr}"

    # 5. ORDER BY + LIMIT — verbatim from .cs:445-449.
    sql += (
        "\n\nORDER BY office_label, pto.c_firstyear, b.c_personid, "
        "pto.c_posting_id, pto.c_sequence, pta.c_addr_id\n"
        "LIMIT :limit;"
    )

    sql = _csharp_params_to_sqlite(sql)

    # 6. Bind values.
    params: dict[str, Any] = {
        "personKeyword": (
            None if not request.person_keyword or not request.person_keyword.strip()
            else f"%{request.person_keyword.strip().replace(chr(34), '')}%"
        ),
        "useIndexYear": 1 if request.use_index_year_range else 0,
        "indexYearFrom": min(request.index_year_from, request.index_year_to),
        "indexYearTo": max(request.index_year_from, request.index_year_to),
        "useOfficeYear": 1 if request.use_office_year_range else 0,
        # C# uses DBNull when the office-year range is disabled. SQLite's
        # Python binding accepts None for NULL, and the SQL guard
        # `$useOfficeYear = 0` short-circuits the comparison anyway.
        "officeYearFrom": (
            min(request.office_year_from, request.office_year_to)
            if request.use_office_year_range else None
        ),
        "officeYearTo": (
            max(request.office_year_from, request.office_year_to)
            if request.use_office_year_range else None
        ),
        "limit": max(1, min(request.limit, 10000)),
    }
    for i, c in enumerate(request.office_codes):
        params[f"officeCode{i}"] = c
    for i, p in enumerate(request.person_place_ids):
        params[f"personPlaceId{i}"] = p
    for i, p in enumerate(request.office_place_ids):
        params[f"officePlaceId{i}"] = p
    for i, d in enumerate(request.dynasty_ids):
        params[f"dynastyId{i}"] = d

    return sql, params


def office_query(
    sqlite_path: Path,
    request: OfficeQueryRequest,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    """Execute the Avalonia office query against `sqlite_path`.

    Returns rows shaped like `OfficeQueryRecord` (dicts keyed by
    `_OFFICE_RECORD_FIELDS`). The row order matches
    `OfficeQueryResult.Records` because we issue the same ORDER BY.
    """
    cs_path = avalonia_data_dir / "SqliteOfficeQueryService.cs"
    template = _load_query_async_sql(cs_path)
    sql, params = _build_office_query_sql(template, request)

    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, params)
        for row in cursor.fetchall():
            assert len(row) == len(_OFFICE_RECORD_FIELDS), (
                f"row width {len(row)} != expected {len(_OFFICE_RECORD_FIELDS)}"
            )
            rows.append(dict(zip(_OFFICE_RECORD_FIELDS, row, strict=True)))
    return rows


def office_query_field_names() -> tuple[str, ...]:
    """Public accessor for the canonical column order."""
    return _OFFICE_RECORD_FIELDS


__all__ = [
    "OfficeQueryRequest",
    "office_query",
    "office_query_field_names",
]
_ = Iterable  # keep collections.abc.Iterable import live for downstream uses
_ = field  # keep dataclasses.field import live (used by subclasses)
