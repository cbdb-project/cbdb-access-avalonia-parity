"""Python re-execution of Avalonia SqlitePersonBrowserService.GetEntriesAsync
(Phase 4, Tier 2 per-person accessor #2).

Pattern matches `cbdb_parity.avalonia_altnames`: extract C# SQL,
splice in raw ID columns for stable diff-keying, execute against
sqlite3, apply JoinDisplay post-processing matching the C# reader.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import find_sql_block

# Mirrors `PersonEntryItem` (the C# record). The Avalonia reader sets
# `Dynasty=null` literally — no SQL column drives it — so we mirror
# that here. `entry_code` is a stable diff-key helper (raw column),
# NOT in the C# record's user-visible payload.
_ENTRY_RECORD_FIELDS: tuple[str, ...] = (
    "sequence",            # 0 ed.c_sequence (IsDBNull → 0)
    "entry_method",        # JoinDisplay(ec.c_entry_desc_chn, ec.c_entry_desc)
    "exam_rank",           # ed.c_exam_rank
    "year",                # ed.c_year
    "nianhao",             # JoinDisplay(nh.c_nianhao_chn, nh.c_nianhao_pin)
    "nianhao_year",        # ed.c_entry_nh_year
    "dynasty",             # literal None
    "range",               # JoinDisplay(yr.c_range_chn, yr.c_range)
    "age",                 # ed.c_age
    "kinship",             # JoinDisplay(kc.c_kinrel_chn, kc.c_kinrel)
    "kin_name_chn",        # kin.c_name_chn
    "kin_name",            # kin.c_name
    "association",         # JoinDisplay(ac.c_assoc_desc_chn, ac.c_assoc_desc)
    "associate_name_chn",  # assoc.c_name_chn
    "associate_name",      # assoc.c_name
    "institution_name_chn",  # sinc.c_inst_name_hz
    "institution_name",      # sinc.c_inst_name_py
    "entry_address_chn",     # addr.c_name_chn
    "entry_address",         # addr.c_name
    "parental_status",     # JoinDisplay(psc.c_parental_status_desc_chn, psc.c_parental_status_desc)
    "source",              # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",               # ed.c_pages
    "notes",               # ed.c_notes
    "posting_notes",       # ed.c_posting_notes
)
_ENTRY_ID_FIELDS: tuple[str, ...] = ("entry_code",)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_entries_sql(cs_path: Path) -> str:
    # `c_entry_desc_chn` is unique to GetEntriesAsync (CountAsync's
    # entry-count block doesn't reference the lookup table).
    return find_sql_block(cs_path, "c_entry_desc_chn")


def entries_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    """Execute the Avalonia GetEntriesAsync SQL, return rows shaped
    like `PersonEntryItem` plus a `entry_code` ID column for diff
    keying."""
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_entries_sql(cs_path)
    augmented = template.replace(
        "ed.c_posting_notes\nFROM",
        "ed.c_posting_notes,\n    ed.c_entry_code\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "entries SQL extracted from C# no longer matches the "
            "expected shape (missing `ed.c_posting_notes\\nFROM` anchor "
            "for ID-column splice). Inspect SqlitePersonBrowserService."
            "cs for an upstream rewrite."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
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
    return rows


def entries_field_names() -> tuple[str, ...]:
    return _ENTRY_RECORD_FIELDS


def entries_id_field_names() -> tuple[str, ...]:
    return _ENTRY_ID_FIELDS


__all__ = [
    "entries_field_names",
    "entries_id_field_names",
    "entries_query",
]
