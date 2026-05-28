# Replay-scan results — Access cbdb-user-mdb-tests inputs × parity harness

`tests/test_phase4_replay_scan.py` parametrizes over every test case
in [cbdb-user-mdb-tests](https://github.com/cbdb-project/cbdb-user-mdb-tests)
that targets a category Avalonia also implements (entry / status /
office), runs both backends, and either diffs them (pass/fail) or
records a documented skip reason.

Last run: **2026-05-28**, Datadump SHA `ed294faed44b…`.

| # | Category | Case ID | Verdict | Notes |
|---|---|---|---|---|
| 1 | entry | `kaifeng_yin_general_900_1100_indexyears` | ✅ pass | **Newly passing** after upstream AddrField feature + parity-side case-insensitive match. |
| 2 | entry | `kaifeng_yin_general_900_1100_entryyears`  | ✅ pass | **Newly passing** (same fix). |
| 3 | entry | `all_jinshi_general_song`                  | ✅ pass | **Newly passing** after LIMIT cap raised from 10_000 → 100_000 upstream. 40_621 / 40_621 / 40_621 matching rows. |
| 4 | entry | `kaifeng_anyentry_900_1100_indexyears`     | ✅ pass | **Newly passing** (AddrField fix). |
| 5 | entry | `empty_inputs`                              | ✅ pass | Both sides correctly return empty for empty input. |
| 6 | status | `empty_codes`                              | ✅ pass | Both sides return empty after the upstream Avalonia picker-contract short-circuit (`SqliteStatusQueryService.QueryAsync` early-returns when `StatusCodes.Count == 0`). |
| 7 | status | `basic_status40_song`                       | ✅ pass | 12_181 / 12_181 matching after LIMIT cap raise + dynasty bridge extension. |
| 8 | status | `status40_kaifeng_900_1100`                | ✅ pass | Index-year + address filter. |
| 9 | office | `empty_codes`                              | ✅ pass | Same picker-contract short-circuit on the Avalonia side. |
| 10 | office | `office1_song`                             | ✅ pass | **Newly passing** after upstream c_appt_type_code fix + office bridge dynasty extension. |

## Tally

- **Passed**: 10/10 ✅
- **Skipped**: 0/10
- **xfail**: 0/10

Every cbdb-user-mdb-tests lookat input that targets an Avalonia-
implemented category now produces byte-identical row sets on both
backends.

## Dynasty-filter probe (2026-05-28)

To rule out the original "semantic divergence" diagnosis on
`entry/all_jinshi_general_song`, three Avalonia variants were
compared against three cbdb_replay year-filter modes at
`limit=10000`:

| Avalonia variant            | cbdb_replay:dynasty | cbdb_replay:entry-960-1279 | cbdb_replay:index-960-1279 |
|---|---|---|---|
| `A_dynasty_ids=(15,)`       | **9871/9871 (100%)** | 6483 | 3952 |
| `B_use_entry_year_range`    | 9812 | **9933/9933 (100%)** | 4211 |
| `C_use_index_year_range`    | 9268 | 6309 | **9802/9802 (100%)** |

Reading: each Avalonia variant's row set is fully contained in
the matching cbdb_replay mode's row set. The semantics are
aligned across all three pairings. The original test failure was
caused by:

1. **Avalonia hardcoded LIMIT cap of 10000**
   (`SqliteEntryQueryService.cs:329`) vs cbdb_replay's ~40k-row
   output for "all Song entries" — Avalonia can't return more
   than 10000 of them.
2. **cbdb_replay has no ORDER BY** — its top-N slice is
   physical/index order; Avalonia's ORDER BY produces a different
   top-N slice. The two truncated 5000-row windows share zero
   `person_id`s.

## What the scan answers (and what it doesn't)

**Does answer**: for each Access test input that both backends can
execute, do they return the same rows? Yes for 2/10, plus 1
divergence found.

**Doesn't answer**: it doesn't grow our query coverage — the 10 cases
are whatever cbdb-user-mdb-tests already encodes. To widen coverage,
add more cases to cbdb-user-mdb-tests (which will then flow through
this scan automatically) OR add more case IDs inside
`_load_user_mdb_tests_cases` for inputs the upstream test suite
hasn't yet encoded.

## How to extend

1. Land a new test case in cbdb-user-mdb-tests' `test_lookat*.py` or
   add a new `cases.append((category, case_id, inputs, None))` block
   in `_load_user_mdb_tests_cases`.
2. Re-run `pytest tests/test_phase4_replay_scan.py`.
3. If a new case lights up red, decide: (a) extend the Avalonia /
   Access bridge to support that input shape, or (b) document it
   as a gap in `reports/known_issues.md`.
