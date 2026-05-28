# Replay-scan results — Access cbdb-user-mdb-tests inputs × parity harness

`tests/test_phase4_replay_scan.py` parametrizes over every test case
in [cbdb-user-mdb-tests](https://github.com/cbdb-project/cbdb-user-mdb-tests)
that targets a category Avalonia also implements (entry / status /
office), runs both backends, and either diffs them (pass/fail) or
records a documented skip reason.

Last run: **2026-05-28**, Datadump SHA `ed294faed44b…`.

| # | Category | Case ID | Verdict | Rows av / ac | Notes |
|---|---|---|---|---|---|
| 1 | entry | `kaifeng_yin_general_900_1100_indexyears` | ⏭️ skip | — | Avalonia gap: no `addr_field='person'` analogue in `EntryQueryRequest`. |
| 2 | entry | `kaifeng_yin_general_900_1100_entryyears`  | ⏭️ skip | — | Same Avalonia gap. |
| 3 | entry | `all_jinshi_general_song`                  | ❌ fail | 4919 / 4993 | Real divergence: dynasty filter has two different semantics on the two sides (people-of-dynasty vs entries-in-year-range). Logged as `entry_all_jinshi_general_song` in known_issues.md. |
| 4 | entry | `kaifeng_anyentry_900_1100_indexyears`     | ⏭️ skip | — | Avalonia gap: `addr_field='person'`. |
| 5 | entry | `empty_inputs`                              | ✅ pass | 0 / 0 | Both sides correctly return empty for empty input. |
| 6 | status | `empty_codes`                              | ⏭️ skip | — | Access-bridge gap: cbdb_replay rejects empty `status_codes`. |
| 7 | status | `basic_status40_song`                       | ⏭️ skip | — | Access-bridge gap: cbdb_replay does not model `dynasty_ids`. |
| 8 | status | `status40_kaifeng_900_1100`                | ✅ pass | _matches_ | Index-year + address filter; both backends agree. |
| 9 | office | `empty_codes`                              | ⏭️ skip | — | Avalonia upstream bug: `pto.c_appt_type_code`. |
| 10 | office | `office1_song`                             | ⏭️ skip | — | Same Avalonia upstream bug. |

## Tally

- **Passed**: 2/10 — both sides agreed on row sets and field values.
- **Skipped**: 7/10 — documented gaps (Avalonia missing feature, Access bridge limitation, or upstream Avalonia bug).
- **Failed**: 1/10 — `entry/all_jinshi_general_song`, a real query-semantic divergence the scan surfaced.

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
