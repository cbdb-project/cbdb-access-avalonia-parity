# Query `status__basic_status40_song` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T19:08:32.520479+00:00
**Datadump SHA**: `ed294faed44b36e80169cae8815f83d9d9c5ca3cdb79520c8d058383ad52eb43`

## Stats
- Rows Avalonia: 5000
- Rows Access: 5000
- Matching: 5000
- Only in Avalonia: 0
- Only in Access: 0
- Value mismatches (same key, different fields): 0

## Request
```json
{
  "category": "status",
  "case_id": "basic_status40_song",
  "replay_inputs": "StatusQueryInputs(status_codes=[40], addr_ids=None, include_subunits=False, use_xy_radius=False, xy_narrow=True, year_mode='dynasty', from_year=None, to_year=None, from_dynasty=15, to_dynasty=15, from_dynasty_begin=960, to_dynasty_end=1279)"
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
