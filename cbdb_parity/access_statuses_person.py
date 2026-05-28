"""Access-side bridge for Phase 4 / Tier 2 per-person statuses accessor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display


_ACCESS_SQL = """
SELECT
    sd.c_sequence,
    sc.c_status_desc_chn,
    sc.c_status_desc,
    sd.c_firstyear,
    fy_nh.c_nianhao_chn,
    fy_nh.c_nianhao_pin,
    sd.c_fy_nh_year,
    fy_range.c_range_chn,
    fy_range.c_range,
    sd.c_lastyear,
    ly_nh.c_nianhao_chn,
    ly_nh.c_nianhao_pin,
    sd.c_ly_nh_year,
    ly_range.c_range_chn,
    ly_range.c_range,
    src.c_title_chn,
    src.c_title,
    sd.c_pages,
    sd.c_notes,
    sd.c_status_code
FROM (((((STATUS_DATA sd
      LEFT JOIN STATUS_CODES sc ON sc.c_status_code = sd.c_status_code)
      LEFT JOIN NIAN_HAO fy_nh ON fy_nh.c_nianhao_id = sd.c_fy_nh_code)
      LEFT JOIN YEAR_RANGE_CODES fy_range ON fy_range.c_range_code = sd.c_fy_range)
      LEFT JOIN NIAN_HAO ly_nh ON ly_nh.c_nianhao_id = sd.c_ly_nh_code)
      LEFT JOIN YEAR_RANGE_CODES ly_range ON ly_range.c_range_code = sd.c_ly_range)
      LEFT JOIN TEXT_CODES src ON src.c_textid = sd.c_source
WHERE sd.c_personid = ?
ORDER BY sd.c_sequence, sd.c_status_code
""".strip()


def statuses_person_query_access(
    mdb_path: Path,
    person_id: int,
) -> list[dict[str, Any]]:
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
        cur.close()
    return rows


__all__ = ["statuses_person_query_access"]
