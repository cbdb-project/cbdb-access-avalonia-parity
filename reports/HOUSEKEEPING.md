# `reports/` housekeeping

This directory holds per-query diff artefacts produced by
`cbdb_parity.diff_report.write_report`. The top-level dashboard
`reports/SUMMARY.md` is regenerated on demand by
`cbdb-parity-summary` (see Phase 7c).

## Active tracked subdirectories (post-Phase-7)

| dir | populated by |
|---|---|
| `entry_basic/` | `tests/test_phase3c_entry_pair.py` |
| `office_basic/` | `tests/test_phase3d_office_pair.py` |
| `status_basic/` | `tests/test_phase3e_status_pair.py` |
| `kinships_basic_person/` | `tests/test_phase4_kinships_pair.py` |
| `replay_scan/<category>__<case>/` | `tests/test_phase4_replay_scan.py` |

Plus the hand-maintained docs at the root:
`known_issues.md`, `known_issues.zh-Hant.md`, this file.

## Retired subdirectories (Phase 6b)

Phase 6b deleted the per-surface dirs for the 12 retired
PersonBrowser pair tests plus `associations_basic_person` (13
total). If your local clone still has them — leftover sediment
from a pytest run BEFORE Phase 6b landed — they are safe to
delete:

```powershell
Remove-Item -Recurse -Force reports/addresses_basic_person `
    reports/altnames_basic reports/associations_basic_person `
    reports/biog_basic_search reports/detail_basic_person `
    reports/entries_basic_person reports/events_basic_person `
    reports/institutions_basic_person reports/possessions_basic_person `
    reports/postings_basic_person reports/sources_basic_person `
    reports/statuses_basic_person reports/writings_basic_person
```

The corresponding pair tests are gone, so nothing will recreate
these directories on a fresh test run. They aren't tracked in
git (Phase 6b removed them from the index) and they don't show
up in `git status` because untracked directories without new
files are silent. The cleanup is purely local hygiene.

## When `cbdb-parity-summary` notices a retired dir

The CLI iterates every immediate subdirectory of `reports/` and
treats one with a `diff.json` as a per-query report. A stale
directory left over from a pre-Phase-6b run that still has
`diff.json` inside it would appear in `reports/SUMMARY.md` under
its old query_id. Run the cleanup above before regenerating the
dashboard if you've inherited such sediment.
