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

### kinship_expanded_network — Python port of Avalonia GetExpandedKinshipsAsync deferred

- **First observed**: 2026-05-28
- **Side**: harness (Python port not yet implemented)
- **Class**: harness gap
- **Description**: `tests/test_phase4_kinships_pair.py` covers the
  direct (`expandNetwork=false`) branch only. The
  `expandNetwork=true` branch in Avalonia
  `SqlitePersonBrowserService.GetExpandedKinshipsAsync` does an
  iterative graph traversal with depth limits (`maxUp=2, maxDown=2,
  maxMarriage=1, maxCollateral=1, maxLoop=10`) — a deterministic
  state machine using `KinshipTraversalState.Extend` and
  `ReduceKinship`. Porting it to Python is mechanical but non-trivial
  and would significantly grow `cbdb_parity.avalonia_kinships`.
- **Root cause**: bandwidth — Tier 2 prioritised SQL-level parity.
- **Suppress rationale**: Tier 2 already verifies the 1-hop SQL is
  identical across SQLite and Access. The recursive traversal is
  pure post-processing — porting it gates on a separate Python-side
  state-machine implementation, not on the parity contract itself.
- **Suppress until**: a Python port of GetExpandedKinshipsAsync lands
  (likely as `cbdb_parity.avalonia_kinships_expanded`).

### group_data_demographics — Access-only; no Avalonia analogue

- **First observed**: 2026-05-28
- **Side**: Avalonia (gap)
- **Class**: Access-only flow
- **Description**: Access `Form_LookAtGroupData` / `CmdRun`
  (`groupdata_demographic_stats`) computes demographic distributions
  for a person set (birth-year histograms, status frequencies, etc.).
  Avalonia's `IGroupPeopleService.QueryAsync` returns grouped
  per-relation records (the equivalent of running each Tier 2
  per-person accessor for a list of people and concatenating); it
  does NOT produce demographic stats. The two are genuinely different
  questions, not a shape-mismatch.
- **Root cause**: Avalonia hasn't implemented the demographic
  aggregation flow.
- **Suppress rationale**: nothing to compare. If Avalonia adds
  demographic aggregation, this entry should be replaced by a
  paired test.
- **Suppress until**: Avalonia adds a demographic-aggregation
  service or method.

### entry_all_jinshi_general_song — dynasty filter semantic divergence

- **First observed**: 2026-05-28 on Datadump SHA `ed294faed44b`, surfaced by
  `tests/test_phase4_replay_scan.py::test_replay_scan[entry-all_jinshi_general_song]`.
- **Side**: both (different question, same name)
- **Class**: shape-mismatch (query semantics)
- **Description**: For "all entries in Song dynasty" with no other
  filters, Avalonia returns 4919 rows while cbdb_replay returns 4993,
  overlapping on only 144 rows. Sampling the only-in-X buckets shows
  the two backends are matching **different sets of people**:
  Avalonia filters `BIOG_MAIN.c_dy IN (dynasty_ids)` — i.e. "entries
  of people whose dynasty IS Song"; cbdb_replay's dynasty mode
  filters by the 960-1279 year range against an entry/index year
  field — i.e. "entries that happened during Song years". A person
  whose c_dy is Tang but who has an entry in 1000 appears on one
  side only, and vice versa.
- **Root cause**: same human-language label ("dynasty filter") covers
  two genuinely different SQL predicates. Neither side is wrong;
  they answer different questions.
- **Suppress rationale**: this is not a bug to fix on either side —
  it's a semantic mismatch the parity harness was designed to
  surface. Resolution requires a product-level decision on which
  semantics "dynasty filter" should mean, then aligning both backends
  on that. Until then, the scan keeps the case as a documented red
  marker so the divergence stays visible.
- **Suppress until**: a product-level alignment lands on either side
  (or the scan switches this case to a narrower question both sides
  can agree on, e.g. dropping dynasty mode and using explicit
  `c_year` ranges).
- **Report**: `reports/replay_scan/entry__all_jinshi_general_song/`.

### avalonia_gap — Texts / Networks / AssociationPairs / Place

- **First observed**: 2026-05-28
- **Side**: Avalonia (gap)
- **Class**: Access-only flow (4 distinct features)
- **Description**: Access has test-driven flows for `texts_basic_search`
  (Form_LookAtTexts), `network_personal_expansion` (Form_LookAtNetworks),
  `assocpairs_path_queries` (Form_LookAtAssociationPairs), and
  `place_basic_search` (Form_LookAtPlace). Avalonia has no equivalent
  services for any of these (per
  `coverage/avalonia_queries.yaml`).
- **Root cause**: Avalonia is biased toward person-centric flows
  (PersonBrowser per-person accessors); text/place/network-centric
  flows haven't been ported from Access yet.
- **Suppress rationale**: nothing to compare until Avalonia
  implements at least one of these. Listed individually in
  `coverage/matrix.md`; this entry is a quick cross-reference.
- **Suppress until**: at least one of Texts / Networks /
  AssociationPairs / Place lands in `cbdb-desktop-app`.

## Suppression sunset

Per WORK_PLAN §7, every entry in this file should also have a
follow-up tracking issue in `cbdb-project`'s issue tracker. The
file is a quick-reference only; the issue tracker is the
canonical action list.
