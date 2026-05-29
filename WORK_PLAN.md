# Work Plan

## 0. Scope contract (read first)

This repository is a **detection / parity test harness**. Every
contributor — human or agent — operates under the following rule:

- We surface Avalonia ↔ Access disagreements, document them in
  `reports/known_issues.md`, and let the parity gate skip them via
  `Suppress until …` clauses.
- We **do not modify the upstream Avalonia codebase**
  (`cbdb-desktop-app`) or any other repository — neither locally nor
  by pushing branches. Even when a parity test makes a bug obvious,
  the fix belongs to the team that owns that codebase.
- When a parity test fails because of a documented upstream bug, the
  resolution is **always**: re-arm the auto-skip, link the
  `known_issues.md` entry, raise the issue with the upstream team
  separately. Never patch the other repo from here.
- The Python mirror layer in `cbdb_parity/avalonia_*.py` mirrors what
  the upstream C# **actually does** at HEAD — not what we wish it
  would do. If C# clamps `LIMIT` at 10,000, the Python mirror clamps
  at 10,000.

The companion `cbdb-desktop-app` repo on the user's machine is
treated as a read-only reference for SQL extraction. Local edits to
that tree, and pushes to any of its remotes, are explicitly
out-of-scope for any /goal directed at this repository.

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
  - ✅ **1.6 — MariaDB intermediate cache** (`cbdb_parity.mariadb` + `cbdb-parity-import-mariadb` CLI + `cbdb_parity.mariadb_source` event adapter; sqlite_builder + mdb_builder `source=mariadb` default; build_all orchestrator calls `ensure_imported` first). Real-world: Datadump → MariaDB 226 s, MariaDB → SQLite 130 s (3.1× faster than the prior Datadump-direct path). Codex iterated v1..v9 of 1.6a; the per-section gate on 1.6b/c is queued behind the codex rate-limit reset. See §4d for the shape this implements.

- **Phase 2 — Query coverage matrix**
  - ✅ `coverage/avalonia_queries.yaml` (29 methods / 9 services) + `coverage/access_queries.yaml` (43 queries / 11 forms) + `coverage/matrix.md` (16 directly-paired + 4 shape-mismatched + 4 access-only)

- **Phase 3 (1–2 weeks)** — differential harness skeleton + first 3 paired queries (Entry / Office / Status — revised starter set, see §6).
  - ✅ 3a (revised — no .NET test host, since the user's machine has only the .NET runtime, not the SDK): `cbdb_parity.avalonia_query_sql` (raw-string SQL extractor from `Sqlite*QueryService.cs`) + `cbdb_parity.avalonia_query` (Python re-execution of the extracted SQL via `sqlite3`; produces bit-identical rows because both Microsoft.Data.Sqlite and Python's sqlite3 wrap the same engine). `EntryQueryRequest` mirror + `entry_query()` verified end-to-end against the real .build/cbdb.sqlite. **Codex round pending.**
  - ✅ 3b: `cbdb_parity.diff_report` (DiffStats / DiffResult / `diff_rows` with composite-key + compare-fields subset + `write_report` producing the WORK_PLAN §6/§7 file tree with hypothesis.md preserved across re-runs) + `cbdb_parity.access_query` (cbdb_replay bridge: sys.path injection for `$ACCESS_TESTS_REPO/tests`, EntryQueryRequest → EntryQueryInputs mapper, row projection to the 9-field common cross-section). **Codex round pending.**
  - ✅ 3c entry pair smoke test: `tests/test_phase3c_entry_pair.py` — runs both backends, diffs by `(person_id, sequence)` on the common fields, writes the report tree, asserts diff.stats.matches. Skips cleanly when prereqs (mdb, manifest same-SHA, pyodbc, cbdb_replay) aren't met. **Will execute end-to-end once Phase 1.3b's bg build finishes AND `cbdb-parity-build-all` is run to anchor both products to the same SHA.**
  - ✅ 3d (Office pair): `cbdb_parity.avalonia_office_query` + `cbdb_parity.access_office_query` + `tests/test_phase3d_office_pair.py`. Field naming aligns with `Cbdb.App.Core.OfficeQueryRecord` snake-case property names; the 57/64 reader swap (SQL columns vs constructor positions) is mirrored in `_sql_row_to_record_row`. Access bridge rejects request branches `cbdb_replay/lookatoffice` cannot faithfully replay (person_keyword / dynasty_ids / place ids when set / empty office_codes) so the parity report doesn't blame Avalonia for mismatches the bridge silently caused. Codex iterated v1..v7 clean.
  - ✅ 3e (Status pair): `cbdb_parity.avalonia_status_query` + `cbdb_parity.access_status_query` + `tests/test_phase3e_status_pair.py`. Same shape as 3d (positional record-order, unsupported-branch rejection, post-fetch label sort, strict-pipeline path-match gate). 36-field record; no positional swap (the C# reader's column indices match SELECT order directly). Codex queued behind rate-limit reset.

- **Phase 4 (complete)** — query-by-query coverage expansion. Final state: **17 paired tests landed end-to-end (387 passed, 2 documented-upstream-skip)**.
  - ✅ **Tier 1 strict-same-shape** (Phase 3): entry / office / status — `tests/test_phase3{c,d,e}_*_pair.py`.
  - ✅ **Tier 1 shape-negotiated** (Phase 4):
    - **BIOG basic** — `tests/test_phase4_biog_basic_pair.py` (SearchAsync no-keyword branch). 50/50 matching at limit=50.
    - **associations cross-person** — resolved into Tier 2 per-person `tests/test_phase4_associations_pair.py` (660/660 matching with text_title in diff key).
    - **kinship recursive** — direct-branch resolved into Tier 2 `tests/test_phase4_kinships_pair.py` (25/25). The `expandNetwork=true` graph traversal is queued in known_issues.md (`kinship_expanded_network`) — port of `KinshipTraversalState`+`ReduceKinship` is pure post-processing on top of the already-verified SQL.
    - **GroupData** — closed as no-pair (genuinely misaligned shapes); known_issues.md entry `group_data_demographics`.
  - ✅ **Tier 2 per-person PersonBrowser accessors** — 13/13:
    - altnames, entries, addresses, writings, statuses, possessions, events, kinships, associations, sources, institutions, detail (PASS).
    - postings auto-skips on the documented upstream `pto.c_appt_type_code` schema bug (same bug as office_basic); same single upstream fix re-arms both.
  - ✅ **Access-only categories** (Texts / Networks / AssociationPairs / Place): documented as Avalonia gaps in `reports/known_issues.md` under `avalonia_gap`. Nothing to compare until Avalonia implements the corresponding services in `cbdb-desktop-app`.
  - Established Tier 2 implementation pattern (codified across 13 accessors):
    1. extract C# SQL via `find_sql_block(cs_path, discriminator)` where the discriminator is a token unique to that block (often a raw alias like `bad.c_sequence` or table-qualified column);
    2. splice raw ID columns into the SELECT for stable diff-keying (anchor: a unique substring just before `FROM`);
    3. hand-mirror the Access SQL with parenthesised chained LEFT JOINs (N joins → N−1 opening parens before the base table) and SQLite→Access expression rewrites (`||`→`&`, `CASE`→`IIf`, `LIMIT/OFFSET`→`TOP n` + Python slice, `WITH`→inline subquery);
    4. apply `JoinDisplay` post-processing identically on both sides;
    5. coerce bool columns via `_to_bool_or_none` for `c_*_intercalary`/`c_natal`/etc.;
    6. choose a diff key that's unique-per-person (sometimes requires the natural key tail — e.g. ASSOC_DATA needs `c_text_title` because multiple texts can document the same logical association).
  - Infrastructure helpers added during Phase 4:
    - `cbdb_parity.avalonia_query_sql.extract_sql_blocks` now also extracts non-interpolated `@"..."` C# verbatim strings (used throughout `SqlitePersonBrowserService.cs`), in source order, while deliberately excluding interpolated `$@"..."` / `@$"..."` whose `{placeholder}` substitutions aren't valid raw SQL.
    - `cbdb_parity.access_query._replay_row_to_avalonia_shape` (and the office/status variants) coerce pandas-NaN → None so SQL-NULL columns don't surface as 198/200 spurious mismatches.
    - Shared `_join_display` / `_to_bool_or_none` helpers in `cbdb_parity.avalonia_altnames` and `cbdb_parity.avalonia_addresses` are reused across all Tier 2 bridges to keep post-processing identical.

- **Phase 5 (next, planned 2026-05-29 onwards)** — pivot to direct
  .NET Avalonia execution via a new `Cbdb.App.ParityHost` console.
  Reason: Phase 3-4 used the "extract SQL + Python re-execute" path
  because the user's machine only had .NET runtime, no SDK. The
  user's followup goal installs SDK 8.0.421 (verified
  `dotnet --list-sdks` shows it; `dotnet build Cbdb.App.Data.csproj`
  succeeds clean against the existing tree). With SDK available we
  can stop mirroring C# semantics in Python and instead invoke the
  real C# services. Concretely:

  - **5a — ParityHost console (lives IN THIS REPO, not upstream)**:
    - Per §0 scope contract: the console project lives in
      `cbdb-access-avalonia-parity/parity_host/Cbdb.App.ParityHost/`
      (`dotnet new console -f net8.0`), NOT in `cbdb-desktop-app`.
      We do not commit code to upstream Avalonia — the harness
      references it.
    - References `Cbdb.App.Core` and `Cbdb.App.Data` via
      `<ProjectReference Include="$(AvaloniaRepo)/Cbdb.App.Core/Cbdb.App.Core.csproj" />`
      style — the `AvaloniaRepo` MSBuild property is read from the
      **process environment variable** of the same name. MSBuild
      doesn't parse `.env` natively, so the contract is:
        - Python harness (the normal caller): always loads `.env` via
          `python-dotenv` before any subprocess call, so
          `os.environ["AVALONIA_REPO"]` is set before invoking
          `dotnet run` or the published binary. Both `Popen` and
          `subprocess.run` inherit the parent env by default.
        - Manual `dotnet build` (rare — initial scaffold,
          contributor IDE setup): contributor sets `AVALONIA_REPO`
          themselves before running, e.g. `$env:AVALONIA_REPO = ...`
          in PowerShell. A small `parity_host/README.md` documents
          this one-liner.
        - `Directory.Build.props` at the project root just exposes
          the env var as an MSBuild property, e.g.
          `<AvaloniaRepo>$(AVALONIA_REPO)</AvaloniaRepo>` inside a
          `<PropertyGroup>`. No parsing of `.env`.
    - When the upstream tree moves (a `git pull` in
      `$AVALONIA_REPO`), this console picks up the changes on next
      `dotnet build`. No commits to upstream needed; no .csproj
      edits in `cbdb-desktop-app`.
    - CLI: `cbdb-parity-host <service> <sqlite-path> <request-json>`
      → reads JSON request from stdin, instantiates the service, runs
      `QueryAsync` / `Get*Async`, JSON-serialises the result to stdout.
      Errors → JSON `{error: ..., stack: ...}` on stderr.
    - One executable handles 6 of the 7 Avalonia query surfaces
      (Entry, Office, Status, PersonBrowser's record-returning methods,
      GroupPeople, PlaceLookup, DynastyLookup). **Special case**:
      `IPersonBrowserService.GetRelatedItemsAsync` returns a
      `DataTable` rather than a record/list DTO, so it needs a custom
      JSON projection (column metadata + row arrays) — handled by a
      dedicated dispatch branch, not the generic record-list serialiser.
    - **Encoding contract** (load-bearing on Windows): both sides
      MUST agree on UTF-8 for stdin/stdout/stderr. C# side sets
      `Console.OutputEncoding = Console.InputEncoding = new UTF8Encoding(false)`
      at host startup. Python side uses `subprocess.Popen(...,
      stdin=PIPE, stdout=PIPE, stderr=PIPE, text=False)` and
      .read()/.write() raw bytes that we decode/encode as UTF-8
      explicitly. Without this, the many Chinese fields in CBDB rows
      (c_name_chn, c_title_chn, etc.) mojibake under the default
      Windows code page and parity diffs become meaningless.

  - **5b — Python harness switchover**: each of the existing
    `cbdb_parity/avalonia_*.py` modules currently does
    `extract_sql_blocks(cs_path) → sqlite3.connect(...).execute(...)`.
    Adds a NEW execution mode `via_parity_host(...)` that
    subprocess-invokes the ParityHost binary with the JSON-serialised
    request and parses the JSON response. Original SQL-extract path
    kept as `via_sql_extract(...)` for diffing (the two paths SHOULD
    produce identical row sets — any divergence is a Python-mirror
    bug we've been failing to catch).

  - **5c — phase out the Python mirror layer** once the
    via-ParityHost path is proven equivalent: drop the SQL extractor +
    its associated rewrites (`_csharp_params_to_sqlite`,
    `_join_display`, `_to_bool_or_none`, the AddrField casefold, the
    NULL sequence → 0 coercion, etc.). All of these have been bug
    sources (codex caught ~10 P1/P2 issues across the 18 review
    rounds purely from Python-mirror drift). The replay scan +
    Tier 1/2 pair tests stay; only their backend swaps. **NB**: the
    full dependency chain that the 5d kinship cross-check needs MUST
    be retained until 5d finishes, NOT just
    `cbdb_parity/avalonia_kinships_expanded.py` itself.
    Concretely, `avalonia_kinships_expanded.py` imports
    `_load_get_kinships_sql` from `cbdb_parity/avalonia_kinships.py`
    (which in turn uses `extract_sql_blocks` from
    `cbdb_parity/avalonia_query_sql.py`) and `_join_display` from
    `cbdb_parity/avalonia_altnames.py`. Removing any of those before
    5d finishes breaks the comparison target at import time. The
    safe 5c ordering: defer deletion of the entire
    `avalonia_{query_sql, altnames, kinships, kinships_expanded}.py`
    cluster until 5d signs off, then delete all four in one commit.

  - **5d — kinship expandNetwork=true cross-check** (must precede
    5c's deletion of the kinships_expanded.py module): the BFS state
    machine in `cbdb_parity/avalonia_kinships_expanded.py` is the
    biggest manual port. Run both ports against the same set of
    person_ids and require byte-identical output before deprecating
    the Python copy. If 5d uncovers divergence, 5c on the kinships
    module is blocked until reconciled.

  - **5e — coverage extension (✅ landed 2026-05-29)**: with the C#
    directly callable, the lookup/group surfaces already in
    cbdb-desktop-app (DynastyLookup, PlaceLookup, GroupPeople) are
    now exposed through the ParityHost and wrapped in Python
    (`cbdb_parity/avalonia_lookups.py`) with smoke tests in
    `tests/test_phase5e_lookups_smoke.py`. The other documented
    gaps (Texts / Networks / AssociationPairs) are NOT in upstream
    yet, so per the §0 scope contract they remain out of scope
    until an upstream commit lands them — at which point this repo
    only needs to add the host dispatch + Python wrapper + smoke
    test. The original 5e plan listed three integration costs per
    new service:
      1. land the upstream service in `cbdb-desktop-app` (record +
         interface + SqliteXxxService.cs, per the existing pattern);
      2. add a dispatch branch in `Cbdb.App.ParityHost` that knows
         how to deserialise the request JSON and serialise the
         response;
      3. add the Python-side wrapper in `cbdb_parity/avalonia_*.py`
         (request dataclass + subprocess invocation + row
         normalisation) and Access bridge (cbdb_replay mapping) and
         pair test.
    What 5e DOES win: the C# implementation runs literally, so there's
    no more "Python mirror drifts from C#" failure mode. But every
    new query still costs 3 distinct integrations, not zero.

  - **Caveats / open questions**:
    - **Startup cost**: `dotnet run` cold-start is ~500ms-1s. For ~400
      tests × multiple sub-queries each this matters. Mitigation:
      ParityHost stays alive as a daemon, Python harness streams
      NDJSON over stdin/stdout (UTF-8 byte pipes — see 5a encoding
      contract). One-shot CLI mode kept for debugging.
    - **UTF-8 pipe contract** (load-bearing): see 5a. NEVER let the
      pipe inherit the default Windows code page (cp936 / cp1252
      etc.) — CBDB rows are predominantly CJK.
    - **`Cbdb.App.Data` references Microsoft.Data.Sqlite**: ParityHost
      will too. No additional native deps. `Cbdb.App.Data` is a
      library project with no DI container of its own; ParityHost
      `new`s up `SqliteXxxService` instances directly (no
      `IServiceProvider` needed).
    - **Test repro**: ParityHost output should be deterministic for a
      fixed (sqlite_path, request) pair. CI / parity reports keep
      the same SHA-anchoring contract.
    - **Backwards-compat during transition**: don't delete the SQL
      extractor (or the `avalonia_kinships_expanded.py` BFS port,
      explicitly) until 5d's byte-for-byte cross-check passes; the
      existing 400-test green state is the floor.

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
