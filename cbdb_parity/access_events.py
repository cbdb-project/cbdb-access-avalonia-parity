"""Access-side bridge for Phase 4 / Tier 2 events accessor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none
from cbdb_parity.avalonia_altnames import _join_display


_ACCESS_SQL = """
SELECT
    ed.c_sequence,
    ec.c_event_name_chn,
    ec.c_event_name,
    ed.c_role,
    ed.c_year,
    nh.c_nianhao_chn,
    nh.c_nianhao_pin,
    ed.c_nh_year,
    ed.c_month,
    ed.c_intercalary,
    ed.c_day,
    gz.c_ganzhi_chn,
    gz.c_ganzhi_py,
    yr.c_range_chn,
    yr.c_range,
    addr.c_name_chn,
    addr.c_name,
    src.c_title_chn,
    src.c_title,
    ed.c_pages,
    ed.c_event,
    ed.c_notes,
    ed.c_event_code
FROM (((((EVENTS_DATA ed
      LEFT JOIN EVENT_CODES ec ON ec.c_event_code = ed.c_event_code)
      LEFT JOIN NIAN_HAO nh ON nh.c_nianhao_id = ed.c_nh_code)
      LEFT JOIN GANZHI_CODES gz ON gz.c_ganzhi_code = ed.c_day_ganzhi)
      LEFT JOIN YEAR_RANGE_CODES yr ON yr.c_range_code = ed.c_yr_range)
      LEFT JOIN ADDR_CODES addr ON addr.c_addr_id = ed.c_addr_id)
      LEFT JOIN TEXT_CODES src ON src.c_textid = ed.c_source
WHERE ed.c_personid = ?
ORDER BY ed.c_year, ed.c_sequence, ed.c_event_code
""".strip()


def events_query_access(
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
            (seq, e_chn, e_en, role, year, nh_chn, nh_py, nh_year,
             month, interc, day, gz_chn, gz_py, yr_chn, yr_en,
             addr_chn, addr_en, src_chn, src_en, pages, event_text, notes,
             event_code) = r
            rows.append({
                "sequence":     seq if seq is not None else 0,
                "event_name":   _join_display(e_chn, e_en),
                "role":         role,
                "year":         year,
                "nianhao":      _join_display(nh_chn, nh_py),
                "nianhao_year": nh_year,
                "month":        month,
                "intercalary":  _to_bool_or_none(interc),
                "day":          day,
                "ganzhi":       _join_display(gz_chn, gz_py),
                "range":            _join_display(yr_chn, yr_en),
                "address_name_chn": addr_chn,
                "address_name":     addr_en,
                "source":           _join_display(src_chn, src_en),
                "pages":            pages,
                "event_text":       event_text,
                "notes":            notes,
                "event_code":       event_code,
            })
        cur.close()
    return rows


__all__ = ["events_query_access"]
