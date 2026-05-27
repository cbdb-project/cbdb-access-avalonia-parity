# Work Plan

## 1. Objective
Build an independent comparison harness in `cbdb-access-avalonia-parity` that, for **every query feature** in the CBDB Avalonia desktop app (`cbdb-desktop-app`), runs the equivalent query against a CBDB Access stack and diffs the results. The harness must (a) reuse the test-design ideas from `cbdb-user-mdb-tests`, (b) feed both stacks from the **same** Datadump so any difference is logic, not data, and (c) report each Access ↔ Avalonia disagreement with a root cause.

Note: both `cbdb-user-mdb-tests` and `cbdb-desktop-app` already contain partial sketches of this comparison work (e.g. `cbdb-user-mdb-tests/data/cbdb_online_sqlite/`, `cbdb-user-mdb-tests/.external/cbdb-desktop-app/`). The decision is to do this in its own repo rather than continue those sketches.

**Strict-pipeline rule (no substitutions).** The build pipeline goes
`Datadump → cbdb_data.mdb` AND `Datadump → cbdb.sqlite` in order, both
from the *same* Datadump archive. Phase 3's differential harness MUST
consume those generated artefacts. Pre-existing mdb files on the user's
machine (e.g. `CBDB_BJ_20260430/CBDB_20260430_DATA.mdb`) are NOT
acceptable substitutes — they were built from a different Datadump and
would silently inject data-version drift into every parity comparison,
which is the exact failure mode this repo is supposed to prevent.
Phase 1.3b (the Datadump → mdb writer) is on the critical path; nothing
downstream may shortcut around it.

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
| `MARIADB_HOST` | MariaDB host for the Phase 1.6 intermediate cache (§4d). | `localhost` |
| `MARIADB_PORT` | MariaDB port. | `3306` |
| `MARIADB_USER` | MariaDB user with `CREATE / DROP / INSERT` on `MARIADB_DATABASE`. | `root` |
| `MARIADB_PASSWORD` | MariaDB password. Required; fail-loud if absent. | `notSecureChangeMe` |
| `MARIADB_DATABASE` | DB name the Datadump is imported into. | `cbdb_data` |
| `MARIADB_CONTAINER_NAME` | Informational; used only when `MARIADB_AUTO_LAUNCH=1`. | `cbdb-parity-mariadb` |
| `MARIADB_FORCE_REIMPORT` | `1` = drop and reimport even when SHA matches; `0` = trust the in-DB provenance row. | `0` |
| `MARIADB_AUTO_LAUNCH` | `1` = `docker start <CONTAINER_NAME>` if found stopped; `0` = require the user to bring the container up. | `0` |

`.env.sample` is committed with these keys and placeholder values. `.env` (real local paths and secrets) is gitignored — never commit real machine paths or passwords into the public repo.

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

Both sub-pipelines (4a, 4b) MUST consume the SAME `cbdb_data_YYYYMMDD.tar.gz` archive; the `build_all` orchestrator (4c) ties them together. See §1 strict-pipeline rule: pre-existing mdb files are NOT acceptable substitutes for the 4a output.

### 4a. Datadump → Access `cbdb_data.mdb`

Split into two sub-phases:

**Phase 1.3a — `cbdb_parity.access_schema` (✅ done)**
- Loads `$ACCESS_MYSQL_TRANSFER_REPO/TablesFields.xlsx` (85 tables / 669 columns) into typed dataclasses: `AccessSchema`, `AccessTable`, `AccessColumn(name, data_format, nullable, is_primary_key, foreign_key_*, dump_*)`.
- Used by 1.3b for type overrides and FK references; useful on its own for schema validation.

**Phase 1.3b — `cbdb_parity.mdb_builder` (next)**

Python end-to-end, no Docker MySQL, no manual artifacts. Concrete plan:

1. **Bootstrap empty mdb** via `pypyodbc.win_create_mdb(target)` — empirically verified to produce a working 172 KB empty mdb in one call on Windows + Microsoft Access Driver. No ADOX, no `win32com`, no template file. `pypyodbc` is added as a new `[access]` extra dependency; we only use that one function — all other mdb operations (connect / execute / cursor.tables) continue to use `pyodbc` (matching the proven shape of `$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb`).
2. **Consume the dump stream** via the existing `cbdb_parity.mysqldump.parse_dump()` (Phase 1.1) — no MySQL server needed, no Docker. Reuse the streaming parser we already have, same as `cbdb_parity.sqlite_builder` does.
3. **MySQL → Access type translator** in a new `cbdb_parity.access_types.mysql_type_to_access()` mirroring the shape of `mysql_type_to_sqlite`. Starting map (from `mysql2access.ipynb` + the README at `$ACCESS_MYSQL_TRANSFER_REPO/README.md`):
   - `int / smallint / mediumint / bigint(N)` → `INTEGER` (Long)
   - `double / float` → `DOUBLE`
   - `decimal(p,s)` → `DOUBLE` (Access lacks NUMERIC — verify with CBDB rows)
   - `varchar(N)` → `VARCHAR(255)` capped; **mind the utf8mb4 → utf8 caveat: drop to `VARCHAR(191)`** if INSERT errors come back complaining about row size, per README §1
   - `char(N)` → `VARCHAR(N)` (Access has no fixed-length CHAR)
   - `text / mediumtext / longtext / tinytext` → `LONGTEXT` (Memo)
   - `date / datetime / timestamp / time` → `DATETIME`
   - `bit / tinyint(1)` → `SMALLINT` (per README §3 — boolean flips bug avoided)
   - `varbinary / binary` → `LONGBINARY`
4. **CREATE TABLE / INSERT** via `pyodbc`. Skip `CBDB__*` internal tables by default (same default as `sqlite_builder`); skip the `SKIP_TABLES` ops/audit list from `mysql2access.ipynb` cell 3 (oauth_*, migrations, users, operations, password_resets, …). Batch INSERTs via `cursor.executemany(...)` — the notebook uses row-by-row `execute`, which is slow for 5M+ rows; we use the same `_BATCH_ROWS=1000` constant `sqlite_builder` does.
5. **Special-value normalisation** from notebook cell 2: `b'\x00'`→0, `b'\x01'`→1, `'0000-00-00 00:00:00'`→None.
6. **Output `BUILD_OUTPUT_DIR\cbdb_data.mdb`**. Pair with fixed `CBDB_USER_MDB` to form the working Access stack.

CLI: `scripts/build_mdb.py` + `[project.scripts] cbdb-parity-build-mdb`. Orchestrator integration: `build_all.py` gains a `_build_mdb_if_needed` call alongside the existing `_build_sqlite_if_needed`, sharing the same SHA-cache invariants and per-product manifest slot.

**Why not Docker MySQL.** Considered as fallback but ruled out: the empty-mdb bootstrap (the only step that initially looked hard) is solved by `pypyodbc.win_create_mdb`; the dump-parsing step is solved by the already-built `cbdb_parity.mysqldump`. Going through Docker would re-introduce MySQL as a dependency and produce a longer pipeline (tar.gz → docker mysql:8 → notebook code → mdb) than the direct one (tar.gz → parse → mdb). The Docker route stays available as an escape hatch if some CBDB-specific dump shape defeats the type translator, mirroring 4b's policy.

**Codex review gate (same as 4b).** During 1.3b implementation, three consecutive codex review rounds flagging serious issues with the Python port flip the offending step to the Docker fallback. User-triggered, not automatic.

### 4b. Datadump → Avalonia SQLite

**Primary route — pure Python port.** The Laravel command of record is `cbdb-online-main-server/app/Console/Commands/ExportMysqlToSqlite.php` (signature `db:export-to-sqlite`). It expects a live MySQL connection, *not* a tar.gz. The plan is to port the *logic* of that command (plus the auxiliary index/address rebuilders it relies on — `RebuildIndexAddress.php`, `RebuildIndexYear.php`, `RebuildNameSearchIndex.php`, `RegenerateAddresses.php`, `ImportTradSimpMap.php`) directly to Python, so the pipeline becomes:

&nbsp;&nbsp;&nbsp;&nbsp;`tar.gz` → parse MySQL dump in Python → write `cbdb.sqlite` directly.

This avoids spinning up MySQL on every run and keeps the pipeline self-contained. Output: `BUILD_OUTPUT_DIR\cbdb.sqlite`. Validate against the row counts of the existing reference `cbdb-user-mdb-tests/data/cbdb_online_sqlite/cbdb_20260328.sqlite3` (older but useful as a structural sanity check).

**Fallback route — Docker MySQL.** If a faithful Python port turns out to be impractical (e.g. an artisan command relies on a non-trivial MySQL-only feature like collation-sensitive name search indexes that doesn't translate cleanly), fall back to: `tar.gz` → restore into a throwaway `mysql:8` Docker container → run the real `php artisan db:export-to-sqlite` against it → copy out `cbdb.sqlite`. Wrap as `scripts/build_sqlite_docker.py` and only invoke it if the Python route fails or diverges.

**Decision point.** Phase 1 must pick one of these *and stick with it* before Phase 2 — running both forever is not the goal. Verify row counts of key tables (BIOG_MAIN, ADDR_CODES, OFFICE_CODES, …) match the Access build to prove "same data, two formats" before any query diffing.

### 4c. One-shot orchestrator (✅ done — `cbdb_parity.build_all`)
`scripts/build_all.py` + `cbdb-parity-build-all` CLI. Runs 4a + 4b from a single Datadump archive and records the dump filename + SHA in `build_manifest.json` (at workspace root, discovered via `find_dotenv`) so every report ties back to a specific data version. SHA-based caching skips rebuilds when the manifest already records the current SHA AND the recorded product path matches the current target AND the file exists. `--rebuild` forces. Refresh of the four external repos is mandatory and cannot be skipped.

Currently wires only 4b (sqlite). Once 4a Phase 1.3b lands, the orchestrator adds the parallel `_build_mdb_if_needed` call alongside `_build_sqlite_if_needed`; manifest invariants (SHA-anchored sibling preservation, partial-write protection, stale-sibling drop on SHA change) are already in place.

### 4d. MariaDB intermediate cache (⏳ Phase 1.6 — adopted after Phase 1.3b empirics)

The Phase 1.3b real-world build against the 1.4 GB May-27 Datadump revealed two pyodbc/Jet pathologies even with the Python port working as designed:

1. **Jet 2 GB transaction-buffer ceiling** — even when the final mdb would be < 1 GB, a single-transaction bulk load against `Microsoft Access Driver` raised `HY001` once Jet's accumulated work-buffer crossed the .mdb format's 2 GB hard limit. Fixed in `mdb_builder._drain` by committing per-table.
2. **Duplicate values blocking declared PKs** — Jet aborts the whole transaction with `IntegrityError 23000` when a Datadump row violates a PK declared via the TablesFields.xlsx overlay, even though the production Access mdb maintained in `$MYSQL2ACCESS_DIR` does not enforce those PKs either. Fixed by suppressing the overlay's PRIMARY KEY clause.

Both fixes hold the Datadump-direct path together, but the **Datadump → Access** write is fundamentally throttled by the Jet ODBC driver's row-level locking with no bulk-load fast path (cf. SQLite's `synchronous=OFF / journal_mode=OFF`). The historical workflow in `$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb` (and the user's empirical measurement) routes through MariaDB instead — `Datadump → MariaDB` is fast (5–10× the Python parser path), and `MariaDB → Access` via pyodbc reuses the proven ipynb pattern.

**The MariaDB step is a CACHE LAYER, not a replacement for either output.** The two final products are still `cbdb.sqlite` (for the Avalonia side) and `cbdb_data.mdb` (for the Access side). The mdb still flows into `cbdb_replay`-driven pyodbc tests exactly as Phase 3 designs. Phase 1.6 displaces the in-process mysqldump parser as the **default** import step for both builders; the `cbdb_parity.mysqldump`-based path is retained as a fallback for non-Docker hosts and selected via `source='datadump'`.

**Module / config layout (`Phase 1.6`):**

- `.env` keys (new; documented in `.env.sample` and §2 alongside the other inputs):
  - `MARIADB_HOST=localhost`
  - `MARIADB_PORT=3306`
  - `MARIADB_USER=root`
  - `MARIADB_PASSWORD=…`  (required; no default — fail-loud if missing)
  - `MARIADB_DATABASE=cbdb_data`
  - `MARIADB_CONTAINER_NAME=cbdb-parity-mariadb` (informational; we don't auto-launch the container — the user runs `docker compose up` themselves)
  - `MARIADB_FORCE_REIMPORT=0` (1 = drop and reimport even when SHA matches; 0 = trust the in-DB provenance row)
  - `MARIADB_AUTO_LAUNCH=0` (1 = `cbdb_parity.mariadb` will `docker start <CONTAINER_NAME>` if found stopped; 0 = fail with a clear "please start the container" message; default 0 keeps the tool deterministic against shared workstations)

- `cbdb_parity.mariadb`:
  - `connect(cfg) → pymysql.Connection`
  - `ensure_imported(cfg, info: DatadumpInfo)`:
    1. Connect; create `cbdb_data` DB if absent.
    2. Check `_cbdb_parity_provenance(datadump_sha, imported_at)` single-row table for `info.sha256`.
    3. If SHA matches AND `MARIADB_FORCE_REIMPORT=0`: return cached.
    4. Else: `DROP DATABASE IF EXISTS cbdb_data; CREATE DATABASE cbdb_data;`, stream the .tar.gz through `mysql` CLI (`tar -O -xzf … | mysql …`) or pymysql `executescript`, then write the provenance row.

- `sqlite_builder` and `mdb_builder` gain `source={'datadump','mariadb'}` (default `mariadb` once 1.6 lands, with `datadump` retained as fallback for non-Docker hosts):
  - From `mariadb`: `SHOW TABLES` + `SELECT * FROM <t>` per table → existing CREATE/INSERT loop. Both builders share a `_pull_table_rows(conn, table) → (TableSchema, Iterable[Row])` helper so the rest of the code path (skip lists, batching, manifest, per-table commit) stays the same.

- `build_all` orchestrator:
  - First runs `mariadb.ensure_imported(cfg, info)`.
  - Then runs sqlite + mdb sub-builders against the cached MariaDB.
  - If `MARIADB_AUTO_LAUNCH=1` the orchestrator may `docker start` the container; otherwise it surfaces "please start the container" and returns rc=2.

**This is additive to Phase 1.3b, not a replacement** — the strict-pipeline rule still bans using pre-existing user mdb files as substitutes for the generated product. MariaDB import is part of OUR pipeline; it just sits between the Datadump and the two writers.

## 5. Query coverage inventory
1. Crawl `cbdb-desktop-app/Cbdb.App.Avalonia` + `Cbdb.App.Core` to enumerate every implemented query/view (people search, office, kinship, association, place, etc.). Output `coverage/avalonia_queries.yaml`: `{id, name, params, status: implemented|missing}`.
2. Crawl `cbdb-user-mdb-tests` (especially `test_vba_*.py`, `cbdb_driver/`, `cbdb_replay/`) to enumerate every Access query the existing framework can drive. Output `coverage/access_queries.yaml`.
3. Produce `coverage/matrix.md` joining the two: Avalonia feature ↔ matching Access query ↔ status (paired / Avalonia-only / Access-only / missing-on-both).

## 6. Differential harness (Phase 3)
- Pytest-based, modeled on the VBA differential pattern in `cbdb-user-mdb-tests/tests/test_vba_differential.py` and `cbdb_driver`/`cbdb_replay`.
- For each paired query in `coverage/matrix.md`:
  1. **Access side** — drive the real Access UI via the existing `cbdb_driver` (pywinauto) **or** issue the equivalent SQL against the **generated** `cbdb_data.mdb` (Phase 1.3b output) via pyodbc, depending on whether the query is UI-only or SQL-expressible. Per §1 strict-pipeline rule, pre-existing local mdbs are NOT acceptable inputs.
  2. **Avalonia side** — call the same query path. Two options to evaluate in a spike: (a) UI-drive Avalonia via Appium/FlaUI, (b) instantiate `Cbdb.App.Core` query services directly from a small .NET test host that returns JSON. (b) is faster and more stable; prefer it unless we need to validate UI binding.
  3. Normalize both result sets to a canonical record shape, sort, diff.
  4. Emit a per-query report under `reports/<query_id>/{access.json, avalonia.json, diff.json, summary.md}`.
- Shared parametrization fixtures (person IDs, office IDs, kinship roots) live in `tests/fixtures/` so both sides hit the same inputs.

**Starter set (first 3 paired queries — revised from WORK_PLAN's original BIOG/office/kinship after Phase 2 found shape mismatches).** Per `coverage/matrix.md` Tier 1, the three strict-same-shape pairs that can be driven without further shape negotiation:
1. **Entry query** — Avalonia `IEntryQueryService.QueryAsync` vs Access `cbdb_replay/lookatentry` + Form_LookAtEntry CmdQuery
2. **Office query** — Avalonia `IOfficeQueryService.QueryAsync` vs Access `cbdb_replay/lookatoffice` + Form_LookAtOffice CmdQuery
3. **Status query** — Avalonia `IStatusQueryService.QueryAsync` vs Access `cbdb_replay/lookatstatus` + Form_LookAtStatus CmdQuery

BIOG basic, kinship recursive, and associations have shape mismatches that need a Phase 4 narrowing step before they're paired.

## 7. Reporting & root-cause loop
- Top-level `reports/SUMMARY.md` aggregates: total queries, paired, passing, failing, Avalonia-missing.
- For each failing query, capture: input, two outputs, diff, and a `hypothesis.md` slot for the human-or-LLM-written root cause (schema mismatch, missing join, code-table drift, etc.).
- `reports/known_issues.md` tracks confirmed Avalonia gaps so they don't re-trigger noise on every run.

## 8. Phasing & status

- **Phase 0 — repo init**
  - ✅ 0.1 `git init` + LICENSE (CC BY-NC-SA 4.0 canonical text) + README + AGENTS + `.gitignore` + `.env.sample`
  - ✅ 0.2 `cbdb_parity.config` (`.env` loader, strict validation, find_dotenv-based discovery)
  - ✅ 0.3 `cbdb_parity.refresh` + `cbdb-parity-refresh` CLI (refresh gate, mandatory)
  - ✅ 0.4 `gh repo create cbdb-project/cbdb-access-avalonia-parity --public` + initial push

- **Phase 1 — Datadump → two databases**
  - ✅ 1.0 `cbdb_parity.datadump` (newest-by-date-tag, streaming `r|gz`, SHA)
  - ✅ 1.1 `cbdb_parity.mysqldump` (forward-only mysqldump parser, fail-loud)
  - ✅ 1.2 `cbdb_parity.sqlite_builder` + `cbdb-parity-build-sqlite` (Python port of `ExportMysqlToSqlite`; real-world: 94 tables / 5.74M rows / 559 MB in 405 s)
  - ✅ 1.3a `cbdb_parity.access_schema` (TablesFields.xlsx loader)
  - ✅ 1.3b code complete (`cbdb_parity.access_types`, `cbdb_parity.mdb_builder`, `cbdb-parity-build-mdb` CLI, build_all integration). Codex rounds clean through v10 + Phase 3d v7. Two real-world fixes applied after first end-to-end attempt against the May-27 Datadump:
    - Jet 2 GB transaction-buffer hit → **per-table commit** in `_drain`.
    - `IntegrityError 23000` on duplicate PK values → **PRIMARY KEY clause suppressed** in `_create_table_sql` (NOT NULL / DataFormat overlays still applied).
    The Datadump-direct path now completes; the MariaDB cache path (§4d, Phase 1.6) supersedes it once landed.
  - ✅ 1.4 `cbdb_parity.build_all` + `cbdb-parity-build-all` (SHA cache, manifest invariants, partial-write protection, mandatory refresh) — extended in 1.3b to build both products
  - ✅ 1.5 `cbdb_parity.parity_check` (row-count diff between mdb and sqlite)
  - ⏳ **1.6 — MariaDB intermediate cache** (`cbdb_parity.mariadb` + `cbdb-parity-import-mariadb` CLI; .env keys above; sqlite_builder + mdb_builder gain `source=mariadb` default once it lands). Driver: mysql2access.ipynb's measured win for the Datadump → mdb half. See §4d for shape. Becomes the default import step; retains `source='datadump'` (the existing `cbdb_parity.mysqldump`-direct path) as fallback for non-Docker hosts. Both builders still emit the same final products.

- **Phase 2 — Query coverage matrix**
  - ✅ `coverage/avalonia_queries.yaml` (29 methods / 9 services) + `coverage/access_queries.yaml` (43 queries / 11 forms) + `coverage/matrix.md` (16 directly-paired + 4 shape-mismatched + 4 access-only)

- **Phase 3 (1–2 weeks)** — differential harness skeleton + first 3 paired queries (Entry / Office / Status — revised starter set, see §6).
  - ✅ 3a (revised — no .NET test host, since the user's machine has only the .NET runtime, not the SDK): `cbdb_parity.avalonia_query_sql` (raw-string SQL extractor from `Sqlite*QueryService.cs`) + `cbdb_parity.avalonia_query` (Python re-execution of the extracted SQL via `sqlite3`; produces bit-identical rows because both Microsoft.Data.Sqlite and Python's sqlite3 wrap the same engine). `EntryQueryRequest` mirror + `entry_query()` verified end-to-end against the real .build/cbdb.sqlite. **Codex round pending.**
  - ✅ 3b: `cbdb_parity.diff_report` (DiffStats / DiffResult / `diff_rows` with composite-key + compare-fields subset + `write_report` producing the WORK_PLAN §6/§7 file tree with hypothesis.md preserved across re-runs) + `cbdb_parity.access_query` (cbdb_replay bridge: sys.path injection for `$ACCESS_TESTS_REPO/tests`, EntryQueryRequest → EntryQueryInputs mapper, row projection to the 9-field common cross-section). **Codex round pending.**
  - ✅ 3c entry pair smoke test: `tests/test_phase3c_entry_pair.py` — runs both backends, diffs by `(person_id, sequence)` on the common fields, writes the report tree, asserts diff.stats.matches. Skips cleanly when prereqs (mdb, manifest same-SHA, pyodbc, cbdb_replay) aren't met. **Will execute end-to-end once Phase 1.3b's bg build finishes AND `cbdb-parity-build-all` is run to anchor both products to the same SHA.**
  - ⏭ 3d (Office pair) and 3e (Status pair) follow the same pattern as 3c — extend `avalonia_query.py` + `access_query.py` with `office_query`/`office_query_access` and `status_query`/`status_query_access`, mirror smoke-test files.

- **Phase 4 (ongoing)** — expand coverage query-by-query; each new query lands with its diff report and (if mismatched) a root-cause note. Targets: shape-mismatched Tier 1 pairs (BIOG basic / associations / kinship / GroupData) then Access-only categories (Texts / Networks / AssociationPairs / Place) once Avalonia-side gains those features.

## 9. Open questions

**Resolved during planning:**
- ✅ Artisan command identified: `db:export-to-sqlite` in `app/Console/Commands/ExportMysqlToSqlite.php`. Auxiliary index/address rebuilders also identified (see §4b).
- ✅ Avalonia headless: `Cbdb.App.Core` is interface-only (`IEntryQueryService`, `IOfficeQueryService`, `IStatusQueryService`, `IGroupPeopleService`, `IPersonBrowserService`, `IPlaceLookupService`, `IDynastyLookupService`); `Cbdb.App.Data` holds the SQLite-backed implementations. A .NET test host that instantiates the `Sqlite*Service` classes directly is structurally feasible. Phase 3 will validate with one query.
- ✅ Repo name: `cbdb-access-avalonia-parity`. Will be created under `cbdb-project` org via local `gh`.

**Decisions made during planning:**
- ✅ **Caching**: cache both the generated Access `cbdb_data.mdb` and the Avalonia `cbdb.sqlite` by Datadump filename + SHA. Re-use the cached artifact unless the Datadump SHA changes or the user passes `--rebuild`.
- ✅ **Python → Docker switch criterion**: the threshold is **not** measured in working days. Instead, during 4a (1.3b) AND 4b implementation, the user invokes Codex review on the Python-port code. If **three consecutive Codex review rounds still flag serious issues** with the Python port for that step, switch the offending command (or the entire pipeline for that side) to a Docker MySQL fallback. Codex review is **user-triggered**, not automatic.
- ✅ **Codex CLI invocation defaults**: `codex --dangerously-bypass-approvals-and-sandbox -c model=gpt-5.4 -c model_reasoning_effort=medium review --uncommitted --title "..."`. The dangerous-bypass is needed on this Windows machine because the default codex sandbox fails with `spawn setup refresh`; `gpt-5.4` + `medium` is the per-section baseline so iterative rounds stay comparable. See `AGENTS.md` for full rationale and when to deviate (e.g. CI machines, especially subtle invariants).
- ✅ **LICENSE**: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0).
- ✅ **Empty mdb bootstrap (1.3b)**: `pypyodbc.win_create_mdb()` — empirically verified to produce a 172 KB empty mdb in one call. NOT `pyodbc` (rejects non-existent file), NOT ADOX/`win32com` (heavier), NOT a committed template binary (not reproducible). `pypyodbc` becomes a new `[access]` extra dependency, used for that single function only; all other mdb operations stay on `pyodbc`.
- ✅ **MariaDB intermediate cache (Phase 1.6)**: adopted as the default import source for both `sqlite_builder` and `mdb_builder` after the Phase 1.3b real-world build hit two Jet-specific pathologies (2 GB transaction-buffer ceiling, PK-on-duplicates `IntegrityError 23000`). The MariaDB cache is **not** a substitute for the strict-pipeline rule's prohibition on pre-existing user mdbs — it is an internal staging layer that we ourselves populate from the Datadump, gated by an in-DB SHA provenance row. The pre-1.6 `cbdb_parity.mysqldump`-direct path is retained as a fallback (`source='datadump'`) for non-Docker hosts. This decision is **complementary to** — not a substitute for — the earlier "three consecutive codex rounds → Docker MySQL fallback" trigger above, which still governs the Python-port-vs-Docker-MySQL decision **inside the sqlite builder**.
