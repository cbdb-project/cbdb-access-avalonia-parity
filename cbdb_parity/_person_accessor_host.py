"""Shared host-call + ID-splice helper for Phase 5c-final.

The Phase 4 pair tests use spliced raw-ID columns
(`c_event_code`, `c_assoc_code`, …) as diff keys, but the upstream
record DTOs (`PersonEventItem`, `PersonAssociationItem`, …)
deliberately don't expose them on the wire. Each Tier-2 mirror
therefore needs a thin sqlite-side query just to fetch the IDs in
the same row order as upstream and splice them back into the host
response.

This helper factors out the boilerplate so each
`cbdb_parity.avalonia_<accessor>.py` becomes a 20-line module:

  - import this helper,
  - declare its splice SQL (table + ORDER BY *identical* to the
    upstream Get<Accessor>Async query, both visible to humans for
    review),
  - declare the response field name(s) to attach the IDs under.

All splice SQL strings live in the accessor module they belong to,
not here, so a future change to an upstream ORDER BY is reviewed
in the file that already covers that surface.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from cbdb_parity.parity_host import invoke_person_accessor_via_host


def resolve_avalonia_repo(
    *, avalonia_repo: Path | None, avalonia_data_dir: Path | None,
) -> Path:
    """Phase 4 pair tests pass `avalonia_data_dir = repo / Cbdb.App.Data`;
    Phase 5 callers pass `avalonia_repo` directly. Either is fine —
    the host needs the repo root, not the Data dir.
    """
    if avalonia_repo is not None:
        return avalonia_repo
    if avalonia_data_dir is not None:
        return avalonia_data_dir.parent
    raise TypeError(
        "either `avalonia_repo` or `avalonia_data_dir` is required"
    )


def fetch_via_host_with_id_splice(
    service: str,
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_repo: Path,
    splice_sql: str | None = None,
    splice_field_names: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Invoke the ParityHost for `service` and (optionally) splice
    additional ID columns back onto each row.

    Parameters
    ----------
    splice_sql: a SELECT statement whose row count and order MUST
        match the upstream Get<Accessor>Async exactly. Must take a
        single `:pid` parameter for c_personid. May be None when
        the accessor has no spliced IDs (e.g. possessions).
    splice_field_names: dict keys to attach the SELECT columns
        under. Length must equal the number of columns the SELECT
        returns (validated at runtime).

    Raises
    ------
    RuntimeError if the splice row count differs from the host row
    count — signals an ORDER BY drift between this module's splice
    SQL and upstream.
    """
    rows = invoke_person_accessor_via_host(
        service, sqlite_path, person_id, avalonia_repo=avalonia_repo,
    )
    if splice_sql is None or not splice_field_names:
        return rows

    with sqlite3.connect(sqlite_path) as conn:
        splice_rows = conn.execute(
            splice_sql, {"pid": person_id},
        ).fetchall()

    if len(splice_rows) != len(rows):
        raise RuntimeError(
            f"{service}: ID splice row-count mismatch — "
            f"host={len(rows)} sqlite={len(splice_rows)}. The splice "
            f"SQL must filter and order identically to upstream "
            f"Get{service.capitalize()}Async."
        )
    for splice in splice_rows:
        if len(splice) != len(splice_field_names):
            raise RuntimeError(
                f"{service}: splice SELECT returned {len(splice)} "
                f"columns but {len(splice_field_names)} field names "
                f"were declared."
            )
    for row, splice in zip(rows, splice_rows, strict=True):
        for name, value in zip(splice_field_names, splice, strict=True):
            row[name] = value
    return rows


__all__ = [
    "fetch_via_host_with_id_splice",
    "resolve_avalonia_repo",
]
