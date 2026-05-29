# Query `entry__kaifeng_yin_general_900_1100_entryyears` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T06:27:28.901364+00:00
**Datadump SHA**: `ed294faed44b36e80169cae8815f83d9d9c5ca3cdb79520c8d058383ad52eb43`

## Stats
- Rows Avalonia: 11
- Rows Access: 11
- Matching: 11
- Only in Avalonia: 0
- Only in Access: 0
- Value mismatches (same key, different fields): 0

## Request
```json
{
  "category": "entry",
  "case_id": "kaifeng_yin_general_900_1100_entryyears",
  "replay_inputs": "EntryQueryInputs(entry_codes=[118], addr_ids=[100658], addr_field='person', include_subunits=False, use_xy_radius=False, year_mode='entry', from_year=900, to_year=1100, from_dynasty=-1, to_dynasty=-1, from_dynasty_begin=None, to_dynasty_end=None)"
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
