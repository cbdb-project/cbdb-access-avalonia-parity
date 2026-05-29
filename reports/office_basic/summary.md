# Query `office_basic` parity report

**Verdict**: PASS
**Generated**: 2026-05-29T19:49:46.740185+00:00
**Datadump SHA**: `ed294faed44b36e80169cae8815f83d9d9c5ca3cdb79520c8d058383ad52eb43`

## Stats
- Rows Avalonia: 1
- Rows Access: 1
- Matching: 1
- Only in Avalonia: 0
- Only in Access: 0
- Value mismatches (same key, different fields): 0

## Request
```json
{
  "office_codes": [
    "7"
  ],
  "limit": 200
}
```

See `diff.json` for full per-row detail; `avalonia.json` / `access.json`
hold the raw inputs (gitignored).

For root-cause analysis, edit `hypothesis.md` in this directory.
