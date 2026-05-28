"""Python re-execution of Avalonia SqlitePersonBrowserService.GetPostingsAsync
(Phase 4, Tier 2 per-person accessor #5).

GetPostingsAsync produces a NESTED structure in C# (`Posting → Office
→ Address`) via an in-memory accumulator. We diff the RAW SQL output
instead, because:
  1. the C# accumulator logic is deterministic and identical on both
     sides — replicating it adds no diff signal;
  2. raw-row diff catches any SQL-engine divergence, which is what
     the parity harness exists for.

50 columns + we keep raw IDs (`posting_id`, `office_id`, `addr_id`)
already exposed in the SELECT — no splicing needed. The diff key
`(posting_id, sequence, office_id, addr_id)` matches the SQL's
ORDER BY and is unique per row (NULL preserved as None).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none
from cbdb_parity.avalonia_query_sql import find_sql_block


_POSTING_RECORD_FIELDS: tuple[str, ...] = (
    "posting_id", "office_id", "sequence",
    "office_name_chn", "office_name",
    "appt_desc_chn", "appt_desc",
    "assume_office_desc_chn", "assume_office_desc",
    "category_desc_chn", "category_desc",
    "first_year",
    "fy_nianhao_chn", "fy_nianhao_pin",
    "fy_nh_year",
    "fy_range_chn", "fy_range",
    "fy_month", "fy_intercalary", "fy_day",
    "fy_ganzhi_chn", "fy_ganzhi_py",
    "last_year",
    "ly_nianhao_chn", "ly_nianhao_pin",
    "ly_nh_year",
    "ly_range_chn", "ly_range",
    "ly_month", "ly_intercalary", "ly_day",
    "ly_ganzhi_chn", "ly_ganzhi_py",
    "dynasty_chn", "dynasty",
    "source_title_chn", "source_title",
    "pages", "notes",
    "created_by", "created_date",
    "modified_by", "modified_date",
    "addr_id",
    "addr_name_chn", "addr_name",
    "addr_created_by", "addr_created_date",
    "addr_modified_by", "addr_modified_date",
)
_POSTING_ID_FIELDS: tuple[str, ...] = ()


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_postings_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "POSTED_TO_OFFICE_DATA")


def _row_to_dict(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "posting_id":             r[0],
        "office_id":              r[1],
        "sequence":               r[2],
        "office_name_chn":        r[3],
        "office_name":            r[4],
        "appt_desc_chn":          r[5],
        "appt_desc":              r[6],
        "assume_office_desc_chn": r[7],
        "assume_office_desc":     r[8],
        "category_desc_chn":      r[9],
        "category_desc":          r[10],
        "first_year":             r[11],
        "fy_nianhao_chn":         r[12],
        "fy_nianhao_pin":         r[13],
        "fy_nh_year":             r[14],
        "fy_range_chn":           r[15],
        "fy_range":               r[16],
        "fy_month":               r[17],
        "fy_intercalary":         _to_bool_or_none(r[18]),
        "fy_day":                 r[19],
        "fy_ganzhi_chn":          r[20],
        "fy_ganzhi_py":           r[21],
        "last_year":              r[22],
        "ly_nianhao_chn":         r[23],
        "ly_nianhao_pin":         r[24],
        "ly_nh_year":             r[25],
        "ly_range_chn":           r[26],
        "ly_range":               r[27],
        "ly_month":               r[28],
        "ly_intercalary":         _to_bool_or_none(r[29]),
        "ly_day":                 r[30],
        "ly_ganzhi_chn":          r[31],
        "ly_ganzhi_py":           r[32],
        "dynasty_chn":            r[33],
        "dynasty":                r[34],
        "source_title_chn":       r[35],
        "source_title":           r[36],
        "pages":                  r[37],
        "notes":                  r[38],
        "created_by":             r[39],
        "created_date":           r[40],
        "modified_by":            r[41],
        "modified_date":          r[42],
        "addr_id":                r[43],
        "addr_name_chn":          r[44],
        "addr_name":              r[45],
        "addr_created_by":        r[46],
        "addr_created_date":      r[47],
        "addr_modified_by":       r[48],
        "addr_modified_date":     r[49],
    }


def postings_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    sql = _csharp_params_to_sqlite(_load_get_postings_sql(cs_path))
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            rows.append(_row_to_dict(r))
    return rows


def postings_field_names() -> tuple[str, ...]:
    return _POSTING_RECORD_FIELDS


def postings_id_field_names() -> tuple[str, ...]:
    return _POSTING_ID_FIELDS


__all__ = [
    "_row_to_dict",
    "postings_field_names",
    "postings_id_field_names",
    "postings_query",
]
