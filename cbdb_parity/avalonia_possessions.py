"""Python re-execution of Avalonia GetPossessionsAsync
(Phase 4, Tier 2 per-person accessor #7).

`record_id` is column 0 in the SELECT — natural unique key,
no ID splicing required.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block


_POSSESSION_RECORD_FIELDS: tuple[str, ...] = (
    "record_id",          # pd.c_possession_record_id (IsDBNull → 0)
    "sequence",           # pd.c_sequence
    "possession",         # JoinDisplay(pd.c_possession_desc_chn, pd.c_possession_desc)
    "possession_action",  # JoinDisplay(pac.c_possession_act_desc_chn, pac.c_possession_act_desc)
    "quantity",           # pd.c_quantity
    "measure",            # JoinDisplay(mc.c_measure_desc_chn, mc.c_measure_desc)
    "year",               # pd.c_possession_yr
    "nianhao",            # JoinDisplay(nh.c_nianhao_chn, nh.c_nianhao_pin)
    "nianhao_year",       # pd.c_possession_nh_yr
    "range",              # JoinDisplay(yr.c_range_chn, yr.c_range)
    "address_name_chn",   # addr.c_name_chn
    "address_name",       # addr.c_name
    "source",             # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",              # pd.c_pages
    "notes",              # pd.c_notes
)
_POSSESSION_ID_FIELDS: tuple[str, ...] = ()


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_possessions_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "POSSESSION_DATA pd")


def possessions_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    sql = _csharp_params_to_sqlite(_load_get_possessions_sql(cs_path))
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            (rec_id, seq, p_chn, p_en, pa_chn, pa_en, qty,
             m_chn, m_en, year, nh_chn, nh_py, nh_year,
             yr_chn, yr_en, addr_chn, addr_en,
             src_chn, src_en, pages, notes) = r
            rows.append({
                "record_id":          rec_id if rec_id is not None else 0,
                "sequence":           seq,
                "possession":         _join_display(p_chn, p_en),
                "possession_action":  _join_display(pa_chn, pa_en),
                "quantity":           qty,
                "measure":            _join_display(m_chn, m_en),
                "year":               year,
                "nianhao":            _join_display(nh_chn, nh_py),
                "nianhao_year":       nh_year,
                "range":              _join_display(yr_chn, yr_en),
                "address_name_chn":   addr_chn,
                "address_name":       addr_en,
                "source":             _join_display(src_chn, src_en),
                "pages":              pages,
                "notes":              notes,
            })
    return rows


def possessions_field_names() -> tuple[str, ...]:
    return _POSSESSION_RECORD_FIELDS


def possessions_id_field_names() -> tuple[str, ...]:
    return _POSSESSION_ID_FIELDS


__all__ = [
    "possessions_field_names",
    "possessions_id_field_names",
    "possessions_query",
]
