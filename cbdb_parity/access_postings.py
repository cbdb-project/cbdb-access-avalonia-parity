"""Access-side bridge for Phase 4 / Tier 2 postings per-person accessor.

16 LEFT JOINs → 15 opening parens before POSTING_DATA, 15 closes
after first 15 JOINs, 16th JOIN naked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_postings import _row_to_dict


_ACCESS_SQL = """
SELECT
    pd.c_posting_id,
    pto.c_office_id,
    pto.c_sequence,
    oc.c_office_chn,
    oc.c_office_pinyin,
    appt.c_appt_desc_chn,
    appt.c_appt_desc,
    assume_office.c_assume_office_desc_chn,
    assume_office.c_assume_office_desc,
    cat.c_category_desc_chn,
    cat.c_category_desc,
    pto.c_firstyear,
    fy_nh.c_nianhao_chn,
    fy_nh.c_nianhao_pin,
    pto.c_fy_nh_year,
    fy_range.c_range_chn,
    fy_range.c_range,
    pto.c_fy_month,
    pto.c_fy_intercalary,
    pto.c_fy_day,
    fy_gz.c_ganzhi_chn,
    fy_gz.c_ganzhi_py,
    pto.c_lastyear,
    ly_nh.c_nianhao_chn,
    ly_nh.c_nianhao_pin,
    pto.c_ly_nh_year,
    ly_range.c_range_chn,
    ly_range.c_range,
    pto.c_ly_month,
    pto.c_ly_intercalary,
    pto.c_ly_day,
    ly_gz.c_ganzhi_chn,
    ly_gz.c_ganzhi_py,
    dy.c_dynasty_chn,
    dy.c_dynasty,
    src.c_title_chn,
    src.c_title,
    pto.c_pages,
    pto.c_notes,
    pto.c_created_by,
    pto.c_created_date,
    pto.c_modified_by,
    pto.c_modified_date,
    office_addr.c_addr_id,
    office_addr.c_name_chn,
    office_addr.c_name,
    pta.c_created_by,
    pta.c_created_date,
    pta.c_modified_by,
    pta.c_modified_date
FROM (((((((((((((((POSTING_DATA pd
      LEFT JOIN POSTED_TO_OFFICE_DATA pto
          ON pto.c_posting_id = pd.c_posting_id
         AND pto.c_personid = pd.c_personid)
      LEFT JOIN POSTED_TO_ADDR_DATA pta
          ON pta.c_posting_id = pto.c_posting_id
         AND pta.c_office_id = pto.c_office_id
         AND pta.c_personid = pto.c_personid)
      LEFT JOIN OFFICE_CODES oc ON oc.c_office_id = pto.c_office_id)
      LEFT JOIN APPOINTMENT_CODES appt ON appt.c_appt_code = pto.c_appt_type_code)
      LEFT JOIN ASSUME_OFFICE_CODES assume_office ON assume_office.c_assume_office_code = pto.c_assume_office_code)
      LEFT JOIN OFFICE_CATEGORIES cat ON cat.c_office_category_id = pto.c_office_category_id)
      LEFT JOIN NIAN_HAO fy_nh ON fy_nh.c_nianhao_id = pto.c_fy_nh_code)
      LEFT JOIN YEAR_RANGE_CODES fy_range ON fy_range.c_range_code = pto.c_fy_range)
      LEFT JOIN GANZHI_CODES fy_gz ON fy_gz.c_ganzhi_code = pto.c_fy_day_gz)
      LEFT JOIN NIAN_HAO ly_nh ON ly_nh.c_nianhao_id = pto.c_ly_nh_code)
      LEFT JOIN YEAR_RANGE_CODES ly_range ON ly_range.c_range_code = pto.c_ly_range)
      LEFT JOIN GANZHI_CODES ly_gz ON ly_gz.c_ganzhi_code = pto.c_ly_day_gz)
      LEFT JOIN DYNASTIES dy ON dy.c_dy = pto.c_dy)
      LEFT JOIN TEXT_CODES src ON src.c_textid = pto.c_source)
      LEFT JOIN ADDR_CODES office_addr ON office_addr.c_addr_id = pta.c_addr_id
WHERE pd.c_personid = ?
ORDER BY pd.c_posting_id, pto.c_sequence, pto.c_office_id, office_addr.c_addr_id
""".strip()


def postings_query_access(
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
            rows.append(_row_to_dict(tuple(r)))
        cur.close()
    return rows


__all__ = ["postings_query_access"]
