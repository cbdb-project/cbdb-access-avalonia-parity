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

## Empirically verified safe (no longer a concern)

### BIT column integrity — bool-1 read-back bug does NOT fire here

- **Verified**: 2026-05-28 on Datadump SHA `ed294faed44b`
- **Side**: Access (read-back via pyodbc + Microsoft Access Driver)
- **Description**: `accessAndMySQLTransfer/README.md §3` warns that
  Access reads BIT columns back as `1` regardless of stored value
  (the "all booleans become true" bug). Our verbatim ipynb-pattern
  mdb builder maps MySQL BIT → Access BIT (matching the ipynb that
  produces the production `cbdb.mdb`); the alternative SMALLINT
  coercion crashed the build at 303 MB with the Jet 2 GB
  temp-file leak.
- **Empirical check** (BIOG_MAIN.c_female histogram, MariaDB vs the
  built Access mdb): `{None: 24,265, 0: 576,616, 1: 57,607}` —
  identical on both sides. The read-back bug does NOT fire in
  the pyodbc + Microsoft Access Driver path on this dataset, so no
  parity test gets fooled by it.
- **What if it ever does fire**: the bug would manifest as
  Access histogram `{None: 24265, 1: 634223}` (every 0 read back
  as 1). Trivially re-detectable; re-run the check above on each
  new Datadump SHA and add a known_issues entry if it diverges.

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

### postings_basic — Avalonia references non-existent `pto.c_appt_type_code`

- **First observed**: 2026-05-28 on Datadump SHA `ed294faed44b`
- **Side**: Avalonia
- **Class**: Avalonia gap (schema drift)
- **Description**: `cbdb-desktop-app/Cbdb.App.Data/SqlitePersonBrowserService.cs`
  GetPostingsAsync SELECTs `pto.c_appt_type_code` via
  `LEFT JOIN APPOINTMENT_CODES appt ON appt.c_appt_code = pto.c_appt_type_code`.
  Same upstream bug as `office_basic`: the schema column is
  `pto.c_appt_code`, not `pto.c_appt_type_code`. The query raises
  `sqlite3.OperationalError: no such column: pto.c_appt_type_code`
  on real CBDB SQLite, so the postings-pair test cannot execute the
  Avalonia side at all.
- **Root cause**: identical rename inconsistency to the office_basic
  entry above. Fixing one upstream commit will resolve both.
- **Suppress rationale**: real Avalonia bug to be fixed upstream.
  Auto-skip pattern in `tests/test_phase4_postings_pair.py` catches
  the OperationalError and skips with reference to this file.
- **Suppress until**: same fix as office_basic — Avalonia code
  SELECTs `c_appt_code` or the SQLite export adds an alias.

## Suppression sunset

Per WORK_PLAN §7, every entry in this file should also have a
follow-up tracking issue in `cbdb-project`'s issue tracker. The
file is a quick-reference only; the issue tracker is the
canonical action list.
