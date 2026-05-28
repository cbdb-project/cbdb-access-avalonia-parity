"""Access-side bridge for Phase 4 / Tier 2 entries per-person accessor.

Same shape as `cbdb_parity.access_altnames`: hand-mirror the Avalonia
SQL with Access-ODBC-friendly nested-parens chained LEFT JOINs (Jet
won't accept the bare sqlite3 form), apply identical JoinDisplay
post-processing so the row dicts diff cleanly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display

# Avalonia GetEntriesAsync query transcribed for Access ODBC. The
# ONLY change from the sqlite3 version is parenthesising every
# chained LEFT JOIN — Jet otherwise raises `Syntax error (missing
# operator)`. Column list and ORDER BY are byte-for-byte identical.
_ACCESS_SQL = """
SELECT
    ed.c_sequence,
    ec.c_entry_desc_chn,
    ec.c_entry_desc,
    ed.c_exam_rank,
    ed.c_year,
    nh.c_nianhao_chn,
    nh.c_nianhao_pin,
    ed.c_entry_nh_year,
    yr.c_range_chn,
    yr.c_range,
    ed.c_age,
    kc.c_kinrel_chn,
    kc.c_kinrel,
    kin.c_name_chn,
    kin.c_name,
    ac.c_assoc_desc_chn,
    ac.c_assoc_desc,
    assoc.c_name_chn,
    assoc.c_name,
    sinc.c_inst_name_hz,
    sinc.c_inst_name_py,
    addr.c_name_chn,
    addr.c_name,
    psc.c_parental_status_desc_chn,
    psc.c_parental_status_desc,
    src.c_title_chn,
    src.c_title,
    ed.c_pages,
    ed.c_notes,
    ed.c_posting_notes,
    ed.c_entry_code
FROM ((((((((((ENTRY_DATA ed
       LEFT JOIN ENTRY_CODES ec ON ec.c_entry_code = ed.c_entry_code)
       LEFT JOIN NIAN_HAO nh ON nh.c_nianhao_id = ed.c_entry_nh_id)
       LEFT JOIN YEAR_RANGE_CODES yr ON yr.c_range_code = ed.c_entry_range)
       LEFT JOIN KINSHIP_CODES kc ON kc.c_kincode = ed.c_kin_code)
       LEFT JOIN BIOG_MAIN kin ON kin.c_personid = ed.c_kin_id)
       LEFT JOIN ASSOC_CODES ac ON ac.c_assoc_code = ed.c_assoc_code)
       LEFT JOIN BIOG_MAIN assoc ON assoc.c_personid = ed.c_assoc_id)
       LEFT JOIN SOCIAL_INSTITUTION_NAME_CODES sinc ON sinc.c_inst_name_code = ed.c_inst_name_code)
       LEFT JOIN ADDR_CODES addr ON addr.c_addr_id = ed.c_entry_addr_id)
       LEFT JOIN PARENTAL_STATUS_CODES psc ON psc.c_parental_status_code = ed.c_parental_status_code)
       LEFT JOIN TEXT_CODES src ON src.c_textid = ed.c_source
WHERE ed.c_personid = ?
ORDER BY ed.c_year, ed.c_sequence, ed.c_entry_code
""".strip()


def entries_query_access(
    mdb_path: Path,
    person_id: int,
) -> list[dict[str, Any]]:
    """Run the entries query against `mdb_path` via pyodbc."""
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
            (seq, em_chn, em, exam, year, nh_chn, nh_py, nh_year,
             yr_chn, yr_en, age, kin_chn, kin_en, kin_name_chn, kin_name,
             ac_chn, ac_en, assoc_chn, assoc_en, inst_chn, inst_py,
             addr_chn, addr_en, ps_chn, ps_en, src_chn, src_en,
             pages, notes, posting_notes, entry_code) = r
            rows.append({
                "sequence":             seq if seq is not None else 0,
                "entry_method":         _join_display(em_chn, em),
                "exam_rank":            exam,
                "year":                 year,
                "nianhao":              _join_display(nh_chn, nh_py),
                "nianhao_year":         nh_year,
                "dynasty":              None,
                "range":                _join_display(yr_chn, yr_en),
                "age":                  age,
                "kinship":              _join_display(kin_chn, kin_en),
                "kin_name_chn":         kin_name_chn,
                "kin_name":             kin_name,
                "association":          _join_display(ac_chn, ac_en),
                "associate_name_chn":   assoc_chn,
                "associate_name":       assoc_en,
                "institution_name_chn": inst_chn,
                "institution_name":     inst_py,
                "entry_address_chn":    addr_chn,
                "entry_address":        addr_en,
                "parental_status":      _join_display(ps_chn, ps_en),
                "source":               _join_display(src_chn, src_en),
                "pages":                pages,
                "notes":                notes,
                "posting_notes":        posting_notes,
                "entry_code":           entry_code,
            })
        cur.close()
    return rows


__all__ = ["entries_query_access"]
