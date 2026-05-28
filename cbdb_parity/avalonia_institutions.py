"""Python re-execution of Avalonia GetInstitutionsAsync
(Phase 4, Tier 2 per-person accessor #12).

26-col SELECT + 10 LEFT JOINs. No bool fields. The `sia.inst_xcoord`
/ `inst_ycoord` columns are read as doubles. Diff key (begin_year,
inst_name_code, inst_code) — splice raw bid.c_inst_name_code,
bid.c_inst_code from BIOG_INST_DATA.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block


_INSTITUTION_RECORD_FIELDS: tuple[str, ...] = (
    "institution_name_chn",  # sinc.c_inst_name_hz
    "institution_name",      # sinc.c_inst_name_py
    "role",                  # JoinDisplay(bic.c_bi_role_chn, bic.c_bi_role_desc)
    "begin_year",            # bid.c_bi_begin_year
    "begin_nianhao",         # JoinDisplay(by_nh.c_nianhao_chn, by_nh.c_nianhao_pin)
    "begin_nianhao_year",    # bid.c_bi_by_nh_year
    "begin_range",           # JoinDisplay(by_range.c_range_chn, by_range.c_range)
    "end_year",              # bid.c_bi_end_year
    "end_nianhao",           # JoinDisplay(ey_nh.c_nianhao_chn, ey_nh.c_nianhao_pin)
    "end_nianhao_year",      # bid.c_bi_ey_nh_year
    "end_range",             # JoinDisplay(ey_range.c_range_chn, ey_range.c_range)
    "place_name_chn",        # ac.c_name_chn
    "place_name",            # ac.c_name
    "place_type",            # JoinDisplay(siat.c_inst_addr_type_chn, siat.c_inst_addr_type_desc)
    "source",                # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",                 # bid.c_pages
    "notes",                 # bid.c_notes
    "x_coord",               # sia.inst_xcoord (double)
    "y_coord",               # sia.inst_ycoord (double)
)
_INSTITUTION_ID_FIELDS: tuple[str, ...] = ("inst_name_code", "inst_code")


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_institutions_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "BIOG_INST_DATA bid")


def institutions_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_institutions_sql(cs_path)
    augmented = template.replace(
        "sia.inst_ycoord\nFROM",
        "sia.inst_ycoord,\n    bid.c_inst_name_code,\n    bid.c_inst_code\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "institutions SQL extracted from C# no longer matches the "
            "expected shape (missing `sia.inst_ycoord\\nFROM` anchor)."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            (in_chn, in_py, br_chn, br_en, by, bn_chn, bn_py, bny,
             br2_chn, br2_en, ey, en_chn, en_py, eny,
             er_chn, er_en, an_chn, an_en, sat_chn, sat_en,
             src_chn, src_en, pages, notes, xc, yc,
             inst_name_code, inst_code) = r
            rows.append({
                "institution_name_chn": in_chn,
                "institution_name":     in_py,
                "role":                 _join_display(br_chn, br_en),
                "begin_year":           by,
                "begin_nianhao":        _join_display(bn_chn, bn_py),
                "begin_nianhao_year":   bny,
                "begin_range":          _join_display(br2_chn, br2_en),
                "end_year":             ey,
                "end_nianhao":          _join_display(en_chn, en_py),
                "end_nianhao_year":     eny,
                "end_range":            _join_display(er_chn, er_en),
                "place_name_chn":       an_chn,
                "place_name":           an_en,
                "place_type":           _join_display(sat_chn, sat_en),
                "source":               _join_display(src_chn, src_en),
                "pages":                pages,
                "notes":                notes,
                "x_coord":              xc,
                "y_coord":              yc,
                "inst_name_code":       inst_name_code,
                "inst_code":            inst_code,
            })
    return rows


def institutions_field_names() -> tuple[str, ...]:
    return _INSTITUTION_RECORD_FIELDS


def institutions_id_field_names() -> tuple[str, ...]:
    return _INSTITUTION_ID_FIELDS


__all__ = [
    "institutions_field_names",
    "institutions_id_field_names",
    "institutions_query",
]
