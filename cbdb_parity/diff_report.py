"""Per-query diff + report writer (Phase 3b).

Normalises two row sets (Avalonia and Access) to a canonical sort order
and computes the row-level diff. Writes the report files documented in
WORK_PLAN §6:

    reports/<query_id>/
        access.json     (gitignored — bulky raw rows)
        avalonia.json   (gitignored — bulky raw rows)
        diff.json       (committed — the canonical diff record)
        summary.md      (committed — narrative)

A `hypothesis.md` slot is created empty for the root-cause analyst (per
WORK_PLAN §7); the file isn't overwritten on subsequent runs so manual
notes stick.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DiffStats:
    rows_avalonia: int = 0
    rows_access: int = 0
    rows_matching: int = 0
    rows_only_in_avalonia: int = 0
    rows_only_in_access: int = 0
    rows_value_mismatch: int = 0

    @property
    def matches(self) -> bool:
        return (
            self.rows_only_in_avalonia == 0
            and self.rows_only_in_access == 0
            and self.rows_value_mismatch == 0
        )


@dataclass(slots=True)
class DiffResult:
    stats: DiffStats = field(default_factory=DiffStats)
    only_in_avalonia: list[dict[str, Any]] = field(default_factory=list)
    only_in_access: list[dict[str, Any]] = field(default_factory=list)
    # Each value mismatch records (key, avalonia_row, access_row, differing_fields).
    value_mismatches: list[dict[str, Any]] = field(default_factory=list)


def _row_key(row: Mapping[str, Any], key_fields: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(row.get(f) for f in key_fields)


def diff_rows(
    avalonia_rows: Iterable[Mapping[str, Any]],
    access_rows: Iterable[Mapping[str, Any]],
    key_fields: tuple[str, ...],
    *,
    compare_fields: tuple[str, ...] | None = None,
) -> DiffResult:
    """Diff two row sets by `key_fields` (which together uniquely
    identify a row), reporting:
      - rows present only in one side
      - rows present in both but with differing values in `compare_fields`
        (defaults to ALL fields excluding `key_fields`)

    Each row is shape-tolerant — extra/missing fields in one side simply
    appear as `None` on the other side's view. Phase 3 starter pairs
    use `key_fields = ("person_id", "sequence")` for entry-style
    record-level rows.
    """
    av_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in avalonia_rows:
        av_by_key[_row_key(row, key_fields)] = dict(row)

    ac_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in access_rows:
        ac_by_key[_row_key(row, key_fields)] = dict(row)

    result = DiffResult()
    result.stats.rows_avalonia = len(av_by_key)
    result.stats.rows_access = len(ac_by_key)

    only_av = set(av_by_key) - set(ac_by_key)
    only_ac = set(ac_by_key) - set(av_by_key)
    common = set(av_by_key) & set(ac_by_key)

    result.only_in_avalonia = [av_by_key[k] for k in sorted(only_av, key=lambda x: tuple(str(p) for p in x))]
    result.only_in_access = [ac_by_key[k] for k in sorted(only_ac, key=lambda x: tuple(str(p) for p in x))]
    result.stats.rows_only_in_avalonia = len(only_av)
    result.stats.rows_only_in_access = len(only_ac)

    for k in sorted(common, key=lambda x: tuple(str(p) for p in x)):
        av_row = av_by_key[k]
        ac_row = ac_by_key[k]
        fields_to_check = (
            compare_fields
            if compare_fields is not None
            else tuple(f for f in av_row.keys() if f not in key_fields)
        )
        diffs: dict[str, dict[str, Any]] = {}
        for f in fields_to_check:
            av_v = av_row.get(f)
            ac_v = ac_row.get(f)
            if av_v != ac_v:
                diffs[f] = {"avalonia": av_v, "access": ac_v}
        if diffs:
            result.value_mismatches.append({
                "key": list(k),
                "avalonia": av_row,
                "access": ac_row,
                "differing_fields": diffs,
            })
            result.stats.rows_value_mismatch += 1
        else:
            result.stats.rows_matching += 1
    return result


def write_report(
    reports_dir: Path,
    query_id: str,
    *,
    request: Mapping[str, Any],
    avalonia_rows: list[Mapping[str, Any]],
    access_rows: list[Mapping[str, Any]],
    diff: DiffResult,
    datadump_sha: str | None = None,
) -> Path:
    """Write the per-query report tree under `reports_dir / query_id /`.

    Files written:
      - access.json + avalonia.json (full raw rows; gitignored)
      - diff.json (canonical diff; committed)
      - summary.md (narrative; committed)
      - hypothesis.md (created empty if missing; preserved on re-runs)

    Returns the query's report directory.
    """
    out_dir = reports_dir / query_id
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "avalonia.json").write_text(
        json.dumps({"rows": list(avalonia_rows)}, indent=2, default=_json_default),
        encoding="utf-8",
    )
    (out_dir / "access.json").write_text(
        json.dumps({"rows": list(access_rows)}, indent=2, default=_json_default),
        encoding="utf-8",
    )

    diff_payload = {
        "query_id": query_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "datadump_sha": datadump_sha,
        "request": dict(request),
        "stats": {
            "rows_avalonia": diff.stats.rows_avalonia,
            "rows_access": diff.stats.rows_access,
            "rows_matching": diff.stats.rows_matching,
            "rows_only_in_avalonia": diff.stats.rows_only_in_avalonia,
            "rows_only_in_access": diff.stats.rows_only_in_access,
            "rows_value_mismatch": diff.stats.rows_value_mismatch,
            "matches": diff.stats.matches,
        },
        "only_in_avalonia": diff.only_in_avalonia,
        "only_in_access": diff.only_in_access,
        "value_mismatches": diff.value_mismatches,
    }
    (out_dir / "diff.json").write_text(
        json.dumps(diff_payload, indent=2, default=_json_default, sort_keys=True),
        encoding="utf-8",
    )

    verdict = "PASS" if diff.stats.matches else "FAIL"
    summary = f"""# Query `{query_id}` parity report

**Verdict**: {verdict}
**Generated**: {diff_payload["generated_at"]}
**Datadump SHA**: `{datadump_sha or '(unset)'}`

## Stats
- Rows Avalonia: {diff.stats.rows_avalonia}
- Rows Access: {diff.stats.rows_access}
- Matching: {diff.stats.rows_matching}
- Only in Avalonia: {diff.stats.rows_only_in_avalonia}
- Only in Access: {diff.stats.rows_only_in_access}
- Value mismatches (same key, different fields): {diff.stats.rows_value_mismatch}

## Request
```json
{json.dumps(dict(request), indent=2, default=_json_default)}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
"""
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")

    hyp = out_dir / "hypothesis.md"
    if not hyp.exists():
        hyp.write_text(
            f"# Hypothesis for `{query_id}`\n\n"
            f"(Root-cause analyst notes go here. The file is NOT overwritten\n"
            f"on subsequent harness runs.)\n",
            encoding="utf-8",
        )
    return out_dir


def _json_default(obj: Any) -> Any:
    """Fall-back serialiser for non-stdlib JSON types we might encounter
    (e.g. datetime, Decimal). Keeps the report write side cheap and
    debuggable rather than forcing every caller to pre-stringify."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__str__"):
        return str(obj)
    raise TypeError(f"unserialisable: {type(obj).__name__}")
