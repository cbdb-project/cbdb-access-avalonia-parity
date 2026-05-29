# Query `entry__all_jinshi_general_song` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T06:27:34.536782+00:00
**Datadump SHA**: `ed294faed44b36e80169cae8815f83d9d9c5ca3cdb79520c8d058383ad52eb43`

## Stats
- Rows Avalonia: 40621
- Rows Access: 40621
- Matching: 40621
- Only in Avalonia: 0
- Only in Access: 0
- Value mismatches (same key, different fields): 0

## Request
```json
{
  "category": "entry",
  "case_id": "all_jinshi_general_song",
  "replay_inputs": "EntryQueryInputs(entry_codes=None, addr_ids=None, addr_field='person', include_subunits=False, use_xy_radius=False, year_mode='dynasty', from_year=None, to_year=None, from_dynasty=15, to_dynasty=15, from_dynasty_begin=960, to_dynasty_end=1279)"
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
