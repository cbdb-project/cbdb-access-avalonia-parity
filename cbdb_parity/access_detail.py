"""Access-side bridge for Phase 4 / Tier 2 detail accessor.

Replicates the SQLite CASE/CAST/concat for c_index_year_source via
Access IIf + `&`. 5 LEFT JOINs → 4 opening parens before BIOG_MAIN.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_detail import _COUNT_QUERIES, _gender_label


_ACCESS_SQL = """
SELECT
    b.c_personid,
    b.c_surname_chn,
    b.c_mingzi_chn,
    b.c_surname,
    b.c_mingzi,
    b.c_surname_proper,
    b.c_mingzi_proper,
    b.c_surname_rm,
    b.c_mingzi_rm,
    b.c_name,
    b.c_name_chn,
    b.c_index_year,
    b.c_index_year_type_code,
    iy.c_index_year_type_hz,
    iy.c_index_year_type_desc,
    IIf(b.c_index_year_source_id IS NULL,
        NULL,
        CStr(b.c_index_year_source_id)
        & IIf(src.c_name_chn IS NOT NULL AND Trim(src.c_name_chn) <> '',
              ' / ' & Trim(src.c_name_chn),
              '')
        & IIf(src.c_name IS NOT NULL AND Trim(src.c_name) <> '',
              ' / ' & Trim(src.c_name),
              '')
    ) AS index_year_source,
    d.c_dynasty,
    d.c_dynasty_chn,
    b.c_birthyear,
    b.c_deathyear,
    b.c_female,
    ac.c_name,
    ac.c_name_chn,
    b.c_index_addr_type_code,
    IIf(bac.c_addr_desc_chn IS NULL, bac.c_addr_desc, bac.c_addr_desc_chn) AS idx_addr_type_desc
FROM ((((BIOG_MAIN b
      LEFT JOIN INDEXYEAR_TYPE_CODES iy ON iy.c_index_year_type_code = b.c_index_year_type_code)
      LEFT JOIN BIOG_MAIN src ON src.c_personid = b.c_index_year_source_id)
      LEFT JOIN DYNASTIES d ON d.c_dy = b.c_dy)
      LEFT JOIN ADDR_CODES ac ON ac.c_addr_id = b.c_index_addr_id)
      LEFT JOIN BIOG_ADDR_CODES bac ON bac.c_addr_type = b.c_index_addr_type_code
WHERE b.c_personid = ?
""".strip()


def detail_query_access(
    mdb_path: Path,
    person_id: int,
) -> list[dict[str, Any]]:
    import pyodbc

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    with pyodbc.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute(_ACCESS_SQL, person_id)
        row = cur.fetchone()
        if row is None:
            return []
        (pid, sn_chn, mz_chn, sn, mz, snp, mzp, snrm, mzrm,
         name, name_chn, iy, iy_type_code, iy_type_hz, iy_type_desc,
         iy_source, dy, dy_chn, by, dy_year, female,
         addr_en, addr_chn, idx_addr_type_code,
         idx_addr_type_desc_coalesced) = row
        result = {
            "person_id":          pid,
            "surname_chn":        sn_chn,
            "mingzi_chn":         mz_chn,
            "surname":            sn,
            "mingzi":             mz,
            "surname_proper":     snp,
            "mingzi_proper":      mzp,
            "surname_rm":         snrm,
            "mingzi_rm":          mzrm,
            "name":               name,
            "name_chn":           name_chn,
            "index_year":         iy,
            "index_year_type":    _join_display(iy_type_hz, iy_type_desc),
            "index_year_source":  iy_source,
            "dynasty":            dy,
            "dynasty_chn":        dy_chn,
            "birth_year":         by,
            "death_year":         dy_year,
            "gender":             _gender_label(female),
            "index_address":      addr_en,
            "index_address_chn":  addr_chn,
            "index_address_type": (
                idx_addr_type_desc_coalesced
                if idx_addr_type_desc_coalesced is not None
                else (None if idx_addr_type_code is None else str(idx_addr_type_code))
            ),
        }
        for name_, count_sql in _COUNT_QUERIES.items():
            cur2 = conn.cursor()
            cur2.execute(count_sql, person_id)
            result[name_] = cur2.fetchone()[0]
            cur2.close()
        cur.close()
    return [result]


__all__ = ["detail_query_access"]
