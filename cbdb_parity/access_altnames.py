"""Access-side bridge for the Phase 4 / Tier 2 altnames query.

Unlike Phase 3c/3d/3e (which wrap `cbdb_replay/lookat*.py`), Tier 2
per-person accessors don't have a cbdb_replay analogue — the Avalonia
PersonBrowser surface is fundamentally per-person while cbdb_replay's
LookAt* forms are corpus-wide queries. Per `coverage/matrix.md` Tier 2,
the strategy is "direct SQL compare": we issue the equivalent SQL
against the .mdb via pyodbc and apply the same post-fetch JoinDisplay
that the Avalonia C# reader does, so the row dicts diff exactly.

The SQL string is literally the SAME shape the Avalonia path uses —
we just replace the `$personId` C# parameter with `?` for pyodbc
positional binding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display

# The Avalonia query, transcribed for Microsoft Access ODBC. Jet
# requires explicit parentheses around chained LEFT JOINs (the
# sqlite3 form Avalonia ships without the parens raises `Syntax
# error (missing operator)`). Functionally identical row shape;
# columns / ORDER BY / WHERE unchanged.
_ACCESS_SQL = """
SELECT
    a.c_sequence,
    a.c_alt_name_chn,
    a.c_alt_name,
    anc.c_name_type_desc_chn,
    anc.c_name_type_desc,
    src.c_title_chn,
    src.c_title,
    a.c_pages,
    a.c_notes,
    a.c_alt_name_type_code,
    a.c_source
FROM (ALTNAME_DATA a
      LEFT JOIN ALTNAME_CODES anc ON anc.c_name_type_code = a.c_alt_name_type_code)
     LEFT JOIN TEXT_CODES src ON src.c_textid = a.c_source
WHERE a.c_personid = ?
ORDER BY a.c_sequence, a.c_alt_name_type_code, a.c_alt_name_chn
""".strip()


def altnames_query_access(
    mdb_path: Path,
    person_id: int,
) -> list[dict[str, Any]]:
    """Run the equivalent altnames query against `mdb_path` via pyodbc.

    Returns rows in the same shape as
    `cbdb_parity.avalonia_altnames.altnames_query()` so a per-row diff
    on the shared field set compares apples to apples.
    """
    import pyodbc

    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"DBQ={mdb_path};"
    )
    rows: list[dict[str, Any]] = []
    with pyodbc.connect(conn_str) as conn:
        cur = conn.cursor()
        cur.execute(_ACCESS_SQL, person_id)
        for raw in cur.fetchall():
            (seq, alt_chn, alt, ntype_chn, ntype, src_chn, src, pages, notes,
             ntype_code, source_id) = raw
            rows.append({
                "sequence":       seq if seq is not None else 0,
                "alt_name_chn":   alt_chn,
                "alt_name":       alt,
                "name_type":      _join_display(ntype_chn, ntype),
                "source":         _join_display(src_chn, src),
                "pages":          pages,
                "notes":          notes,
                "name_type_code": ntype_code,
                "source_id":      source_id,
            })
        cur.close()
    return rows


__all__ = ["altnames_query_access"]
