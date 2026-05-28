"""Access-side bridge for Phase 4 / Tier 2 addresses per-person accessor.

Same pattern as access_altnames / access_entries: hand-mirrored
Avalonia SQL with Access-ODBC parenthesised chained LEFT JOINs.
9 LEFT JOINs → 9 opening parens before BIOG_ADDR_DATA, 8 closes
distributed (innermost JOIN naked).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none
from cbdb_parity.avalonia_altnames import _join_display

_ACCESS_SQL = """
SELECT
    bad.c_sequence,
    bad.c_natal,
    bac.c_addr_desc,
    bac.c_addr_desc_chn,
    ac.c_name,
    ac.c_name_chn,
    bad.c_firstyear,
    fy_nh.c_nianhao_pin,
    fy_nh.c_nianhao_chn,
    bad.c_fy_nh_year,
    bad.c_fy_month,
    bad.c_fy_intercalary,
    bad.c_fy_day,
    fy_gz.c_ganzhi_py,
    fy_gz.c_ganzhi_chn,
    fy_range.c_range,
    fy_range.c_range_chn,
    bad.c_lastyear,
    ly_nh.c_nianhao_pin,
    ly_nh.c_nianhao_chn,
    bad.c_ly_nh_year,
    bad.c_ly_month,
    bad.c_ly_intercalary,
    bad.c_ly_day,
    ly_gz.c_ganzhi_py,
    ly_gz.c_ganzhi_chn,
    ly_range.c_range,
    ly_range.c_range_chn,
    src.c_title,
    src.c_title_chn,
    bad.c_pages,
    bad.c_notes,
    bad.c_addr_type,
    bad.c_addr_id
FROM ((((((((BIOG_ADDR_DATA bad
      LEFT JOIN BIOG_ADDR_CODES bac ON bac.c_addr_type = bad.c_addr_type)
      LEFT JOIN ADDR_CODES ac ON ac.c_addr_id = bad.c_addr_id)
      LEFT JOIN NIAN_HAO fy_nh ON fy_nh.c_nianhao_id = bad.c_fy_nh_code)
      LEFT JOIN NIAN_HAO ly_nh ON ly_nh.c_nianhao_id = bad.c_ly_nh_code)
      LEFT JOIN GANZHI_CODES fy_gz ON fy_gz.c_ganzhi_code = bad.c_fy_day_gz)
      LEFT JOIN GANZHI_CODES ly_gz ON ly_gz.c_ganzhi_code = bad.c_ly_day_gz)
      LEFT JOIN YEAR_RANGE_CODES fy_range ON fy_range.c_range_code = bad.c_fy_range)
      LEFT JOIN YEAR_RANGE_CODES ly_range ON ly_range.c_range_code = bad.c_ly_range)
      LEFT JOIN TEXT_CODES src ON src.c_textid = bad.c_source
WHERE bad.c_personid = ?
ORDER BY bad.c_sequence, bad.c_addr_type, bad.c_addr_id
""".strip()


def addresses_query_access(
    mdb_path: Path,
    person_id: int,
) -> list[dict[str, Any]]:
    """Run the addresses query against `mdb_path` via pyodbc."""
    import pyodbc

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    rows: list[dict[str, Any]] = []
    with pyodbc.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute(_ACCESS_SQL, person_id)
        for r in cur.fetchall():
            (seq, natal, at_en, at_chn, an_en, an_chn,
             fy, fynh_py, fynh_chn, fyny, fym, fyi, fyd,
             fygz_py, fygz_chn, fyr_en, fyr_chn,
             ly, lynh_py, lynh_chn, lyny, lym, lyi, lyd,
             lygz_py, lygz_chn, lyr_en, lyr_chn,
             src_en, src_chn, pages, notes,
             at_code, addr_id) = r
            rows.append({
                "sequence":           seq if seq is not None else 0,
                "natal":              _to_bool_or_none(natal),
                "address_type":       _join_display(at_chn, at_en),
                "address_name_chn":   an_chn,
                "address_name":       an_en,
                "first_year":         fy,
                "first_nianhao":      _join_display(fynh_chn, fynh_py),
                "first_nianhao_year": fyny,
                "first_month":        fym,
                "first_intercalary":  _to_bool_or_none(fyi),
                "first_day":          fyd,
                "first_ganzhi":       _join_display(fygz_chn, fygz_py),
                "first_range":        _join_display(fyr_chn, fyr_en),
                "last_year":          ly,
                "last_nianhao":       _join_display(lynh_chn, lynh_py),
                "last_nianhao_year":  lyny,
                "last_month":         lym,
                "last_intercalary":   _to_bool_or_none(lyi),
                "last_day":           lyd,
                "last_ganzhi":        _join_display(lygz_chn, lygz_py),
                "last_range":         _join_display(lyr_chn, lyr_en),
                "source":             _join_display(src_chn, src_en),
                "pages":              pages,
                "notes":              notes,
                "addr_type_code":     at_code,
                "addr_id":            addr_id,
            })
        cur.close()
    return rows


__all__ = ["addresses_query_access"]
