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
    splice_verify: tuple[tuple[str, str], ...] = (),
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
        returns (validated at runtime). Splice columns are
        appended in this order at the end of the SELECT — see
        `splice_verify` for the prefix used to align rows.
    splice_verify: optional tuple of `(host_field_name,
        splice_col_label)` pairs. When set, the splice SELECT MUST
        return these columns FIRST (in this order), and each
        spliced row's leading values must equal the corresponding
        host row's host_field_name. Used by accessors whose
        upstream ORDER BY has a known tied-column risk (e.g.
        altnames: two rows can share (sequence, name_type,
        name_chn) and the positional zip would silently misalign).
        Codex round on Phase 5c-final flagged altnames as the
        concrete case; this is the general guard.

    Raises
    ------
    RuntimeError if the splice row count differs from the host row
    count (ORDER BY drift), or if `splice_verify` is set and any
    splice row's leading values don't match the corresponding host
    row.
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

    verify_count = len(splice_verify)
    expected_splice_width = verify_count + len(splice_field_names)
    for splice in splice_rows:
        if len(splice) != expected_splice_width:
            raise RuntimeError(
                f"{service}: splice SELECT returned {len(splice)} "
                f"columns but {expected_splice_width} were expected "
                f"({verify_count} verify + {len(splice_field_names)} attach)."
            )
    for i, (row, splice) in enumerate(zip(rows, splice_rows, strict=True)):
        for j, (host_field, _splice_label) in enumerate(splice_verify):
            host_value = row.get(host_field)
            if host_value != splice[j]:
                raise RuntimeError(
                    f"{service}: splice row {i} drifted from host row — "
                    f"verify field {host_field!r}: host={host_value!r} "
                    f"sqlite={splice[j]!r}. The upstream ORDER BY has "
                    f"tied columns; widen splice_verify or update the "
                    f"splice SQL."
                )
        for name, value in zip(
            splice_field_names, splice[verify_count:], strict=True,
        ):
            row[name] = value
    return rows


__all__ = [
    "fetch_via_host_with_id_splice",
    "resolve_avalonia_repo",
]
