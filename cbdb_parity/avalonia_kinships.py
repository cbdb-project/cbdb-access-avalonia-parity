"""Python re-execution of Avalonia GetKinshipsAsync, non-expanded branch
(Phase 4, Tier 2 per-person accessor #9).

GetKinshipsAsync(expandNetwork=true) does iterative graph traversal
in C# that we do not replicate here — the pair test covers only the
direct (expandNetwork=false) branch.

The SQL is duplicated in C# (one occurrence in GetKinshipsAsync's
direct branch, one in LoadDirectKinshipEdgesAsync) — both blocks
are byte-identical, so we dedupe before extracting.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_query_sql import extract_sql_blocks


_KINSHIP_RECORD_FIELDS: tuple[str, ...] = (
    "kin_person_id",   # kd.c_kin_id (IsDBNull → 0)
    "kinship",         # JoinDisplay(kc.c_kinrel_chn, kc.c_kinrel)
    "kin_name_chn",    # kin.c_name_chn
    "kin_name",        # kin.c_name
    "up_step",         # kc.c_upstep
    "down_step",       # kc.c_dwnstep
    "marriage_step",   # kc.c_marstep
    "collateral_step", # kc.c_colstep
    "source",          # JoinDisplay(src.c_title_chn, src.c_title)
    "pages",           # kd.c_pages
    "notes",           # kd.c_notes
)
_KINSHIP_ID_FIELDS: tuple[str, ...] = ("kin_code",)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_kinships_sql(cs_path: Path) -> str:
    blocks = extract_sql_blocks(cs_path)
    matches = sorted({b for b in blocks if "KIN_DATA kd" in b})
    if len(matches) != 1:
        raise LookupError(
            f"expected exactly one unique kinship SQL block in {cs_path}; "
            f"found {len(matches)}"
        )
    return matches[0]


def kinships_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_kinships_sql(cs_path)
    augmented = template.replace(
        "kd.c_notes\nFROM",
        "kd.c_notes,\n    kd.c_kin_code\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "kinships SQL extracted from C# no longer matches the "
            "expected shape (missing `kd.c_notes\\nFROM` anchor)."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
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
    return rows


def kinships_field_names() -> tuple[str, ...]:
    return _KINSHIP_RECORD_FIELDS


def kinships_id_field_names() -> tuple[str, ...]:
    return _KINSHIP_ID_FIELDS


__all__ = [
    "kinships_field_names",
    "kinships_id_field_names",
    "kinships_query",
]
