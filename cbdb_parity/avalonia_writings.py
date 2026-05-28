"""Python re-execution of Avalonia SqlitePersonBrowserService.GetWritingsAsync
(Phase 4, Tier 2 per-person accessor #4).

Same pattern as altnames/entries/addresses: extract C# SQL, splice
in a raw ID column (`btd.c_role_id`) for stable diff-keying, execute
against sqlite3, apply JoinDisplay post-processing.

`text_id` and `year` are already exposed in the SELECT, so the diff
key is `(year, text_id, role_id)` — matching the SQL's ORDER BY.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block


_WRITING_RECORD_FIELDS: tuple[str, ...] = (
    "text_id",       # btd.c_textid (IsDBNull → 0)
    "title_chn",     # tc.c_title_chn
    "title",         # tc.c_title
    "role",          # JoinDisplay(trc.c_role_desc_chn, trc.c_role_desc)
    "year",          # btd.c_year
    "nianhao",       # JoinDisplay(nh.c_nianhao_chn, nh.c_nianhao_pin)
    "nianhao_year",  # btd.c_nh_year
    "range",         # JoinDisplay(yrc.c_range_chn, yrc.c_range)
    "source",        # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",         # btd.c_pages
    "notes",         # btd.c_notes
)
_WRITING_ID_FIELDS: tuple[str, ...] = ("role_id",)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_writings_sql(cs_path: Path) -> str:
    # `BIOG_TEXT_DATA` is unique to GetWritingsAsync.
    return find_sql_block(cs_path, "BIOG_TEXT_DATA")


def writings_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_writings_sql(cs_path)
    augmented = template.replace(
        "btd.c_notes\nFROM",
        "btd.c_notes,\n    btd.c_role_id\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "writings SQL extracted from C# no longer matches the "
            "expected shape (missing `btd.c_notes\\nFROM` anchor)."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            (text_id, title_chn, title, role_chn, role_en, year,
             nh_chn, nh_py, nh_year, yr_chn, yr_en,
             src_chn, src_en, pages, notes, role_id) = r
            rows.append({
                "text_id":      text_id if text_id is not None else 0,
                "title_chn":    title_chn,
                "title":        title,
                "role":         _join_display(role_chn, role_en),
                "year":         year,
                "nianhao":      _join_display(nh_chn, nh_py),
                "nianhao_year": nh_year,
                "range":        _join_display(yr_chn, yr_en),
                "source":       _join_display(src_chn, src_en),
                "pages":        pages,
                "notes":        notes,
                "role_id":      role_id,
            })
    return rows


def writings_field_names() -> tuple[str, ...]:
    return _WRITING_RECORD_FIELDS


def writings_id_field_names() -> tuple[str, ...]:
    return _WRITING_ID_FIELDS


__all__ = [
    "writings_field_names",
    "writings_id_field_names",
    "writings_query",
]
