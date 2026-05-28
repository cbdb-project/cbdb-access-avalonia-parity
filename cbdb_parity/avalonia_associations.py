"""Python re-execution of Avalonia GetAssociationsAsync
(Phase 4, Tier 2 per-person accessor #10).

46-col SELECT + 16 LEFT JOINs. Bool: c_assoc_fy_intercalary
(column 27). Diff key (year, sequence, assoc_code, assoc_id) —
ad.c_assoc_code spliced (sequence/assoc_id/year already in SELECT).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none
from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block


_ASSOC_RECORD_FIELDS: tuple[str, ...] = (
    "sequence", "count", "associate_person_id",
    "associate_name_chn", "associate_name",
    "association", "kinship", "kin_person_id",
    "kin_name_chn", "kin_name",
    "associate_kinship", "associate_kin_person_id",
    "associate_kin_name_chn", "associate_kin_name",
    "claimer_person_id", "claimer_name_chn", "claimer_name",
    "address_name_chn", "address_name",
    "year", "nianhao", "nianhao_year",
    "month", "intercalary", "day",
    "ganzhi", "range",
    "topic_chn", "topic",
    "institution_name_chn", "institution_name",
    "occasion_chn", "occasion",
    "literary_genre_chn", "literary_genre",
    "text_title",
    "source_title_chn", "source_title",
    "pages", "notes",
)
_ASSOC_ID_FIELDS: tuple[str, ...] = ("assoc_code",)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_associations_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "ASSOC_DATA ad")


def associations_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_associations_sql(cs_path)
    augmented = template.replace(
        "ad.c_notes\nFROM",
        "ad.c_notes,\n    ad.c_assoc_code\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "associations SQL extracted from C# no longer matches the "
            "expected shape (missing `ad.c_notes\\nFROM` anchor)."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
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
    return rows


def associations_field_names() -> tuple[str, ...]:
    return _ASSOC_RECORD_FIELDS


def associations_id_field_names() -> tuple[str, ...]:
    return _ASSOC_ID_FIELDS


__all__ = [
    "associations_field_names",
    "associations_id_field_names",
    "associations_query",
]
