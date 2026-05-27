# Known parity issues — suppressed from the gate

This file lists Access/Avalonia disagreements that the harness has
already surfaced and analysed, and which the maintainers have decided
should NOT block the parity gate on subsequent runs.

The list is **hand-maintained** — `cbdb_parity.summary_report.write_summary`
will reference it from the top-level `SUMMARY.md` dashboard but never
overwrites this file.

## Format

Each entry uses this shape:

```
### <query_id> — <one-line title>

- **First observed**: YYYY-MM-DD on Datadump SHA `<short-sha>`
- **Side**: Avalonia / Access / both
- **Class**: shape-mismatch / data-version drift / Avalonia gap / Access gap / harness bug
- **Description**: one paragraph on what's going wrong
- **Root cause**: one paragraph (link to the per-query `hypothesis.md` for detail)
- **Suppress rationale**: why this is intentionally not gating

The bottom of each entry adds:

- **Suppress until**: a Datadump date, a commit SHA, "permanent",
  or "until Avalonia adds X" — whatever makes the suppression
  temporally bounded.
```

## Currently suppressed

_(none yet — populate as Phase 3/4 finds them.)_

## Suppression sunset

Per WORK_PLAN §7, every entry in this file should also have a
follow-up tracking issue in `cbdb-project`'s issue tracker. The
file is a quick-reference only; the issue tracker is the
canonical action list.
