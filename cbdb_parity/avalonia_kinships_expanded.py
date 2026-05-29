"""Phase 5c-final batch 2 — thin wrapper around GetExpandedKinshipsAsync
(expandNetwork=true BFS) via the ParityHost.

Phase 5d (`tests/test_phase5d_kinships_byte_for_byte.py`)
previously cross-checked a hand-ported BFS state machine in this
module against the real C# implementation and showed byte-for-byte
equivalence on the canonical fixture (Su Shi / 1762). With the
host now the authoritative source per WORK_PLAN.md §5c, the port
has been retired; this module simply forwards to the host.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cbdb_parity._person_accessor_host import resolve_avalonia_repo
from cbdb_parity.parity_host import invoke_parity_host


_EXPANDED_KINSHIP_FIELDS: tuple[str, ...] = (
    "kin_person_id", "kinship", "kin_name_chn", "kin_name",
    "is_derived",
    "up_step", "down_step", "marriage_step", "collateral_step",
    "source", "pages", "notes",
)


def expanded_kinships_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path | None = None,
    avalonia_repo: Path | None = None,
    timeout_seconds: float = 300.0,
) -> list[dict[str, Any]]:
    """Run GetKinshipsAsync(person_id, expandNetwork=true) via the
    ParityHost.

    Well-connected fixtures (Su Shi / 1762) take ~2-3 minutes on
    the canonical dataset; 300s default leaves headroom.
    """
    repo = resolve_avalonia_repo(
        avalonia_repo=avalonia_repo,
        avalonia_data_dir=avalonia_data_dir,
    )
    response = invoke_parity_host(
        "kinships", sqlite_path,
        {"person_id": person_id, "expand_network": True},
        avalonia_repo=repo,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(response, list):
        raise TypeError(
            f"expected list from kinships dispatch, got {type(response).__name__}"
        )
    return response


# Legacy alias — Phase 5d's byte-for-byte test imported this name.
expanded_kinships_via_host = expanded_kinships_query


def expanded_kinships_field_names() -> tuple[str, ...]:
    return _EXPANDED_KINSHIP_FIELDS


__all__ = [
    "expanded_kinships_field_names",
    "expanded_kinships_query",
    "expanded_kinships_via_host",
]
