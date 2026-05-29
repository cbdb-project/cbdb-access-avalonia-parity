"""Access-side bridge for Phase 4 / Tier 1 BIOG basic search.

Access SQL differences from the SQLite original:
- `LIMIT n OFFSET m` → `TOP (n+m)` then drop the first m rows in Python.
- `COALESCE(a, b)` → `IIf(a IS NULL, b, a)` (COALESCE works in modern
  Access ODBC but `IIf` is safer cross-version).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


_ACCESS_NO_KEYWORD_SQL_TOP = """
SELECT TOP {top}
    b.c_personid,
    b.c_name_chn,
    b.c_name,
    b.c_index_year,
    IIf(ac.c_name_chn IS NULL, ac.c_name, ac.c_name_chn) AS c_index_address
FROM BIOG_MAIN b
LEFT JOIN ADDR_CODES ac ON ac.c_addr_id = b.c_index_addr_id
ORDER BY b.c_personid
""".strip()


def biog_basic_query_access(
    mdb_path: Path,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    import pyodbc

    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    top = limit + offset
    # Access has no parameter for TOP, so we string-format it (safe:
    # already clamped to an int range).
    sql = _ACCESS_NO_KEYWORD_SQL_TOP.format(top=top)

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    rows: list[dict[str, Any]] = []
    with pyodbc.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        for (pid, name_chn, name, iy, idx_addr) in cur.fetchall():
            rows.append({
                "person_id":     pid,
                "name_chn":      name_chn,
                "name_rm":       name,
                "index_year":    iy,
                "index_address": idx_addr,
            })
        cur.close()
    # Drop the first `offset` rows to emulate SQL OFFSET.
    return rows[offset:]


__all__ = ["biog_basic_query_access"]
