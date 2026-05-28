"""Access-side bridge for Phase 4 / Tier 2 possessions accessor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display


_ACCESS_SQL = """
SELECT
    pd.c_possession_record_id,
    pd.c_sequence,
    pd.c_possession_desc_chn,
    pd.c_possession_desc,
    pac.c_possession_act_desc_chn,
    pac.c_possession_act_desc,
    pd.c_quantity,
    mc.c_measure_desc_chn,
    mc.c_measure_desc,
    pd.c_possession_yr,
    nh.c_nianhao_chn,
    nh.c_nianhao_pin,
    pd.c_possession_nh_yr,
    yr.c_range_chn,
    yr.c_range,
    addr.c_name_chn,
    addr.c_name,
    src.c_title_chn,
    src.c_title,
    pd.c_pages,
    pd.c_notes
FROM (((((POSSESSION_DATA pd
      LEFT JOIN POSSESSION_ACT_CODES pac ON pac.c_possession_act_code = pd.c_possession_act_code)
      LEFT JOIN MEASURE_CODES mc ON mc.c_measure_code = pd.c_measure_code)
      LEFT JOIN NIAN_HAO nh ON nh.c_nianhao_id = pd.c_possession_nh_code)
      LEFT JOIN YEAR_RANGE_CODES yr ON yr.c_range_code = pd.c_possession_yr_range)
      LEFT JOIN ADDR_CODES addr ON addr.c_addr_id = pd.c_addr_id)
      LEFT JOIN TEXT_CODES src ON src.c_textid = pd.c_source
WHERE pd.c_personid = ?
ORDER BY pd.c_sequence, pd.c_possession_record_id
""".strip()


def possessions_query_access(
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
        cur.close()
    return rows


__all__ = ["possessions_query_access"]
