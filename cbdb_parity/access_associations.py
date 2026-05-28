"""Access-side bridge for Phase 4 / Tier 2 associations accessor.

16 LEFT JOINs → 15 opening parens before ASSOC_DATA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none
from cbdb_parity.avalonia_altnames import _join_display


_ACCESS_SQL = """
SELECT
    ad.c_sequence,
    ad.c_assoc_count,
    ad.c_assoc_id,
    assoc_person.c_name_chn,
    assoc_person.c_name,
    ac.c_assoc_desc_chn,
    ac.c_assoc_desc,
    kin_code.c_kinrel_chn,
    kin_code.c_kinrel,
    ad.c_kin_id,
    kin_person.c_name_chn,
    kin_person.c_name,
    assoc_kin_code.c_kinrel_chn,
    assoc_kin_code.c_kinrel,
    ad.c_assoc_kin_id,
    assoc_kin_person.c_name_chn,
    assoc_kin_person.c_name,
    ad.c_assoc_claimer_id,
    claimer_person.c_name_chn,
    claimer_person.c_name,
    assoc_addr.c_name_chn,
    assoc_addr.c_name,
    ad.c_assoc_first_year,
    fy_nh.c_nianhao_chn,
    fy_nh.c_nianhao_pin,
    ad.c_assoc_fy_nh_year,
    ad.c_assoc_fy_month,
    ad.c_assoc_fy_intercalary,
    ad.c_assoc_fy_day,
    fy_gz.c_ganzhi_chn,
    fy_gz.c_ganzhi_py,
    fy_range.c_range_chn,
    fy_range.c_range,
    topic.c_topic_desc_chn,
    topic.c_topic_desc,
    inst.c_inst_name_hz,
    inst.c_inst_name_py,
    occ.c_occasion_desc_chn,
    occ.c_occasion_desc,
    genre.c_lit_genre_desc_chn,
    genre.c_lit_genre_desc,
    ad.c_text_title,
    src.c_title_chn,
    src.c_title,
    ad.c_pages,
    ad.c_notes,
    ad.c_assoc_code
FROM (((((((((((((((ASSOC_DATA ad
      LEFT JOIN BIOG_MAIN assoc_person ON assoc_person.c_personid = ad.c_assoc_id)
      LEFT JOIN ASSOC_CODES ac ON ac.c_assoc_code = ad.c_assoc_code)
      LEFT JOIN KINSHIP_CODES kin_code ON kin_code.c_kincode = ad.c_kin_code)
      LEFT JOIN BIOG_MAIN kin_person ON kin_person.c_personid = ad.c_kin_id)
      LEFT JOIN KINSHIP_CODES assoc_kin_code ON assoc_kin_code.c_kincode = ad.c_assoc_kin_code)
      LEFT JOIN BIOG_MAIN assoc_kin_person ON assoc_kin_person.c_personid = ad.c_assoc_kin_id)
      LEFT JOIN BIOG_MAIN claimer_person ON claimer_person.c_personid = ad.c_assoc_claimer_id)
      LEFT JOIN ADDR_CODES assoc_addr ON assoc_addr.c_addr_id = ad.c_addr_id)
      LEFT JOIN NIAN_HAO fy_nh ON fy_nh.c_nianhao_id = ad.c_assoc_fy_nh_code)
      LEFT JOIN GANZHI_CODES fy_gz ON fy_gz.c_ganzhi_code = ad.c_assoc_fy_day_gz)
      LEFT JOIN YEAR_RANGE_CODES fy_range ON fy_range.c_range_code = ad.c_assoc_fy_range)
      LEFT JOIN SCHOLARLYTOPIC_CODES topic ON topic.c_topic_code = ad.c_topic_code)
      LEFT JOIN SOCIAL_INSTITUTION_NAME_CODES inst ON inst.c_inst_name_code = ad.c_inst_name_code)
      LEFT JOIN OCCASION_CODES occ ON occ.c_occasion_code = ad.c_occasion_code)
      LEFT JOIN LITERARYGENRE_CODES genre ON genre.c_lit_genre_code = ad.c_litgenre_code)
      LEFT JOIN TEXT_CODES src ON src.c_textid = ad.c_source
WHERE ad.c_personid = ?
ORDER BY ad.c_assoc_first_year, ad.c_sequence, ad.c_assoc_code, ad.c_assoc_id
""".strip()


def associations_query_access(
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
            (seq, cnt, ap_id, ap_chn, ap_en, a_chn, a_en,
             kin_chn, kin_en, kin_pid, kp_chn, kp_en,
             ak_chn, ak_en, akp_id, akp_chn, akp_en,
             clm_pid, clm_chn, clm_en, addr_chn, addr_en,
             year, nh_chn, nh_py, nh_year, month, interc, day,
             gz_chn, gz_py, yr_chn, yr_en,
             topic_chn, topic_en, inst_chn, inst_py,
             occ_chn, occ_en, lit_chn, lit_en,
             text_title, src_chn, src_en, pages, notes,
             assoc_code) = r
            rows.append({
                "sequence":                seq if seq is not None else 0,
                "count":                   cnt,
                "associate_person_id":     ap_id,
                "associate_name_chn":      ap_chn,
                "associate_name":          ap_en,
                "association":             _join_display(a_chn, a_en),
                "kinship":                 _join_display(kin_chn, kin_en),
                "kin_person_id":           kin_pid,
                "kin_name_chn":            kp_chn,
                "kin_name":                kp_en,
                "associate_kinship":       _join_display(ak_chn, ak_en),
                "associate_kin_person_id": akp_id,
                "associate_kin_name_chn":  akp_chn,
                "associate_kin_name":      akp_en,
                "claimer_person_id":       clm_pid,
                "claimer_name_chn":        clm_chn,
                "claimer_name":            clm_en,
                "address_name_chn":        addr_chn,
                "address_name":            addr_en,
                "year":                    year,
                "nianhao":                 _join_display(nh_chn, nh_py),
                "nianhao_year":            nh_year,
                "month":                   month,
                "intercalary":             _to_bool_or_none(interc),
                "day":                     day,
                "ganzhi":                  _join_display(gz_chn, gz_py),
                "range":                   _join_display(yr_chn, yr_en),
                "topic_chn":               topic_chn,
                "topic":                   topic_en,
                "institution_name_chn":    inst_chn,
                "institution_name":        inst_py,
                "occasion_chn":            occ_chn,
                "occasion":                occ_en,
                "literary_genre_chn":      lit_chn,
                "literary_genre":          lit_en,
                "text_title":              text_title,
                "source_title_chn":        src_chn,
                "source_title":            src_en,
                "pages":                   pages,
                "notes":                   notes,
                "assoc_code":              assoc_code,
            })
        cur.close()
    return rows


__all__ = ["associations_query_access"]
