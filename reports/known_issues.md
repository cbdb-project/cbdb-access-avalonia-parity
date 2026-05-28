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

### [RESOLVED 2026-05-28] office_basic / postings_basic — `c_appt_type_code` fixed upstream

Both Avalonia services now reference the correct schema column
(`pto.c_appt_code`). `tests/test_phase3d_office_pair.py` and
`tests/test_phase4_postings_pair.py` pass end-to-end again. Auto-skip
patterns have been removed from both tests. Two follow-on fixes
landed alongside the upstream rename:

- `cbdb_parity/access_postings.py`: also referenced the wrong column
  name in the hand-mirrored Access SQL; corrected.
- `cbdb_parity/access_postings.py`: added datetime → string coercion
  for `created_date` / `modified_date` (Access ODBC returns native
  `datetime.datetime` while SQLite returns the raw stored text;
  dtype diffs were drowning the real-data diff).

The historical bug description is preserved below for reference.

---

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
  export layer adds an alias. **RESOLVED 2026-05-28** — upstream
  patched.

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
  **RESOLVED 2026-05-28** — upstream patched.

### [RESOLVED 2026-05-28] kinship_expanded_network — port landed

`cbdb_parity/avalonia_kinships_expanded.py` now mirrors
`GetExpandedKinshipsAsync` end-to-end (KinshipReductionRules dict,
ReduceKinship / ResolveKinshipDisplay / Extend / BuildNotes,
maxLoop=10 BFS, depth caps, final OrderBy chain).
`tests/test_phase4_kinships_expanded.py` asserts six structural
invariants of the port (unique-by-kin, depth caps on derived rows,
direct ⊆ expanded, monotone count, determinism) plus a
ReduceKinship unit test. Original entry preserved below for
reference.

---

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
  (likely as `cbdb_parity.avalonia_kinships_expanded`). **RESOLVED
  2026-05-28**.

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

### entry_all_jinshi_general_song — LIMIT-cap truncation + no ORDER BY (NOT semantic divergence)

- **First observed**: 2026-05-28 on Datadump SHA `ed294faed44b`,
  surfaced by `tests/test_phase4_replay_scan.py`.
- **Side**: both (test-design artifact)
- **Class**: harness gap (test-input too broad for the row cap)
- **Description**: For "all entries in Song dynasty" with no other
  filters, the first scan run reported 4919 / 4993 rows on each
  side with only 144 matches. **Initial diagnosis (semantic
  divergence) was wrong** — see "Empirical resolution" below.
- **Empirical resolution** (2026-05-28 probe at limit=10000): three
  Avalonia variants were compared against three cbdb_replay modes:

  | Avalonia variant            | rep:dynasty | rep:entry-960-1279 | rep:index-960-1279 |
  |---|---|---|---|
  | `A_dynasty_ids=(15,)`       | **9871/9871 (100%)** | 6483 | 3952 |
  | `B_use_entry_year_range`    | 9812 | **9933/9933 (100%)** | 4211 |
  | `C_use_index_year_range`    | 9268 | 6309 | **9802/9802 (100%)** |

  Each Avalonia variant aligns 100% with its matching cbdb_replay
  mode (all rows present on the Avalonia side appear in the
  corresponding cbdb_replay set). The original test failure has
  TWO compounding causes, neither of which is a semantic mismatch:

  1. **Avalonia LIMIT cap**: `SqliteEntryQueryService.cs:329` clamps
     `request.Limit` to `[1, 10000]`. cbdb_replay's
     `year_mode='dynasty'` for Song returns ~40 621 unique
     `(person_id, sequence)` rows — Avalonia can never return more
     than 10000 of them.
  2. **cbdb_replay has no ORDER BY**: see `lookatentry.py` —
     `grep ORDER` finds nothing. Pandas reads rows in whatever
     physical order Access ODBC delivers them, which is index /
     insertion order. Avalonia's `ORDER BY entry_label, c_year,
     c_personid, c_sequence` produces a different top-10000 slice.

  At limit=5000 (the test's value), the two top-5000 slices share
  ZERO `person_id` overlap — they're disjoint slices of the same
  ~40k-row superset.
- **Root cause**: the test asks a question whose true result set
  exceeds Avalonia's hardcoded LIMIT cap. The semantics are correct
  on both sides; the comparison window just isn't wide enough.
- **Suppress rationale**: this is now `xfail` in the scan because
  the question itself is broader than the harness can faithfully
  compare. Tagged xfail (not skip) so any change that closes the
  gap surfaces as XPASS.
- **Suppress until**: one of (a) the upstream cbdb-user-mdb-tests
  case narrows to a subset that fits within 10000 rows
  (e.g. `entry_codes=[36]` jinshi-only); (b) Avalonia raises the
  LIMIT cap; (c) cbdb_replay adds an ORDER BY so its top-N slice
  becomes deterministic and alignable.
- **Report**: `reports/replay_scan/entry__all_jinshi_general_song/`.

### avalonia_gap — Texts / Networks / AssociationPairs / Place / GroupData

**Status (2026-05-28)**: documented permanent gap. Implementing these
upstream services in `cbdb-desktop-app` would require ~250 lines of
new C# per service (request/record/interface/SQLite implementation)
plus equivalent parity-side mirrors and pair tests. Out of scope for
the current parity-completion session; each service is documented
below with the cbdb_replay SQL pattern that an Avalonia implementor
could lift directly.

**For implementors**: each `cbdb_replay/lookat*.py` already contains
the production-validated SQL for these flows; an upstream Avalonia
implementor only needs to:

1. Mirror the request shape as `Cbdb.App.Core/<X>QueryRequest.cs`
2. Mirror each row as `Cbdb.App.Core/<X>QueryRecord.cs`
3. Add `Cbdb.App.Core/I<X>QueryService.cs` (`Task<…QueryResult>
   QueryAsync(string sqlitePath, …QueryRequest request, …)`)
4. Copy the cbdb_replay SQL into `Cbdb.App.Data/Sqlite<X>QueryService.cs`,
   adapting `$param`-style placeholders and the LIMIT/ORDER BY
5. Add the parity Python mirror + Access bridge by the same recipe
   the existing Entry/Status/Office bridges follow.

**Per-feature pointers**:

- **Texts** (simplest): `cbdb_replay/lookattexts.py` line ~50-200.
  Returns `(person, text, role)` triples filtered by `biblcat_codes`.
  15-column SELECT × 3 INNER JOINs; ~150 SLOC to port end-to-end.
- **Place**: `cbdb_replay/lookatplace.py`. People-by-index-addr query;
  similar shape to entry's `addr_field='person'` branch.
- **Networks**: `cbdb_replay/lookatnetworks.py`. Multi-hop graph
  traversal (kinship + association edges) — non-trivial.
- **AssociationPairs**: `cbdb_replay/lookatassociationpairs.py`. Path
  queries over association graph.
- **GroupData**: demographic stats (histograms, frequency tables).
  Genuinely different from any existing Avalonia service shape; needs
  product-level decision on whether to add to Avalonia.

(Historical Tier 1 "Avalonia gap" cross-reference preserved below.)

### avalonia_gap (legacy entry) — Texts / Networks / AssociationPairs / Place

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
