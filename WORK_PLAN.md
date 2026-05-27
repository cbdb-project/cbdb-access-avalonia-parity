# Work Plan

## 1. Objective
Build an independent comparison harness in `cbdb-access-avalonia-parity` that, for **every query feature** in the CBDB Avalonia desktop app (`cbdb-desktop-app`), runs the equivalent query against a CBDB Access stack and diffs the results. The harness must (a) reuse the test-design ideas from `cbdb-user-mdb-tests`, (b) feed both stacks from the **same** Datadump so any difference is logic, not data, and (c) report each Access ↔ Avalonia disagreement with a root cause.

Note: both `cbdb-user-mdb-tests` and `cbdb-desktop-app` already contain partial sketches of this comparison work (e.g. `cbdb-user-mdb-tests/data/cbdb_online_sqlite/`, `cbdb-user-mdb-tests/.external/cbdb-desktop-app/`). The decision is to do this in its own repo rather than continue those sketches.

## 2. Inputs (sourced via `.env`, never copied into the repo)

| Key | What it points to | Example placeholder |
|---|---|---|
| `DATADUMP_DIR` | Folder of `cbdb_data_YYYYMMDD.tar.gz` archives (auto-pick latest). | `D:\path\to\Datadump` |
| `CBDB_USER_MDB` | Fixed `CBDB_BJ_User.mdb` (Access UI front-end). | `C:\path\to\CBDB_BJ_User.mdb` |
| `ACCESS_TESTS_REPO` | Local clone of `cbdb-user-mdb-tests`. | `C:\path\to\cbdb-user-mdb-tests` |
| `AVALONIA_REPO` | Local clone of `cbdb-desktop-app`. | `C:\path\to\cbdb-desktop-app` |
| `ONLINE_SERVER_REPO` | Local clone of `cbdb-online-main-server`. | `C:\path\to\cbdb-online-main-server` |
| `MYSQL2ACCESS_DIR` | Local working folder for Datadump → Access conversion (not a git repo). | `C:\path\to\mysql2access` |
| `ACCESS_MYSQL_TRANSFER_REPO` | Local clone of `accessAndMySQLTransfer`. | `C:\path\to\accessAndMySQLTransfer` |
| `BUILD_OUTPUT_DIR` | Local scratch dir for generated `cbdb_data.mdb` and `cbdb.sqlite` (gitignored). | `.build` or any absolute path |

`.env.sample` is committed with these keys and placeholder values. `.env` (real local paths) is gitignored — never commit real machine paths into the public repo.

## 3. Repository setup
1. `git init`, set default branch `main`, add `.gitignore` (Python, .NET, PHP, .env, scratch dirs, large DBs).
2. Add `README.md`, `LICENSE` (**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International — CC BY-NC-SA 4.0**), `AGENTS.md`/`CLAUDE.md` conventions.
3. Create empty repo `cbdb-access-avalonia-parity` under `https://github.com/orgs/cbdb-project/` (public) via the local `gh` CLI (already authenticated). Push `main`.
4. Add a "pull-then-use" helper. **Every parity run** (and every build-pipeline run) refreshes the following four repos first via `git -C <repo> pull --ff-only`:
   - `ACCESS_TESTS_REPO` → `cbdb-user-mdb-tests`
   - `AVALONIA_REPO` → `cbdb-desktop-app`
   - `ONLINE_SERVER_REPO` → `cbdb-online-main-server`
   - `ACCESS_MYSQL_TRANSFER_REPO` → `accessAndMySQLTransfer`

   `MYSQL2ACCESS_DIR` and the folder containing `CBDB_USER_MDB` are **not** git repos and are skipped by the refresher. Implement as a single Python utility `scripts/refresh_external_repos.py` that every harness entrypoint calls before doing anything else; fail loudly if any pull is non-fast-forward.

## 4. Build pipeline (Datadump → two databases)

### 4a. Datadump → Access "data" mdb
- Pick newest archive in `DATADUMP_DIR`, extract to scratch.
- Port the MySQL→Access flow from `$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb` + `$MYSQL2ACCESS_DIR/mysql2access.ipynb` into a reproducible script `scripts/build_access_data.py` (no notebook). Reuse the table list / field list / primary-key spreadsheets that live in `$MYSQL2ACCESS_DIR`.
- Output `BUILD_OUTPUT_DIR\cbdb_data.mdb`. Pair it with the fixed `CBDB_BJ_User.mdb` to form a working Access stack.

### 4b. Datadump → Avalonia SQLite

**Primary route — pure Python port.** The Laravel command of record is `cbdb-online-main-server/app/Console/Commands/ExportMysqlToSqlite.php` (signature `db:export-to-sqlite`). It expects a live MySQL connection, *not* a tar.gz. The plan is to port the *logic* of that command (plus the auxiliary index/address rebuilders it relies on — `RebuildIndexAddress.php`, `RebuildIndexYear.php`, `RebuildNameSearchIndex.php`, `RegenerateAddresses.php`, `ImportTradSimpMap.php`) directly to Python, so the pipeline becomes:

&nbsp;&nbsp;&nbsp;&nbsp;`tar.gz` → parse MySQL dump in Python → write `cbdb.sqlite` directly.

This avoids spinning up MySQL on every run and keeps the pipeline self-contained. Output: `BUILD_OUTPUT_DIR\cbdb.sqlite`. Validate against the row counts of the existing reference `cbdb-user-mdb-tests/data/cbdb_online_sqlite/cbdb_20260328.sqlite3` (older but useful as a structural sanity check).

**Fallback route — Docker MySQL.** If a faithful Python port turns out to be impractical (e.g. an artisan command relies on a non-trivial MySQL-only feature like collation-sensitive name search indexes that doesn't translate cleanly), fall back to: `tar.gz` → restore into a throwaway `mysql:8` Docker container → run the real `php artisan db:export-to-sqlite` against it → copy out `cbdb.sqlite`. Wrap as `scripts/build_sqlite_docker.py` and only invoke it if the Python route fails or diverges.

**Decision point.** Phase 1 must pick one of these *and stick with it* before Phase 2 — running both forever is not the goal. Verify row counts of key tables (BIOG_MAIN, ADDR_CODES, OFFICE_CODES, …) match the Access build to prove "same data, two formats" before any query diffing.

### 4c. One-shot orchestrator
`scripts/build_all.py` runs 4a + 4b from a single Datadump archive and records the dump filename + SHA in `build_manifest.json` so every report ties back to a specific data version.

## 5. Query coverage inventory
1. Crawl `cbdb-desktop-app/Cbdb.App.Avalonia` + `Cbdb.App.Core` to enumerate every implemented query/view (people search, office, kinship, association, place, etc.). Output `coverage/avalonia_queries.yaml`: `{id, name, params, status: implemented|missing}`.
2. Crawl `cbdb-user-mdb-tests` (especially `test_vba_*.py`, `cbdb_driver/`, `cbdb_replay/`) to enumerate every Access query the existing framework can drive. Output `coverage/access_queries.yaml`.
3. Produce `coverage/matrix.md` joining the two: Avalonia feature ↔ matching Access query ↔ status (paired / Avalonia-only / Access-only / missing-on-both).

## 6. Differential harness
- Pytest-based, modeled on the VBA differential pattern in `cbdb-user-mdb-tests/tests/test_vba_differential.py` and `cbdb_driver`/`cbdb_replay`.
- For each paired query in `matrix.md`:
  1. **Access side** — drive the real Access UI via the existing `cbdb_driver` (pywinauto) **or** issue the equivalent SQL against the generated `cbdb_data.mdb` via pyodbc, depending on whether the query is UI-only or SQL-expressible.
  2. **Avalonia side** — call the same query path. Two options to evaluate in a spike: (a) UI-drive Avalonia via Appium/FlaUI, (b) instantiate `Cbdb.App.Core` query services directly from a small .NET test host that returns JSON. (b) is faster and more stable; prefer it unless we need to validate UI binding.
  3. Normalize both result sets to a canonical record shape, sort, diff.
  4. Emit a per-query report under `reports/<query_id>/{access.json, avalonia.json, diff.json, summary.md}`.
- Shared parametrization fixtures (person IDs, office IDs, kinship roots) live in `tests/fixtures/` so both sides hit the same inputs.

## 7. Reporting & root-cause loop
- Top-level `reports/SUMMARY.md` aggregates: total queries, paired, passing, failing, Avalonia-missing.
- For each failing query, capture: input, two outputs, diff, and a `hypothesis.md` slot for the human-or-LLM-written root cause (schema mismatch, missing join, code-table drift, etc.).
- `reports/known_issues.md` tracks confirmed Avalonia gaps so they don't re-trigger noise on every run.

## 8. Phasing
- **Phase 0 (1–2 days)** — repo init, `.env`/`.env.sample`, `.gitignore`, push to `cbdb-project` org, cross-repo `git pull` helper.
- **Phase 1 (3–5 days)** — Datadump→Access script (port from `mysql2access`); Datadump→SQLite script (port from `cbdb-online-main-server` artisan); row-count parity check.
- **Phase 2 (2–3 days)** — coverage inventory + matrix.
- **Phase 3 (1–2 weeks)** — differential harness skeleton + first 3 paired queries end-to-end (recommend: BIOG basic, office query, kinship), proving both drive paths.
- **Phase 4 (ongoing)** — expand coverage query-by-query; each new query lands with its diff report and (if mismatched) a root-cause note.

## 9. Open questions

**Resolved during planning:**
- ✅ Artisan command identified: `db:export-to-sqlite` in `app/Console/Commands/ExportMysqlToSqlite.php`. Auxiliary index/address rebuilders also identified (see §4b).
- ✅ Avalonia headless: `Cbdb.App.Core` is interface-only (`IEntryQueryService`, `IOfficeQueryService`, `IStatusQueryService`, `IGroupPeopleService`, `IPersonBrowserService`, `IPlaceLookupService`, `IDynastyLookupService`); `Cbdb.App.Data` holds the SQLite-backed implementations. A .NET test host that instantiates the `Sqlite*Service` classes directly is structurally feasible. Phase 3 will validate with one query.
- ✅ Repo name: `cbdb-access-avalonia-parity`. Will be created under `cbdb-project` org via local `gh`.

**Decisions made during planning:**
- ✅ **Caching**: cache both the generated Access `cbdb_data.mdb` and the Avalonia `cbdb.sqlite` by Datadump filename + SHA. Re-use the cached artifact unless the Datadump SHA changes or the user passes `--rebuild`.
- ✅ **Python → Docker switch criterion**: the threshold is **not** measured in working days. Instead: during Phase 1 4b implementation, the user will invoke Codex review on the Python-port code. If **three consecutive Codex review rounds still flag serious issues** with the Python port, switch the offending command (or the entire 4b pipeline) to the Docker MySQL fallback. Codex review is **user-triggered**, not automatic.
- ✅ **LICENSE**: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0).
