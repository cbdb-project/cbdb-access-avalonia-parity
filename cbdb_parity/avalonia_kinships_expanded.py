"""Python re-execution of Avalonia GetExpandedKinshipsAsync
(SqlitePersonBrowserService.cs:1323).

The C# function is a deterministic state machine:

1. Loads direct kinship edges of the seed person.
2. Promotes each edge to a `KinshipTraversalState` keyed by KinPersonId,
   keeping the "best" one if multiple paths reach the same person.
3. Expands the frontier breadth-first up to `maxLoop=10` hops, applying
   per-direction caps (`maxUp=2, maxDown=2, maxMarriage=1,
   maxCollateral=1`). Each extension calls `ReduceKinship` which
   collapses 2-character suffixes (e.g. "BB" → "B" with collateral−1)
   via a fixed rule table.
4. Returns survivors sorted by:
     (IsDerived, weighted_step_score, Distance, KinPersonId)

This module ports steps 2–4 verbatim. Step 1 reuses the SQL extracted
by `cbdb_parity.avalonia_kinships._load_get_kinships_sql`.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cbdb_parity.avalonia_altnames import _join_display
from cbdb_parity.avalonia_kinships import _load_get_kinships_sql


# Per SqlitePersonBrowserService.cs:1328-1332
_MAX_LOOP = 10
_MAX_UP = 2
_MAX_DOWN = 2
_MAX_MARRIAGE = 1
_MAX_COLLATERAL = 1


# SqlitePersonBrowserService.cs:9 — KinshipReductionRules.
# Keys are 2-char suffixes (case-insensitive on the C# side).
# Values: (replacement, up_change, down_change, collateral_change, marriage_change)
_KINSHIP_REDUCTION_RULES: dict[str, tuple[str, int, int, int, int]] = {
    "BB": ("B", 0, 0, -1, 0),
    "BZ": ("Z", 0, 0, -1, 0),
    "DB": ("S", 0, 0, -1, 0),
    "DZ": ("D", 0, 0, -1, 0),
    "SB": ("S", 0, 0, -1, 0),
    "SZ": ("D", 0, 0, -1, 0),
    "ZB": ("B", 0, 0, -1, 0),
    "ZZ": ("Z", 0, 0, -1, 0),
}


_EXPANDED_KINSHIP_FIELDS: tuple[str, ...] = (
    "kin_person_id",
    "kinship",
    "kin_name_chn",
    "kin_name",
    "is_derived",
    "up_step",
    "down_step",
    "marriage_step",
    "collateral_step",
    "source",
    "pages",
    "notes",
)


@dataclass(frozen=True)
class _KinshipEdge:
    """Mirror of the C# `KinshipEdge` record."""

    kin_person_id: int
    raw_kinship: str | None
    kinship: str | None
    kin_name_chn: str | None
    kin_name: str | None
    up_step: int | None
    down_step: int | None
    marriage_step: int | None
    collateral_step: int | None
    source: str | None
    pages: str | None
    notes: str | None


@dataclass
class _TraversalState:
    """Mirror of the C# `KinshipTraversalState` record (mutable for
    convenience; we re-create rather than mutate in Extend)."""

    kin_person_id: int
    raw_kinship: str | None
    kinship: str | None
    kin_name_chn: str | None
    kin_name: str | None
    is_derived: bool
    up_step: int | None
    down_step: int | None
    marriage_step: int | None
    collateral_step: int | None
    source: str | None
    pages: str | None
    path_description: str | None
    supplemental_notes: str | None
    notes: str | None
    distance: int
    visited_person_ids: frozenset[int] = field(default_factory=frozenset)


def _reduce_kinship(
    raw_kinship: str | None,
    up_step: int,
    down_step: int,
    marriage_step: int,
    collateral_step: int,
) -> tuple[str | None, int, int, int, int]:
    """Port of `ReduceKinship` (SqlitePersonBrowserService.cs:1669)."""
    if not raw_kinship or not raw_kinship.strip():
        return raw_kinship, up_step, down_step, marriage_step, collateral_step
    current = raw_kinship
    changed = True
    while changed and len(current) >= 2:
        changed = False
        suffix = current[-2:]
        # KinshipReductionRules is OrdinalIgnoreCase on the C# side —
        # match by uppercase. The keys are already uppercase.
        rule = _KINSHIP_REDUCTION_RULES.get(suffix.upper())
        if rule is None:
            continue
        replacement, up_change, down_change, collateral_change, marriage_change = rule
        current = current[:-2] + replacement
        up_step += up_change
        down_step += down_change
        collateral_step += collateral_change
        marriage_step += marriage_change
        changed = True
    return current, up_step, down_step, marriage_step, collateral_step


def _resolve_kinship_display(
    raw_kinship: str | None,
    kinship_display_lookup: dict[str, str],
) -> str | None:
    """Port of `ResolveKinshipDisplay` (SqlitePersonBrowserService.cs:1694)."""
    if not raw_kinship or not raw_kinship.strip():
        return raw_kinship
    # The lookup is case-insensitive in C#.
    display = kinship_display_lookup.get(raw_kinship.casefold())
    if display is not None:
        return display
    return raw_kinship if len(raw_kinship) == 1 else None


def _build_root_path(
    root_label: str | None, kin_label: str | None, kinship: str | None
) -> str | None:
    if not root_label or not root_label.strip():
        path = kin_label
    elif not kin_label or not kin_label.strip():
        path = root_label
    else:
        path = f"{root_label} > {kin_label}"
    if not path or not path.strip() or not kinship or not kinship.strip():
        return path
    return f"{path} ({kinship})"


def _append_path(
    prior_path: str | None, next_label: str | None, kinship: str | None
) -> str | None:
    if not next_label or not next_label.strip():
        segment = None
    elif not kinship or not kinship.strip():
        segment = next_label
    else:
        segment = f"{next_label} ({kinship})"
    if not prior_path or not prior_path.strip():
        return segment
    if not segment or not segment.strip():
        return prior_path
    return f"{prior_path} > {segment}"


def _append_supplemental_notes(
    prior_notes: str | None, next_notes: str | None
) -> str | None:
    if not prior_notes or not prior_notes.strip():
        return next_notes
    if not next_notes or not next_notes.strip():
        return prior_notes
    # C# uses Environment.NewLine — on Avalonia's typical Windows host
    # that's "\r\n". The replay scan compares notes as strings; we
    # emit "\r\n" to match.
    return f"{prior_notes}\r\n{next_notes}"


def _build_notes(
    path_description: str | None,
    supplemental_notes: str | None,
    original_raw_kinship: str | None,
    reduced_raw_kinship: str | None,
    reduced_kinship: str | None,
) -> str | None:
    combined = path_description
    if (
        original_raw_kinship and original_raw_kinship.strip()
        and reduced_kinship and reduced_kinship.strip()
        and (
            (original_raw_kinship or "").casefold() != (reduced_raw_kinship or "").casefold()
            or (original_raw_kinship or "").casefold() != (reduced_kinship or "").casefold()
        )
    ):
        addition = f"{original_raw_kinship} => {reduced_kinship}"
        combined = addition if not combined or not combined.strip() else f"{combined}\r\n{addition}"
    if not supplemental_notes or not supplemental_notes.strip():
        return combined
    if not combined or not combined.strip():
        return supplemental_notes
    return f"{combined}\r\n{supplemental_notes}"


def _create_root(edge: _KinshipEdge, root_name: tuple[str | None, str | None]) -> _TraversalState:
    root_label = _join_display(root_name[0], root_name[1])
    kin_label = _join_display(edge.kin_name_chn, edge.kin_name)
    path = _build_root_path(root_label, kin_label, edge.kinship)
    notes = _build_notes(path, edge.notes, None, edge.raw_kinship, edge.kinship)
    return _TraversalState(
        kin_person_id=edge.kin_person_id,
        raw_kinship=edge.raw_kinship,
        kinship=edge.kinship,
        kin_name_chn=edge.kin_name_chn,
        kin_name=edge.kin_name,
        is_derived=False,
        up_step=edge.up_step,
        down_step=edge.down_step,
        marriage_step=edge.marriage_step,
        collateral_step=edge.collateral_step,
        source=edge.source,
        pages=edge.pages,
        path_description=path,
        supplemental_notes=edge.notes,
        notes=notes,
        distance=1,
        visited_person_ids=frozenset({edge.kin_person_id}),
    )


def _extend(
    state: _TraversalState,
    edge: _KinshipEdge,
    kinship_display_lookup: dict[str, str],
) -> _TraversalState:
    combined_raw = (state.raw_kinship or "") + (edge.raw_kinship or "")
    new_raw, new_up, new_down, new_marriage, new_collateral = _reduce_kinship(
        combined_raw,
        (state.up_step or 0) + (edge.up_step or 0),
        (state.down_step or 0) + (edge.down_step or 0),
        (state.marriage_step or 0) + (edge.marriage_step or 0),
        (state.collateral_step or 0) + (edge.collateral_step or 0),
    )
    kinship = _resolve_kinship_display(new_raw, kinship_display_lookup)
    if not kinship or not kinship.strip():
        # Fallback path in the C# code (SqlitePersonBrowserService.cs:1596-1602).
        if not state.kinship or not state.kinship.strip():
            kinship = edge.kinship
        elif not edge.kinship or not edge.kinship.strip():
            kinship = state.kinship
        else:
            kinship = f"{state.kinship} > {edge.kinship}"
    next_label = _join_display(edge.kin_name_chn, edge.kin_name)
    path = _append_path(state.path_description, next_label, edge.kinship)
    supplemental = _append_supplemental_notes(state.supplemental_notes, edge.notes)
    notes = _build_notes(path, supplemental, combined_raw, new_raw, kinship)
    visited = state.visited_person_ids | {edge.kin_person_id}
    return _TraversalState(
        kin_person_id=edge.kin_person_id,
        raw_kinship=new_raw,
        kinship=kinship,
        kin_name_chn=edge.kin_name_chn,
        kin_name=edge.kin_name,
        is_derived=True,
        up_step=new_up,
        down_step=new_down,
        marriage_step=new_marriage,
        collateral_step=new_collateral,
        source=edge.source,
        pages=edge.pages,
        path_description=path,
        supplemental_notes=supplemental,
        notes=notes,
        distance=state.distance + 1,
        visited_person_ids=visited,
    )


def _metric_score(state: _TraversalState) -> int:
    """Mirror of CompareMetrics's weighted score."""
    return (
        (state.up_step or 0) * 1000
        + (state.down_step or 0) * 100
        + (state.collateral_step or 0) * 10
        + (state.marriage_step or 0)
    )


def _is_better(candidate: _TraversalState, existing: _TraversalState) -> bool:
    """Port of `IsBetterThan` (SqlitePersonBrowserService.cs:1633)."""
    metric_compare = _metric_score(candidate) - _metric_score(existing)
    if metric_compare != 0:
        return metric_compare < 0
    if candidate.distance != existing.distance:
        return candidate.distance < existing.distance
    cand_len = len(candidate.notes) if candidate.notes is not None else 2**31 - 1
    ext_len = len(existing.notes) if existing.notes is not None else 2**31 - 1
    if cand_len != ext_len:
        return cand_len < ext_len
    # OrdinalIgnoreCase string compare on Kinship.
    cand_kin = (candidate.kinship or "").casefold()
    ext_kin = (existing.kinship or "").casefold()
    return cand_kin < ext_kin


def _try_add_best(
    bucket: dict[int, _TraversalState], candidate: _TraversalState
) -> None:
    existing = bucket.get(candidate.kin_person_id)
    if existing is None or _is_better(candidate, existing):
        bucket[candidate.kin_person_id] = candidate


def _within_limits(state: _TraversalState) -> bool:
    return (
        (state.up_step or 0) <= _MAX_UP
        and (state.down_step or 0) <= _MAX_DOWN
        and (state.marriage_step or 0) <= _MAX_MARRIAGE
        and (state.collateral_step or 0) <= _MAX_COLLATERAL
    )


def _csharp_params_to_sqlite(sql: str) -> str:
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r":\1", sql)


def _load_person_name(conn: sqlite3.Connection, person_id: int) -> tuple[str | None, str | None]:
    cur = conn.execute(
        "SELECT c_name_chn, c_name FROM BIOG_MAIN WHERE c_personid = :pid LIMIT 1",
        {"pid": person_id},
    )
    row = cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


def _load_direct_edges(
    conn: sqlite3.Connection, person_id: int, sql: str
) -> list[_KinshipEdge]:
    edges: list[_KinshipEdge] = []
    cur = conn.execute(sql, {"personId": person_id})
    for r in cur.fetchall():
        (kin_pid, _kin_simplified, kin_chn, kin_en,
         kin_name_chn, kin_name, up, down, mar, col,
         src_chn, src_en, pages, notes) = r
        edges.append(_KinshipEdge(
            kin_person_id=kin_pid if kin_pid is not None else 0,
            raw_kinship=_kin_simplified,
            kinship=_join_display(kin_chn, kin_en),
            kin_name_chn=kin_name_chn,
            kin_name=kin_name,
            up_step=up,
            down_step=down,
            marriage_step=mar,
            collateral_step=col,
            source=_join_display(src_chn, src_en),
            pages=pages,
            notes=notes,
        ))
    return edges


def _load_kinship_display_lookup(conn: sqlite3.Connection) -> dict[str, str]:
    """Port of LoadKinshipDisplayLookupAsync (line 1391). The lookup is
    case-insensitive in C#; we casefold the key on insert and lookup."""
    lookup: dict[str, str] = {}
    cur = conn.execute(
        "SELECT c_kinrel_simplified, c_kinrel_chn, c_kinrel "
        "FROM KINSHIP_CODES "
        "WHERE c_kinrel_simplified IS NOT NULL "
        "AND TRIM(c_kinrel_simplified) <> '' "
        "ORDER BY c_kincode"
    )
    for simplified, chn, en in cur.fetchall():
        if not simplified or not str(simplified).strip():
            continue
        key = str(simplified).casefold()
        if key in lookup:
            continue
        lookup[key] = _join_display(chn, en) or simplified
    return lookup


def expanded_kinships_query(
    sqlite_path: Path,
    person_id: int,
    *,
    avalonia_data_dir: Path,
) -> list[dict[str, Any]]:
    """Run the GetExpandedKinshipsAsync state machine and return the
    final ordered list of derived kinships, shaped like
    `PersonKinshipItem`."""
    cs_path = avalonia_data_dir / "SqlitePersonBrowserService.cs"
    edge_sql_template = _load_get_kinships_sql(cs_path)
    edge_sql = _csharp_params_to_sqlite(edge_sql_template)

    edge_cache: dict[int, list[_KinshipEdge]] = {}

    with sqlite3.connect(sqlite_path) as conn:
        kinship_display_lookup = _load_kinship_display_lookup(conn)
        root_name = _load_person_name(conn, person_id)

        if person_id not in edge_cache:
            edge_cache[person_id] = _load_direct_edges(conn, person_id, edge_sql)
        direct_edges = edge_cache[person_id]

        best_by_kin_id: dict[int, _TraversalState] = {}
        frontier: dict[int, _TraversalState] = {}

        for edge in direct_edges:
            if edge.kin_person_id == person_id:
                continue
            state = _create_root(edge, root_name)
            _try_add_best(best_by_kin_id, state)
            if _within_limits(state):
                _try_add_best(frontier, state)

        depth = 1
        while depth < _MAX_LOOP and frontier:
            next_frontier: dict[int, _TraversalState] = {}
            for current in frontier.values():
                cur_pid = current.kin_person_id
                if cur_pid not in edge_cache:
                    edge_cache[cur_pid] = _load_direct_edges(conn, cur_pid, edge_sql)
                for edge in edge_cache[cur_pid]:
                    if edge.kin_person_id == person_id:
                        continue
                    if edge.kin_person_id in current.visited_person_ids:
                        continue
                    candidate = _extend(current, edge, kinship_display_lookup)
                    if not _within_limits(candidate):
                        continue
                    _try_add_best(best_by_kin_id, candidate)
                    _try_add_best(next_frontier, candidate)
            frontier = next_frontier
            depth += 1

    # Final OrderBy/ThenBy chain (line 1380-1387):
    #   IsDerived ASC, weighted_score ASC, Distance ASC, KinPersonId ASC
    survivors = list(best_by_kin_id.values())
    survivors.sort(
        key=lambda s: (
            1 if s.is_derived else 0,
            _metric_score(s),
            s.distance,
            s.kin_person_id,
        )
    )
    return [{
        "kin_person_id":   s.kin_person_id,
        "kinship":         s.kinship,
        "kin_name_chn":    s.kin_name_chn,
        "kin_name":        s.kin_name,
        "is_derived":      s.is_derived,
        "up_step":         s.up_step,
        "down_step":       s.down_step,
        "marriage_step":   s.marriage_step,
        "collateral_step": s.collateral_step,
        "source":          s.source,
        "pages":           s.pages,
        "notes":           s.notes,
    } for s in survivors]


def expanded_kinships_field_names() -> tuple[str, ...]:
    return _EXPANDED_KINSHIP_FIELDS


__all__ = [
    "expanded_kinships_field_names",
    "expanded_kinships_query",
]
