"""Access-side bridge for Phase 4 / Tier 2 sources accessor.

NB: Access SQL uses `IIf(IsNull, NULL, ...)` instead of the SQLite
`CASE WHEN ... THEN ... END` and concatenation operator `&` instead
of `||`. Otherwise mirrors the Avalonia SQL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_addresses import _to_bool_or_none


_ACCESS_SQL = """
SELECT
    tc.c_title_chn,
    tc.c_title,
    bsd.c_pages,
    bsd.c_notes,
    bsd.c_main_source,
    bsd.c_self_bio,
    IIf(tc.c_url_api IS NULL AND tc.c_url_api_coda IS NULL,
        NULL,
        IIf(tc.c_url_api IS NULL, '', tc.c_url_api)
        & IIf(bsd.c_pages IS NULL, '', bsd.c_pages)
        & IIf(tc.c_url_api_coda IS NULL, '', tc.c_url_api_coda)
    ) AS c_hyperlink,
    bsd.c_textid
FROM BIOG_SOURCE_DATA bsd
LEFT JOIN TEXT_CODES tc ON tc.c_textid = bsd.c_textid
WHERE bsd.c_personid = ?
ORDER BY bsd.c_textid, bsd.c_pages
""".strip()


def sources_query_access(
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
        cur.close()
    return rows


__all__ = ["sources_query_access"]
