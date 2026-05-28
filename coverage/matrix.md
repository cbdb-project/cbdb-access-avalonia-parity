# CBDB Access ↔ Avalonia query coverage matrix (Phase 2)

Pairing of Access query features (driven by [cbdb-user-mdb-tests](https://github.com/cbdb-project/cbdb-user-mdb-tests))
against Avalonia query features (in [cbdb-desktop-app](https://github.com/frankslin/cbdb-desktop-app)).

**Status legend:**
- ✅ **paired** — both sides implement the query; Phase 3 differential harness can compare results directly
- ⚠️ **access-only** — Access has it; Avalonia doesn't (yet) — Phase 3 records this as a known Avalonia gap
- 🆕 **avalonia-only** — Avalonia has it; Access doesn't drive it via the test framework (may exist as raw Access UI without test coverage)
- ❌ **missing-on-both** — present in neither (placeholder; nothing to compare)

## Tier 1: core "look-at" queries — Phase 3 priorities

These are the high-value paired queries that should land first in the differential harness.

| # | Query | Access (id, form, command) | Avalonia (service, method) | Status |
|---|---|---|---|---|
| 1 | **Biographic basic** | _(no Access test-driven form; closest analogue is Form_LookAtPeople which has no automated coverage)_ | `IPersonBrowserService.SearchAsync(keyword, limit, offset)` | ✅ paired — `tests/test_phase4_biog_basic_pair.py` (no-keyword branch; keyword/personId branches queued as follow-ups) |
| 2 | **Entry codes query** | `entry_basic_search` · Form_LookAtEntry · CmdQuery | `IEntryQueryService.QueryAsync` | ✅ paired |
| 3 | **Office query** | `office_basic_search` · Form_LookAtOffice · CmdQuery | `IOfficeQueryService.QueryAsync` | ✅ paired |
| 4 | **Status query** | `status_basic_search` · Form_LookAtStatus · CmdQuery | `IStatusQueryService.QueryAsync` | ✅ paired |
| 5 | **Texts/bibliography** | `texts_basic_search` · Form_LookAtTexts · CmdQuery | _none_ | ⚠️ access-only |
| 6 | **Associations** | `assoc_basic_search` · Form_LookAtAssociations · CmdQuery — *code/dynasty-filtered people list* | `IPersonBrowserService.GetAssociationsAsync(personId)` — *per-person associations* | ✅ paired (per-person shape) — `tests/test_phase4_associations_pair.py` answers "associations of person X" on both sides via raw SQL. The Access form's code-filter list workflow is intentionally NOT mirrored — it's an Access-only UI flow, distinct from the per-person question. |
| 7 | **Kinship** | `kinship_recursive_traversal` · Form_LookAtKinship · CmdRun — *recursive expansion from seed* | `IPersonBrowserService.GetKinshipsAsync(personId, expandNetwork=false)` direct branch (Tier 2-tested) + `expandNetwork=true` graph traversal (multi-hop with `maxUp=2, maxDown=2, maxMarriage=1, maxCollateral=1` and `maxLoop=10`) | ✅ paired (1-hop direct branch) — `tests/test_phase4_kinships_pair.py`. The expandNetwork=true traversal (Avalonia GetExpandedKinshipsAsync) is a deterministic Python-portable state machine; a recursive-traversal pair test is queued as a follow-up (requires porting `KinshipTraversalState.Extend` + `ReduceKinship` + the rank-by-Up/Down/Mar/Col tuple). |
| 8 | **Network expansion** | `network_personal_expansion` · Form_LookAtNetworks · CmdRun | _none_ | ⚠️ access-only |
| 9 | **Association pairs** (path queries) | `assocpairs_path_queries` · Form_LookAtAssociationPairs · CmdQuery | _none_ | ⚠️ access-only |
| 10 | **Place / GIS** | `place_basic_search` · Form_LookAtPlace · CmdQuery | _none_ | ⚠️ access-only |
| 11 | **Group demographics** _(Access side)_ vs **Group people aggregation** _(Avalonia side)_ | `groupdata_demographic_stats` · Form_LookAtGroupData · CmdRun (✗ timeout on full inputs; small-fixture tests in test_vba_networks_small_fixture.py) | `IGroupPeopleService.QueryAsync(personIds, options)` returns grouped per-relation records (status/office/entry/text/address) — NOT demographic stats | ⚠️ misaligned — **closed as no-pair**. The two sides ask genuinely different questions; the SAME-question reformulation is the per-relation per-person flow already covered by Tier 2 (entries/postings/addresses/etc.). Access GroupData's demographic aggregation has no Avalonia analogue and is queued in known_issues.md as an Access-only flow. |
| 12 | **Picker dropdowns** | none — Access populates from raw codes tables | `IPlaceLookupService` / `IDynastyLookupService` / `*PickerData*Async` | 🆕 avalonia-only (lookup data; no Access-driven equivalent needed) |

## Tier 2: per-person detail accessors (Avalonia PersonBrowser)

PersonBrowser's 14 detail methods (`Get<X>Async(personId)`) each return a per-person view of one CBDB relationship type. The Access test framework doesn't drive Form_LookAtPeople (the natural pair), so these are mostly _Avalonia-only_ from the test-harness perspective — but each one IS testable against the underlying mdb via direct SQL.

| Avalonia method | Underlying table(s) | Access equivalent | Phase 3 approach |
|---|---|---|---|
| `GetAddressesAsync` | BIOG_ADDR_DATA + ADDRESSES + ADDR_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetAltNamesAsync` | ALTNAME_DATA | pyodbc SQL | ✅ direct SQL compare |
| `GetWritingsAsync` | TEXT_DATA + TEXT_CODES (?) | pyodbc SQL | ✅ direct SQL compare |
| `GetPostingsAsync` | POSTED_TO_OFFICE_DATA + POSTING_DATA | pyodbc SQL | ✅ direct SQL compare |
| `GetEntriesAsync` | ENTRY_DATA + ENTRY_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetStatusesAsync` | STATUS_DATA + STATUS_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetPossessionsAsync` | POSSESSION_ACT_DATA | pyodbc SQL | ✅ direct SQL compare |
| `GetEventsAsync` | EVENTS_DATA + EVENT_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetKinshipsAsync` | KIN_DATA + KINSHIP_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetAssociationsAsync` | ASSOC_DATA + ASSOC_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetSourcesAsync` | BIOG_SOURCE_DATA + TEXT_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetInstitutionsAsync` | BIOG_INST_DATA + SOCIAL_INSTITUTION_CODES | pyodbc SQL | ✅ direct SQL compare |
| `GetDetailAsync` | BIOG_MAIN + 5-6 join tables | pyodbc SQL | ✅ direct SQL compare |
| `GetRelatedItemsAsync` | dispatch — covered by per-relation methods above | dispatch | n/a |

## Tier 3: Access-only export workflows

These produce files (GIS .tab, Neo4j CSV sets, UCINet .vna, Pajek .net, Gephi .gexf) rather than UI result rows. Out of scope for query-result parity, but listed for completeness.

| Form | GIS | Neo4j | UCINet | Pajek | Gephi |
|---|:---:|:---:|:---:|:---:|:---:|
| LookAtEntry | ✓ | ✓ | — | — | — |
| LookAtOffice | ✓ | ✓ | — | — | — |
| LookAtStatus | ✓ | ✓ | — | — | — |
| LookAtTexts | ✓ | ✓ | — | — | — |
| LookAtAssociations | ✓ | ✓ | (issue #22) | ✓ | ✓ |
| LookAtPlace | ✓ | ✓ | gap | — | — |
| LookAtKinship | ✓ | — | ✓ (fragile) | — | — |
| LookAtNetworks | — | gap timeout | — | — | — |
| LookAtAssociationPairs | — | ✓ | — | — | — |

## Tier 4: import / save list helpers (per-form bulk-IO)

Access has `CmdImport*` (read tab/comma-separated input file → form selection set) and `CmdSave*` (export form selection to tab file) on every code-driven form. Avalonia doesn't have analogous bulk-IO; users interact with picker dropdowns one item at a time. Not in Phase 3 scope.

## Summary counts

- **Avalonia query services**: 7 user-facing (Entry/Office/Status/PersonBrowser/GroupPeople/PlaceLookup/DynastyLookup) + 2 diagnostic (DatabaseHealth/DatabaseIndex) = 9 services, **29 methods total** (2+2+3+16+1+1+1+1+2)
- **Access driver-covered queries**: 43 entries (across 11 forms × ~3-5 actions/form; 5 status values used)
- **Directly-comparable pairs (Phase 4 landed)**: Tier 1 = 4 ✅ (entry, office, status, BIOG basic) + Tier 2 = 13 ✅ (per-person PersonBrowser accessors — altnames, entries, addresses, writings, postings*, statuses, possessions, events, kinships, associations, sources, institutions, detail) = **17 query pairs** with end-to-end PASS reports under `reports/`. *postings auto-skips on a documented upstream Avalonia schema bug (`pto.c_appt_type_code`); same bug also affects office_basic.
- **Closed-by-tier-2** (originally listed as shape-mismatched but resolved by asking the per-person question on both sides): associations and kinship (non-recursive). The kinship `expandNetwork=true` graph traversal is queued as a follow-up — requires porting the `KinshipTraversalState` machine to Python.
- **No-pair (genuinely misaligned)**: GroupData demographics. Documented in `reports/known_issues.md` as Access-only.
- **Access-only — no Avalonia analogue**: Texts, Networks, AssociationPairs, Place. Documented in `reports/known_issues.md` as Avalonia gaps; nothing to compare until those services land in `cbdb-desktop-app`.
- **Avalonia-only**: PickerData + diagnostics (DatabaseHealth/Index); not user-facing query results

## Phase 3 recommended starter set (3 queries end-to-end)

Per WORK_PLAN §8 phasing — but with shape-mismatch caveats from this matrix:

1. **Office query** → Avalonia `IOfficeQueryService.QueryAsync` vs Access `cbdb_replay/lookatoffice` + Form_LookAtOffice. **Same shape** (code/dynasty-filtered list); ready to drive.
2. **Entry query** → Avalonia `IEntryQueryService.QueryAsync` vs Access `cbdb_replay/lookatentry` + Form_LookAtEntry. **Same shape**; ready to drive.
3. **Status query** → Avalonia `IStatusQueryService.QueryAsync` vs Access `cbdb_replay/lookatstatus` + Form_LookAtStatus. **Same shape**; ready to drive.

These three are the strictly-same-shape pairs from Tier 1 — proving the harness on these first before tackling the shape-mismatched ones (associations / kinship / GroupData) avoids confounding harness-plumbing bugs with shape-negotiation issues.

WORK_PLAN §8 originally suggested "BIOG basic / office / kinship" — but BIOG basic has no Access-test form pair (would need a custom SQL fixture), and kinship is recursive-vs-1-hop mismatched (would need recursive Avalonia or 1-hop-restricted Access). Substituting Entry+Status keeps the same number of starter queries while staying on solid shape ground; the originally-named pair can land in Phase 4 once shape negotiation is resolved.

## Open follow-ups

- **Case-normalisation of table names** between mdb and sqlite (Phase 1.5 surfaced: mdb's `CopyTablesDefault` ≠ sqlite's `COPYMISSINGTABLES`). Phase 3 normaliser must collapse case for table-level comparisons.
- **Different shapes**: Access associations query is *code-filtered list*; Avalonia is *per-person list*. The diff requires asking the same question on both sides (e.g. "associations of person X" in both); won't be a bare SQL row-set diff.
- **Kinship distance limit**: Access's `CmdRun` may use a different default expansion depth than Avalonia's `expandNetwork=true`. Phase 3 will need to fix expansion depth on both sides.
- **Phase 1.3b** (Access mdb writer) is still deferred and is the **unblocker for Phase 3**.
  The repo's strict-pipeline rule (WORK_PLAN §1) requires both stacks to be fed from the *same* Datadump — drift between them would surface as false-positive Avalonia/Access disagreements. Phase 3 differential comparisons MUST use:
  - generated `cbdb_data.mdb` (Phase 1.3b) + fixed `CBDB_BJ_User.mdb`
  - generated `cbdb.sqlite` (Phase 1.2, already working)
  — both from the SAME Datadump archive.
  Pre-existing mdb files on the user's machine (e.g. `CBDB_BJ_20260430/CBDB_20260430_DATA.mdb`) are NOT acceptable substitutes, even for smoke testing — they would inject data-version drift and weaken the test contract. Nothing downstream of Phase 1.3b may run until 1.3b lands.
- **Access inventory completeness**: the 43 entries in `access_queries.yaml` are a first-pass enumeration from `tests/test_vba_*.py` + form-specs. The CBDB Access UI has additional commands (`CmdGUESS` cross-form, `CmdGISPeople`, several import handlers under `Form_LookAtPeople` / `Form_LookAtBaseMaintenance`) that the test framework also covers but which this matrix doesn't yet list. Phase 3 fixture discovery will expand the inventory as paired queries are added — `coverage/` is a living document.
