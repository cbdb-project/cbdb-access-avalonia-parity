# Query `status__status40_kaifeng_900_1100` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T20:10:22.387861+00:00
**Datadump SHA**: `ed294faed44b36e80169cae8815f83d9d9c5ca3cdb79520c8d058383ad52eb43`

## Stats
- Rows Avalonia: 270
- Rows Access: 270
- Matching: 270
- Only in Avalonia: 0
- Only in Access: 0
- Value mismatches (same key, different fields): 0

## Request
```json
{
  "category": "status",
  "case_id": "status40_kaifeng_900_1100",
  "replay_inputs": "StatusQueryInputs(status_codes=[40], addr_ids=[100658], include_subunits=False, use_xy_radius=False, xy_narrow=True, year_mode='index', from_year=900, to_year=1100, from_dynasty=-1, to_dynasty=-1, from_dynasty_begin=None, to_dynasty_end=None)"
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
