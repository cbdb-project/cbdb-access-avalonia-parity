"""Python re-execution of Avalonia GetEventsAsync
(Phase 4, Tier 2 per-person accessor #8).

Bool: c_intercalary (column 9). Diff key (year, sequence, event_code)
— `c_event_code` spliced for diff-keying.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none
from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block


_EVENT_RECORD_FIELDS: tuple[str, ...] = (
    "sequence",      # ed.c_sequence (IsDBNull → 0)
    "event_name",    # JoinDisplay(ec.c_event_name_chn, ec.c_event_name)
    "role",          # ed.c_role
    "year",          # ed.c_year
    "nianhao",       # JoinDisplay(nh.c_nianhao_chn, nh.c_nianhao_pin)
    "nianhao_year",  # ed.c_nh_year
    "month",         # ed.c_month
    "intercalary",   # bool: ed.c_intercalary == 1
    "day",           # ed.c_day
    "ganzhi",        # JoinDisplay(gz.c_ganzhi_chn, gz.c_ganzhi_py)
    "range",         # JoinDisplay(yr.c_range_chn, yr.c_range)
    "address_chn",   # addr.c_name_chn
    "address",       # addr.c_name
    "source",        # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",         # ed.c_pages
    "event",         # ed.c_event
    "notes",         # ed.c_notes
)
_EVENT_ID_FIELDS: tuple[str, ...] = ("event_code",)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_events_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "EVENTS_DATA ed")


def events_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_events_sql(cs_path)
    augmented = template.replace(
        "ed.c_notes\nFROM",
        "ed.c_notes,\n    ed.c_event_code\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "events SQL extracted from C# no longer matches the "
            "expected shape (missing `ed.c_notes\\nFROM` anchor)."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            (seq, e_chn, e_en, role, year, nh_chn, nh_py, nh_year,
             month, interc, day, gz_chn, gz_py, yr_chn, yr_en,
             addr_chn, addr_en, src_chn, src_en, pages, event_text, notes,
             event_code) = r
            rows.append({
                "sequence":     seq if seq is not None else 0,
                "event_name":   _join_display(e_chn, e_en),
                "role":         role,
                "year":         year,
                "nianhao":      _join_display(nh_chn, nh_py),
                "nianhao_year": nh_year,
                "month":        month,
                "intercalary":  _to_bool_or_none(interc),
                "day":          day,
                "ganzhi":       _join_display(gz_chn, gz_py),
                "range":        _join_display(yr_chn, yr_en),
                "address_chn":  addr_chn,
                "address":      addr_en,
                "source":       _join_display(src_chn, src_en),
                "pages":        pages,
                "event":        event_text,
                "notes":        notes,
                "event_code":   event_code,
            })
    return rows


def events_field_names() -> tuple[str, ...]:
    return _EVENT_RECORD_FIELDS


def events_id_field_names() -> tuple[str, ...]:
    return _EVENT_ID_FIELDS


__all__ = [
    "events_field_names",
    "events_id_field_names",
    "events_query",
]
