"""Aggregator for `reports/SUMMARY.md` — the top-level dashboard
that surveys all per-query reports under `reports/<query_id>/`.

Per WORK_PLAN §7:
    Top-level reports/SUMMARY.md aggregates: total queries, paired,
    passing, failing, Avalonia-missing.

This module reads every `reports/<query_id>/diff.json` (the canonical
per-query artefact produced by `cbdb_parity.diff_report.write_report`)
and renders a single markdown dashboard. It's idempotent — re-running
overwrites SUMMARY.md based on whatever's currently on disk.

`reports/known_issues.md` is NOT regenerated here; that's a hand-
maintained file (per §7) that suppresses noise on confirmed Avalonia
gaps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class _QueryRow:
    """A single line in the SUMMARY.md table."""

    query_id: str
    matches: bool
    rows_avalonia: int
    rows_access: int
    rows_matching: int
    rows_only_in_avalonia: int
    rows_only_in_access: int
    rows_value_mismatch: int
    generated_at: str
    datadump_sha: str | None


def _load_diff(diff_path: Path) -> _QueryRow | None:
    """Parse one report's diff.json into a _QueryRow; returns None on a
    malformed/missing file so the dashboard never aborts on a single
    bad entry."""
    try:
        payload: dict[str, Any] = json.loads(diff_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        return None
    return _QueryRow(
        query_id=str(payload.get("query_id", diff_path.parent.name)),
        matches=bool(stats.get("matches", False)),
        rows_avalonia=int(stats.get("rows_avalonia", 0)),
        rows_access=int(stats.get("rows_access", 0)),
        rows_matching=int(stats.get("rows_matching", 0)),
        rows_only_in_avalonia=int(stats.get("rows_only_in_avalonia", 0)),
        rows_only_in_access=int(stats.get("rows_only_in_access", 0)),
        rows_value_mismatch=int(stats.get("rows_value_mismatch", 0)),
        generated_at=str(payload.get("generated_at", "")),
        datadump_sha=payload.get("datadump_sha"),
    )


def render_summary(reports_dir: Path) -> str:
    """Build the SUMMARY.md text (not written to disk by this fn)."""
    rows: list[_QueryRow] = []
    if reports_dir.is_dir():
        for child in sorted(reports_dir.iterdir()):
            if not child.is_dir():
                continue
            diff_path = child / "diff.json"
            row = _load_diff(diff_path)
            if row is not None:
                rows.append(row)

    total = len(rows)
    passing = sum(1 for r in rows if r.matches)
    failing = total - passing

    lines = [
        "# CBDB Avalonia ↔ Access parity — SUMMARY",
        "",
        f"_Generated: {datetime.now(UTC).isoformat()}_",
        "",
        "## Top-level",
        "",
        f"- **Total paired queries**: {total}",
        f"- **Passing** (rows match): {passing}",
        f"- **Failing** (mismatch present): {failing}",
        "",
    ]

    if not rows:
        lines.append(
            "_No per-query reports found under `reports/<query_id>/diff.json`. "
            "Run the differential harness to populate._"
        )
        return "\n".join(lines) + "\n"

    lines.extend([
        "## Per query",
        "",
        "| Query | Verdict | Avalonia | Access | Match | Only-Av | Only-Ac | Value-mismatch | Datadump SHA | Generated |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ])
    for r in rows:
        verdict = "✅ PASS" if r.matches else "❌ FAIL"
        sha_short = (r.datadump_sha or "(none)")[:12]
        lines.append(
            f"| `{r.query_id}` | {verdict} | {r.rows_avalonia} | {r.rows_access} | "
            f"{r.rows_matching} | {r.rows_only_in_avalonia} | {r.rows_only_in_access} | "
            f"{r.rows_value_mismatch} | `{sha_short}` | {r.generated_at[:19]} |"
        )

    lines.extend([
        "",
        "## Known issues",
        "",
        "See [`known_issues.md`](known_issues.md) for confirmed Avalonia "
        "gaps that are intentionally suppressed from the parity gate. "
        "That file is hand-maintained; this summary doesn't regenerate it.",
        "",
    ])
    return "\n".join(lines) + "\n"


def write_summary(reports_dir: Path) -> Path:
    """Build and write `reports/SUMMARY.md`, returning the path."""
    text = render_summary(reports_dir)
    out = reports_dir / "SUMMARY.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def cli_main() -> int:
    """Phase 7c — `cbdb-parity-summary` CLI entry point.

    Renders `reports/SUMMARY.md` from whatever per-query
    `reports/<query_id>/diff.json` files currently exist. By
    convention the reports tree lives at `<cwd>/reports`, matching
    every other CLI in this package.

    A `--reports-dir` flag lets a caller (or a future
    pytest session-finish hook) point at a non-default location.

    Exit codes:
      0 — SUMMARY.md was rewritten.
      2 — `<reports-dir>` does not exist (the directory tree is
          missing entirely; usually means the differential harness
          hasn't been run yet). Distinguished from "no reports
          inside the dir" because the latter is a legitimate empty
          state and `render_summary` already represents it cleanly.

    We deliberately do NOT regenerate `reports/known_issues.md` —
    that file is hand-maintained per WORK_PLAN §7.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="cbdb-parity-summary",
        description=(
            "Render reports/SUMMARY.md from per-query diff.json "
            "files. Idempotent — overwrites whatever's currently at "
            "reports/SUMMARY.md."
        ),
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path.cwd() / "reports",
        help=(
            "Path to the reports tree. Defaults to <cwd>/reports, "
            "matching the layout the other cbdb-parity-* CLIs use."
        ),
    )
    args = parser.parse_args()

    reports_dir: Path = args.reports_dir
    if not reports_dir.exists():
        print(
            f"cbdb-parity-summary: reports directory not found: "
            f"{reports_dir}. Run the differential harness first.",
            flush=True,
        )
        return 2

    out_path = write_summary(reports_dir)
    print(f"cbdb-parity-summary: wrote {out_path}", flush=True)
    return 0
