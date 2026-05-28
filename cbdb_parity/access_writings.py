"""Access-side bridge for Phase 4 / Tier 2 writings per-person accessor.

5 LEFT JOINs → 4 opening parens before BIOG_TEXT_DATA, 4 closes
after first 4 JOINs, 5th JOIN naked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display


_ACCESS_SQL = """
SELECT
    btd.c_textid,
    tc.c_title_chn,
    tc.c_title,
    trc.c_role_desc_chn,
    trc.c_role_desc,
    btd.c_year,
    nh.c_nianhao_chn,
    nh.c_nianhao_pin,
    btd.c_nh_year,
    yrc.c_range_chn,
    yrc.c_range,
    src.c_title_chn,
    src.c_title,
    btd.c_pages,
    btd.c_notes,
    btd.c_role_id
FROM ((((BIOG_TEXT_DATA btd
      LEFT JOIN TEXT_CODES tc ON tc.c_textid = btd.c_textid)
      LEFT JOIN TEXT_ROLE_CODES trc ON trc.c_role_id = btd.c_role_id)
      LEFT JOIN NIAN_HAO nh ON nh.c_nianhao_id = btd.c_nh_code)
      LEFT JOIN YEAR_RANGE_CODES yrc ON yrc.c_range_code = btd.c_range_code)
      LEFT JOIN TEXT_CODES src ON src.c_textid = btd.c_source
WHERE btd.c_personid = ?
ORDER BY btd.c_year, btd.c_textid, btd.c_role_id
""".strip()


def writings_query_access(
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
        cur.close()
    return rows


__all__ = ["writings_query_access"]
