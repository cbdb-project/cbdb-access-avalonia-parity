"""Python re-execution of Avalonia SqlitePersonBrowserService.GetStatusesAsync
(Phase 4, Tier 2 per-person accessor #6).

NB: this is the PER-PERSON statuses accessor on the browser service.
Distinct from Phase 3e's cross-person status query (which targeted a
different code-table lookup path).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block


_STATUS_RECORD_FIELDS: tuple[str, ...] = (
    "sequence",            # sd.c_sequence (IsDBNull → 0)
    "status",              # JoinDisplay(sc.c_status_desc_chn, sc.c_status_desc)
    "first_year",          # sd.c_firstyear
    "first_nianhao",       # JoinDisplay(fy_nh.c_nianhao_chn, fy_nh.c_nianhao_pin)
    "first_nianhao_year",  # sd.c_fy_nh_year
    "first_range",         # JoinDisplay(fy_range.c_range_chn, fy_range.c_range)
    "last_year",           # sd.c_lastyear
    "last_nianhao",        # JoinDisplay(ly_nh.c_nianhao_chn, ly_nh.c_nianhao_pin)
    "last_nianhao_year",   # sd.c_ly_nh_year
    "last_range",          # JoinDisplay(ly_range.c_range_chn, ly_range.c_range)
    "source",              # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",               # sd.c_pages
    "notes",               # sd.c_notes
)
_STATUS_ID_FIELDS: tuple[str, ...] = ("status_code",)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_statuses_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "STATUS_DATA sd")


def statuses_person_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_statuses_sql(cs_path)
    augmented = template.replace(
        "sd.c_notes\nFROM",
        "sd.c_notes,\n    sd.c_status_code\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "statuses SQL extracted from C# no longer matches the "
            "expected shape (missing `sd.c_notes\\nFROM` anchor)."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            (seq, s_chn, s_en, fy, fynh_chn, fynh_py, fyny,
             fyr_chn, fyr_en, ly, lynh_chn, lynh_py, lyny,
             lyr_chn, lyr_en, src_chn, src_en, pages, notes,
             status_code) = r
            rows.append({
                "sequence":           seq if seq is not None else 0,
                "status":             _join_display(s_chn, s_en),
                "first_year":         fy,
                "first_nianhao":      _join_display(fynh_chn, fynh_py),
                "first_nianhao_year": fyny,
                "first_range":        _join_display(fyr_chn, fyr_en),
                "last_year":          ly,
                "last_nianhao":       _join_display(lynh_chn, lynh_py),
                "last_nianhao_year":  lyny,
                "last_range":         _join_display(lyr_chn, lyr_en),
                "source":             _join_display(src_chn, src_en),
                "pages":              pages,
                "notes":              notes,
                "status_code":        status_code,
            })
    return rows


def statuses_person_field_names() -> tuple[str, ...]:
    return _STATUS_RECORD_FIELDS


def statuses_person_id_field_names() -> tuple[str, ...]:
    return _STATUS_ID_FIELDS


__all__ = [
    "statuses_person_field_names",
    "statuses_person_id_field_names",
    "statuses_person_query",
]
