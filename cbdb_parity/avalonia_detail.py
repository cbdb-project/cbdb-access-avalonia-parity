"""Python re-execution of Avalonia GetDetailAsync (the basic
person-detail SELECT + 12 COUNT subqueries) — Phase 4, Tier 2
per-person accessor #13.

We diff the SELECT output + the 12 counts. The C# `Fields` list
(FK-enriched dump of BIOG_MAIN fields) is NOT replicated here —
it's enrichment metadata produced by a separate LoadBiogMainFieldsAsync
code path that uses dynamic FK resolution; out of scope for parity.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block


_DETAIL_FIELDS: tuple[str, ...] = (
    "person_id", "surname_chn", "mingzi_chn", "surname", "mingzi",
    "surname_proper", "mingzi_proper", "surname_rm", "mingzi_rm",
    "name", "name_chn",
    "index_year", "index_year_type", "index_year_source",
    "dynasty", "dynasty_chn",
    "birth_year", "death_year", "gender",
    "index_address", "index_address_chn", "index_address_type",
    "address_count", "alt_name_count", "kin_count", "assoc_count",
    "office_count", "entry_count", "event_count", "status_count",
    "text_count", "possession_count", "source_count", "institution_count",
)


_COUNT_QUERIES: dict[str, str] = {
    "address_count":     "SELECT COUNT(*) FROM BIOG_ADDR_DATA WHERE c_personid = ?",
    "alt_name_count":    "SELECT COUNT(*) FROM ALTNAME_DATA WHERE c_personid = ?",
    "kin_count":         "SELECT COUNT(*) FROM KIN_DATA WHERE c_personid = ?",
    "assoc_count":       "SELECT COUNT(*) FROM ASSOC_DATA WHERE c_personid = ?",
    "office_count":      "SELECT COUNT(*) FROM POSTED_TO_OFFICE_DATA WHERE c_personid = ?",
    "entry_count":       "SELECT COUNT(*) FROM ENTRY_DATA WHERE c_personid = ?",
    "event_count":       "SELECT COUNT(*) FROM EVENTS_DATA WHERE c_personid = ?",
    "status_count":      "SELECT COUNT(*) FROM STATUS_DATA WHERE c_personid = ?",
    "text_count":        "SELECT COUNT(*) FROM BIOG_TEXT_DATA WHERE c_personid = ?",
    "possession_count":  "SELECT COUNT(*) FROM POSSESSION_DATA WHERE c_personid = ?",
    "source_count":      "SELECT COUNT(*) FROM BIOG_SOURCE_DATA WHERE c_personid = ?",
    "institution_count": "SELECT COUNT(*) FROM BIOG_INST_DATA WHERE c_personid = ?",
}


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_detail_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "INDEXYEAR_TYPE_CODES")


def _gender_label(value: Any) -> str:
    if value is None:
        return "Unknown"
    return "F" if value == 1 else "M"


def detail_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    sql = _csharp_params_to_sqlite(_load_get_detail_sql(cs_path))
    with sqlite3.connect(sqlite_path) as conn:
        cur = conn.execute(sql, {"personId": person_id})
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
            # C#: `reader.IsDBNull(24) ? (reader.IsDBNull(23) ? null :
            # Convert.ToString(reader.GetValue(23))) : reader.GetString(24)`
            # — prefer COALESCE(c_addr_desc_chn, c_addr_desc); fall back
            # to stringified c_index_addr_type_code.
            "index_address_type": (
                idx_addr_type_desc_coalesced
                if idx_addr_type_desc_coalesced is not None
                else (None if idx_addr_type_code is None else str(idx_addr_type_code))
            ),
        }
        for name_, count_sql in _COUNT_QUERIES.items():
            cur2 = conn.execute(count_sql.replace("?", ":pid"), {"pid": person_id})
            result[name_] = cur2.fetchone()[0]
    return [result]


def detail_field_names() -> tuple[str, ...]:
    return _DETAIL_FIELDS


__all__ = [
    "detail_field_names",
    "detail_query",
]
