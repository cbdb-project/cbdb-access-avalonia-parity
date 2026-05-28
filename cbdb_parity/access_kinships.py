"""Access-side bridge for Phase 4 / Tier 2 kinships accessor (non-expanded)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display


_ACCESS_SQL = """
SELECT
    kd.c_kin_id,
    kc.c_kinrel_simplified,
    kc.c_kinrel_chn,
    kc.c_kinrel,
    kin.c_name_chn,
    kin.c_name,
    kc.c_upstep,
    kc.c_dwnstep,
    kc.c_marstep,
    kc.c_colstep,
    src.c_title_chn,
    src.c_title,
    kd.c_pages,
    kd.c_notes,
    kd.c_kin_code
FROM ((KIN_DATA kd
      LEFT JOIN KINSHIP_CODES kc ON kc.c_kincode = kd.c_kin_code)
      LEFT JOIN BIOG_MAIN kin ON kin.c_personid = kd.c_kin_id)
      LEFT JOIN TEXT_CODES src ON src.c_textid = kd.c_source
WHERE kd.c_personid = ?
ORDER BY kd.c_kin_id, kd.c_kin_code
""".strip()


def kinships_query_access(
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
            (kin_pid, _kin_simplified, kin_chn, kin_en,
             kin_name_chn, kin_name, up, down, mar, col,
             src_chn, src_en, pages, notes, kin_code) = r
            rows.append({
                "kin_person_id":   kin_pid if kin_pid is not None else 0,
                "kinship":         _join_display(kin_chn, kin_en),
                "kin_name_chn":    kin_name_chn,
                "kin_name":        kin_name,
                "up_step":         up,
                "down_step":       down,
                "marriage_step":   mar,
                "collateral_step": col,
                "source":          _join_display(src_chn, src_en),
                "pages":           pages,
                "notes":           notes,
                "kin_code":        kin_code,
            })
        cur.close()
    return rows


__all__ = ["kinships_query_access"]
