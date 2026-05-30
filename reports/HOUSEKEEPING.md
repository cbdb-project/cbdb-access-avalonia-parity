# `reports/` housekeeping

This directory holds per-query diff artefacts produced by
`cbdb_parity.diff_report.write_report`. The top-level dashboard
`reports/SUMMARY.md` is regenerated on demand by
`cbdb-parity-summary` (see Phase 7c). `cbdb-parity-summary`
iterates only the **immediate children** of `reports/` — a child
is treated as a per-query report when it is a directory
containing `diff.json` directly. Sub-subdirectories like
`replay_scan/<category>__<case>/` are NOT discovered by the
dashboard; they exist as a separate artefact tree the per-case
pair tests write to.

## Active report paths (post-Phase-7)

| path | populated by | in SUMMARY.md? |
|---|---|---|
| `entry_basic/` | `tests/test_phase3c_entry_pair.py` | yes |
| `office_basic/` | `tests/test_phase3d_office_pair.py` | yes |
| `status_basic/` | `tests/test_phase3e_status_pair.py` | yes |
| `kinships_basic_person/` | `tests/test_phase4_kinships_pair.py` | yes |
| `replay_scan/<category>__<case>/` | `tests/test_phase4_replay_scan.py` | **no** — nested, dashboard doesn't recurse |

Plus the hand-maintained docs at the root: `known_issues.md`,
`known_issues.zh-Hant.md`, this file, and the dashboard
`SUMMARY.md` itself when generated.

## Retired report paths (Phase 6b)

Phase 6b deleted the per-surface paths for the 12 retired
PersonBrowser pair tests plus `associations_basic_person` (13
total). If your local clone still has them — leftover sediment
from a pytest run BEFORE Phase 6b landed — they are safe to
delete:

```powershell
$retired = @(
    'reports/addresses_basic_person',
    'reports/altnames_basic',
    'reports/associations_basic_person',
    'reports/biog_basic_search',
    'reports/detail_basic_person',
    'reports/entries_basic_person',
    'reports/events_basic_person',
    'reports/institutions_basic_person',
    'reports/possessions_basic_person',
    'reports/postings_basic_person',
    'reports/sources_basic_person',
    'reports/statuses_basic_person',
    'reports/writings_basic_person'
)
foreach ($p in $retired) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
    }
}
```

The `Test-Path` guard means partial cleanups don't emit
errors for dirs that are already gone.

The corresponding pair tests are gone, so nothing will recreate
these paths on a fresh test run. Git tracks files, not
directories: Phase 6b removed the tracked `diff.json` /
`summary.md` / `hypothesis.md` files under those paths, so a
fresh checkout doesn't see them at all. On a long-lived local
clone, the directories themselves can survive (empty or holding
only `.gitignore`-d artefacts like `access.json` / `avalonia.json`),
and `git status` then stays silent because the only payload is
git-ignored. The cleanup above is purely local hygiene.

## When `cbdb-parity-summary` notices a retired path

The CLI iterates every immediate subdirectory of `reports/`. A
retired pre-Phase-6b directory at the top level that still
contains a `diff.json` would be picked up as a per-query report
and appear in `reports/SUMMARY.md` under its old query_id. Run
the cleanup above before regenerating the dashboard if you've
inherited that kind of sediment. The dashboard does NOT recurse,
so a stale file deep inside `replay_scan/` would NOT contaminate
the dashboard — only top-level dirs are at risk.
