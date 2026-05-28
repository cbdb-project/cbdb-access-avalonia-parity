"""Access-side bridge for Phase 4 / Tier 2 institutions accessor.

10 LEFT JOINs → 9 opening parens before BIOG_INST_DATA. The
SOCIAL_INSTITUTION_ADDR join uses a compound ON condition (2 cols).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display


_ACCESS_SQL = """
SELECT
    sinc.c_inst_name_hz,
    sinc.c_inst_name_py,
    bic.c_bi_role_chn,
    bic.c_bi_role_desc,
    bid.c_bi_begin_year,
    by_nh.c_nianhao_chn,
    by_nh.c_nianhao_pin,
    bid.c_bi_by_nh_year,
    by_range.c_range_chn,
    by_range.c_range,
    bid.c_bi_end_year,
    ey_nh.c_nianhao_chn,
    ey_nh.c_nianhao_pin,
    bid.c_bi_ey_nh_year,
    ey_range.c_range_chn,
    ey_range.c_range,
    ac.c_name_chn,
    ac.c_name,
    siat.c_inst_addr_type_chn,
    siat.c_inst_addr_type_desc,
    src.c_title_chn,
    src.c_title,
    bid.c_pages,
    bid.c_notes,
    sia.inst_xcoord,
    sia.inst_ycoord,
    bid.c_inst_name_code,
    bid.c_inst_code
FROM (((((((((BIOG_INST_DATA bid
      LEFT JOIN SOCIAL_INSTITUTION_NAME_CODES sinc ON sinc.c_inst_name_code = bid.c_inst_name_code)
      LEFT JOIN BIOG_INST_CODES bic ON bic.c_bi_role_code = bid.c_bi_role_code)
      LEFT JOIN NIAN_HAO by_nh ON by_nh.c_nianhao_id = bid.c_bi_by_nh_code)
      LEFT JOIN YEAR_RANGE_CODES by_range ON by_range.c_range_code = bid.c_bi_by_range)
      LEFT JOIN NIAN_HAO ey_nh ON ey_nh.c_nianhao_id = bid.c_bi_ey_nh_code)
      LEFT JOIN YEAR_RANGE_CODES ey_range ON ey_range.c_range_code = bid.c_bi_ey_range)
      LEFT JOIN SOCIAL_INSTITUTION_ADDR sia
          ON sia.c_inst_code = bid.c_inst_code
         AND sia.c_inst_name_code = bid.c_inst_name_code)
      LEFT JOIN ADDR_CODES ac ON ac.c_addr_id = sia.c_inst_addr_id)
      LEFT JOIN SOCIAL_INSTITUTION_ADDR_TYPES siat ON siat.c_inst_addr_type_code = sia.c_inst_addr_type_code)
      LEFT JOIN TEXT_CODES src ON src.c_textid = bid.c_source
WHERE bid.c_personid = ?
ORDER BY bid.c_bi_begin_year, bid.c_inst_name_code, bid.c_inst_code
""".strip()


def institutions_query_access(
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
        cur.close()
    return rows


__all__ = ["institutions_query_access"]
