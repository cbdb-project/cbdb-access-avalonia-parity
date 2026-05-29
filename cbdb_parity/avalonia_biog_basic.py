"""Python re-execution of Avalonia SqlitePersonBrowserService.SearchAsync —
the no-keyword branch (Phase 4, Tier 1 shape-mismatched pair #1).

The matrix.md entry calls this 🆕 partially-paired: Access has no
test-driven form, so we mirror the SearchAsync SQL directly on the
mdb side. We cover only the no-keyword branch (`keyword=None`) for
the initial pair — the personId-keyword and text-keyword branches
are queued for follow-up.

`COALESCE(ac.c_name_chn, ac.c_name)` returns whichever is non-null —
identical behaviour on both engines (SQLite COALESCE and Jet's
NZ/IIf-or-COALESCE produce the same output for two-arg form).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


_BIOG_BASIC_FIELDS: tuple[str, ...] = (
    "person_id",     # b.c_personid
    "name_chn",      # b.c_name_chn
    "name_rm",       # b.c_name — upstream PersonListItem.NameRm
    "index_year",    # b.c_index_year
    "index_address", # COALESCE(ac.c_name_chn, ac.c_name)
)


_SQLITE_NO_KEYWORD_SQL = """
SELECT
    b.c_personid,
    b.c_name_chn,
    b.c_name,
    b.c_index_year,
    COALESCE(ac.c_name_chn, ac.c_name) AS c_index_address
FROM BIOG_MAIN b
LEFT JOIN ADDR_CODES ac ON ac.c_addr_id = b.c_index_addr_id
ORDER BY b.c_personid
LIMIT :limit OFFSET :offset
""".strip()


def biog_basic_query(
    sqlite_path: Path,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.execute(_SQLITE_NO_KEYWORD_SQL, {"limit": limit, "offset": offset})
        for (pid, name_chn, name, iy, idx_addr) in cursor.fetchall():
            rows.append({
                "person_id":     pid,
                "name_chn":      name_chn,
                "name_rm":       name,
                "index_year":    iy,
                "index_address": idx_addr,
            })
    return rows


def biog_basic_field_names() -> tuple[str, ...]:
    return _BIOG_BASIC_FIELDS


__all__ = [
    "biog_basic_field_names",
    "biog_basic_query",
]
