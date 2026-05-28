"""Python re-execution of Avalonia SqlitePersonBrowserService.GetAddressesAsync
(Phase 4, Tier 2 per-person accessor #3).

Pattern matches altnames/entries: extract C# SQL, splice raw ID
columns for diff-keying, execute via sqlite3, apply JoinDisplay
post-processing.

Caveat specific to addresses: the C# reader passes the Chinese (chn)
column FIRST to `JoinDisplay`, but the SELECT order is English-then-
Chinese (en at index N, chn at N+1). We replicate that swap in Python.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block

# Mirrors `PersonAddressItem` (the C# record). `c_addr_type` and
# `c_addr_id` are raw IDs we add to the SELECT for stable diff-keying
# (they ARE in the ORDER BY already, so the natural unique key per
# person is `(c_sequence, c_addr_type, c_addr_id)`).
_ADDRESS_RECORD_FIELDS: tuple[str, ...] = (
    "sequence",            # bad.c_sequence (IsDBNull → 0)
    "natal",               # bool: bad.c_natal == 1
    "address_type",        # JoinDisplay(bac.c_addr_desc_chn, bac.c_addr_desc)
    "address_name_chn",    # ac.c_name_chn
    "address_name",        # ac.c_name
    "first_year",          # bad.c_firstyear
    "first_nianhao",       # JoinDisplay(fy_nh.c_nianhao_chn, fy_nh.c_nianhao_pin)
    "first_nianhao_year",  # bad.c_fy_nh_year
    "first_month",         # bad.c_fy_month
    "first_intercalary",   # bool: bad.c_fy_intercalary == 1
    "first_day",           # bad.c_fy_day
    "first_ganzhi",        # JoinDisplay(fy_gz.c_ganzhi_chn, fy_gz.c_ganzhi_py)
    "first_range",         # JoinDisplay(fy_range.c_range_chn, fy_range.c_range)
    "last_year",           # bad.c_lastyear
    "last_nianhao",        # JoinDisplay(ly_nh.c_nianhao_chn, ly_nh.c_nianhao_pin)
    "last_nianhao_year",   # bad.c_ly_nh_year
    "last_month",          # bad.c_ly_month
    "last_intercalary",    # bool: bad.c_ly_intercalary == 1
    "last_day",            # bad.c_ly_day
    "last_ganzhi",         # JoinDisplay(ly_gz.c_ganzhi_chn, ly_gz.c_ganzhi_py)
    "last_range",          # JoinDisplay(ly_range.c_range_chn, ly_range.c_range)
    "source",              # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",               # bad.c_pages
    "notes",               # bad.c_notes
)
_ADDRESS_ID_FIELDS: tuple[str, ...] = ("addr_type_code", "addr_id")


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_addresses_sql(cs_path: Path) -> str:
    # `bad.c_sequence` is unique to GetAddressesAsync — the basic-
    # person-detail SELECT also references `c_addr_desc_chn` via its
    # index-address join, so we discriminate on the BIOG_ADDR_DATA
    # alias instead.
    return find_sql_block(cs_path, "bad.c_sequence")


def _to_bool_or_none(v: Any) -> bool | None:
    """Mirrors the C# reader's `IsDBNull(i) ? null : GetInt32(i) == 1`
    pattern for `Natal` / `FirstIntercalary` / `LastIntercalary`."""
    if v is None:
        return None
    return v == 1


def addresses_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_addresses_sql(cs_path)
    # Splice raw `bad.c_addr_type`, `bad.c_addr_id` (the natural
    # identifier columns already in the ORDER BY) into the SELECT for
    # diff-keying.
    augmented = template.replace(
        "bad.c_notes\nFROM",
        "bad.c_notes,\n    bad.c_addr_type,\n    bad.c_addr_id\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "addresses SQL extracted from C# no longer matches the "
            "expected shape (missing `bad.c_notes\\nFROM` anchor). "
            "Inspect SqlitePersonBrowserService.cs for an upstream rewrite."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            (seq, natal, at_en, at_chn, an_en, an_chn,
             fy, fynh_py, fynh_chn, fyny, fym, fyi, fyd,
             fygz_py, fygz_chn, fyr_en, fyr_chn,
             ly, lynh_py, lynh_chn, lyny, lym, lyi, lyd,
             lygz_py, lygz_chn, lyr_en, lyr_chn,
             src_en, src_chn, pages, notes,
             at_code, addr_id) = r
            rows.append({
                "sequence":           seq if seq is not None else 0,
                "natal":              _to_bool_or_none(natal),
                # NB: C# passes Chinese FIRST, English SECOND to
                # JoinDisplay despite SELECT being en-then-chn.
                "address_type":       _join_display(at_chn, at_en),
                "address_name_chn":   an_chn,
                "address_name":       an_en,
                "first_year":         fy,
                "first_nianhao":      _join_display(fynh_chn, fynh_py),
                "first_nianhao_year": fyny,
                "first_month":        fym,
                "first_intercalary":  _to_bool_or_none(fyi),
                "first_day":          fyd,
                "first_ganzhi":       _join_display(fygz_chn, fygz_py),
                "first_range":        _join_display(fyr_chn, fyr_en),
                "last_year":          ly,
                "last_nianhao":       _join_display(lynh_chn, lynh_py),
                "last_nianhao_year":  lyny,
                "last_month":         lym,
                "last_intercalary":   _to_bool_or_none(lyi),
                "last_day":           lyd,
                "last_ganzhi":        _join_display(lygz_chn, lygz_py),
                "last_range":         _join_display(lyr_chn, lyr_en),
                "source":             _join_display(src_chn, src_en),
                "pages":              pages,
                "notes":              notes,
                "addr_type_code":     at_code,
                "addr_id":            addr_id,
            })
    return rows


def addresses_field_names() -> tuple[str, ...]:
    return _ADDRESS_RECORD_FIELDS


def addresses_id_field_names() -> tuple[str, ...]:
    return _ADDRESS_ID_FIELDS


__all__ = [
    "addresses_field_names",
    "addresses_id_field_names",
    "addresses_query",
]
