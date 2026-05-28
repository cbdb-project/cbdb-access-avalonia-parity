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

### office_basic — Avalonia references non-existent `pto.c_appt_type_code`

- **First observed**: 2026-05-28 on Datadump SHA `ed294faed44b` (cbdb_data_20260527.tar.gz)
- **Side**: Avalonia
- **Class**: Avalonia gap (schema drift)
- **Description**: `cbdb-desktop-app/Cbdb.App.Data/SqliteOfficeQueryService.cs:307`
  SELECTs `pto.c_appt_type_code` and the JOIN at line 365 reads it.
  But `POSTED_TO_OFFICE_DATA` only has `c_appt_code`. The query
  raises `sqlite3.OperationalError: no such column: pto.c_appt_type_code`
  on real CBDB data, so the office-pair smoke test cannot execute
  the Avalonia side at all. This is exactly the class of finding
  the parity harness was designed to surface — Avalonia code
  references a schema column that does not exist in the actual
  CBDB SQLite emitted from the canonical MySQL Datadump.
- **Root cause**: Avalonia commit history likely renamed
  `c_appt_code` → `c_appt_type_code` in the Avalonia query without
  the corresponding rename in the SQLite export side (which still
  derives from MySQL's `c_appt_code`). Or the rename was speculative
  for a future schema migration that didn't happen.
- **Suppress rationale**: real Avalonia bug to be fixed upstream
  in `cbdb-desktop-app`. Suppressing here prevents the parity gate
  from being permanently red on office_basic while the upstream
  fix is in flight.
- **Suppress until**: Avalonia `SqliteOfficeQueryService.cs` SELECTs
  the column that actually exists (`c_appt_code`) or the SQLite
  export layer adds an alias.

## Suppression sunset

Per WORK_PLAN §7, every entry in this file should also have a
follow-up tracking issue in `cbdb-project`'s issue tracker. The
file is a quick-reference only; the issue tracker is the
canonical action list.
