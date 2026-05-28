"""Python re-execution of Avalonia GetSourcesAsync
(Phase 4, Tier 2 per-person accessor #11).

7-col SELECT + 1 LEFT JOIN. Bools: c_main_source, c_self_bio.
Diff key (textid, pages) — splice bsd.c_textid.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none
from cbdb_parity.avalonia_query_sql import find_sql_block


_SOURCE_RECORD_FIELDS: tuple[str, ...] = (
    "title_chn",   # tc.c_title_chn
    "title",       # tc.c_title
    "pages",       # bsd.c_pages
    "notes",       # bsd.c_notes
    "main_source", # bool: bsd.c_main_source == 1
    "self_bio",    # bool: bsd.c_self_bio == 1
    "hyperlink",   # CASE ... END (computed)
)
_SOURCE_ID_FIELDS: tuple[str, ...] = ("text_id",)


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_get_sources_sql(cs_path: Path) -> str:
    return find_sql_block(cs_path, "BIOG_SOURCE_DATA")


def sources_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    template = _load_get_sources_sql(cs_path)
    # Splice `bsd.c_textid` for diff-keying. Anchor is the CASE...END
    # block label `AS c_hyperlink`.
    augmented = template.replace(
        "AS c_hyperlink\nFROM",
        "AS c_hyperlink,\n    bsd.c_textid\nFROM",
    )
    if augmented == template:
        raise RuntimeError(
            "sources SQL extracted from C# no longer matches the "
            "expected shape (missing `AS c_hyperlink\\nFROM` anchor)."
        )
    sql = _csharp_params_to_sqlite(augmented)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(sql, {"personId": person_id})
        for r in cursor.fetchall():
            (title_chn, title, pages, notes, main, sb, hyperlink, text_id) = r
            rows.append({
                "title_chn":   title_chn,
                "title":       title,
                "pages":       pages,
                "notes":       notes,
                "main_source": _to_bool_or_none(main),
                "self_bio":    _to_bool_or_none(sb),
                "hyperlink":   hyperlink,
                "text_id":     text_id,
            })
    return rows


def sources_field_names() -> tuple[str, ...]:
    return _SOURCE_RECORD_FIELDS


def sources_id_field_names() -> tuple[str, ...]:
    return _SOURCE_ID_FIELDS


__all__ = [
    "sources_field_names",
    "sources_id_field_names",
    "sources_query",
]
