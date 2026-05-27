# 工作计划

## 1. 目标
在 `cbdb-access-avalonia-parity` 中独立构建一个对比测试框架：对 Avalonia 桌面端（`cbdb-desktop-app`）**每一个**查询功能，都运行一份等价的 Access 查询并 diff 结果。要求：(a) 借鉴 `cbdb-user-mdb-tests` 的测试设计；(b) 两端使用**同一份** Datadump 生成数据，确保差异来自查询逻辑而非数据；(c) 把每个不一致连同根因记录下来。

说明：`cbdb-user-mdb-tests` 和 `cbdb-desktop-app` 都已经存在一些此项工作的**雏形**（如 `cbdb-user-mdb-tests/data/cbdb_online_sqlite/`、`cbdb-user-mdb-tests/.external/cbdb-desktop-app/`），但最终决定**另起独立 repo** 做这件事，而不是延续既有雏形。

**严格流水线规则（不接受替代）。** 构建流水线必须按顺序走完：
`Datadump → cbdb_data.mdb` 与 `Datadump → cbdb.sqlite`，**两端都从同一份 Datadump 归档生成**。Phase 3 的差分框架**必须**消费这两份生成出的产物。**不接受**用本机已有的 mdb 文件（例如 `CBDB_BJ_20260430/CBDB_20260430_DATA.mdb`）作为替代——它们是从不同 Datadump 构建的，会把数据版本漂移悄悄注入到每一次 parity 对比里，而这正是本 repo 要防止的根本失败模式。Phase 1.3b（Datadump → mdb 写入器）位于关键路径上，**下游任何阶段都不允许绕过它走捷径**。

## 2. 输入（写入 `.env`，外部资源不复制进 repo）

| Key | 含义 | 占位示例 |
|---|---|---|
| `DATADUMP_DIR` | `cbdb_data_YYYYMMDD.tar.gz` 所在目录（自动取最新归档）。 | `D:\path\to\Datadump` |
| `CBDB_USER_MDB` | 固定的 `CBDB_BJ_User.mdb`（Access UI 前端）。 | `C:\path\to\CBDB_BJ_User.mdb` |
| `ACCESS_TESTS_REPO` | `cbdb-user-mdb-tests` 本地克隆。 | `C:\path\to\cbdb-user-mdb-tests` |
| `AVALONIA_REPO` | `cbdb-desktop-app` 本地克隆。 | `C:\path\to\cbdb-desktop-app` |
| `ONLINE_SERVER_REPO` | `cbdb-online-main-server` 本地克隆。 | `C:\path\to\cbdb-online-main-server` |
| `MYSQL2ACCESS_DIR` | Datadump → Access 转换工作目录（非 git repo）。 | `C:\path\to\mysql2access` |
| `ACCESS_MYSQL_TRANSFER_REPO` | `accessAndMySQLTransfer` 本地克隆。 | `C:\path\to\accessAndMySQLTransfer` |
| `BUILD_OUTPUT_DIR` | 生成 `cbdb_data.mdb` 与 `cbdb.sqlite` 的本地临时目录（gitignored）。 | `.build` 或任意绝对路径 |

同步提交 `.env.sample`（占位值），`.env`（真实本地路径）加进 `.gitignore` —— 永远不要把真实机器路径提交进公开 repo。

## 3. 仓库初始化
1. `git init` → main 分支 → `.gitignore`（Python、.NET、PHP、.env、临时数据库）。
2. 加 `README.md`、`LICENSE`（**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International，简称 CC BY-NC-SA 4.0**）、`AGENTS.md`/`CLAUDE.md`。
3. 用本地已登录的 `gh` CLI 在 `https://github.com/orgs/cbdb-project/` 下创建 public repo `cbdb-access-avalonia-parity`，推送 main。
4. 写一个统一的 "pull-then-use" 工具。**每次 parity run**（以及每次 build pipeline 运行）开头都对下列四个 repo 做 `git -C <repo> pull --ff-only`：
   - `ACCESS_TESTS_REPO` → `cbdb-user-mdb-tests`
   - `AVALONIA_REPO` → `cbdb-desktop-app`
   - `ONLINE_SERVER_REPO` → `cbdb-online-main-server`
   - `ACCESS_MYSQL_TRANSFER_REPO` → `accessAndMySQLTransfer`

   `MYSQL2ACCESS_DIR` 以及 `CBDB_USER_MDB` 所在的那个文件夹**不是 git repo**，刷新器自动跳过它们。实现为 `scripts/refresh_external_repos.py`，框架所有入口点必须先调用它；任何 non-fast-forward 立即报错。

## 4. 数据构建流水线（Datadump → 两个数据库）

两条子流水线（4a、4b）**必须消费同一份** `cbdb_data_YYYYMMDD.tar.gz` 归档；由 `build_all` 编排器（4c）串起来。遵循 §1 严格流水线规则：**本机已有的 mdb 不允许替代 4a 的输出**。

### 4a. Datadump → Access `cbdb_data.mdb`

拆成两个子阶段：

**Phase 1.3a — `cbdb_parity.access_schema`（✅ 已完成）**
- 加载 `$ACCESS_MYSQL_TRANSFER_REPO/TablesFields.xlsx`（85 表 / 669 列）到强类型 dataclass：`AccessSchema`、`AccessTable`、`AccessColumn(name, data_format, nullable, is_primary_key, foreign_key_*, dump_*)`。
- 给 1.3b 用作类型 override + FK 查询；本身也可用于 schema 校验。

**Phase 1.3b — `cbdb_parity.mdb_builder`（下一个）**

纯 Python 端到端，不起 Docker MySQL，不依赖手工模板。具体方案：

1. **空 mdb 起步** 用 `pypyodbc.win_create_mdb(target)` —— 实测在 Windows + Microsoft Access Driver 下一行调用即生成可用的 172 KB 空 mdb。不需要 ADOX，不需要 `win32com`，不需要在 repo 里 commit 模板文件。`pypyodbc` 加进 `[access]` extra 依赖，**只用这一个函数**；其他所有 mdb 操作（connect / execute / cursor.tables）继续走 `pyodbc`（保持 `$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb` 已验证的形态）。
2. **消费 dump 流** 用现有的 `cbdb_parity.mysqldump.parse_dump()`（Phase 1.1）——不需要 MySQL server，不需要 Docker。复用我们已有的流式解析器，和 `cbdb_parity.sqlite_builder` 一样的玩法。
3. **MySQL → Access 类型翻译器** 新建 `cbdb_parity.access_types.mysql_type_to_access()`，结构镜像 `mysql_type_to_sqlite`。起步映射表（来自 `mysql2access.ipynb` + `$ACCESS_MYSQL_TRANSFER_REPO/README.md` 里的避坑提示）：
   - `int / smallint / mediumint / bigint(N)` → `INTEGER`（Long）
   - `double / float` → `DOUBLE`
   - `decimal(p,s)` → `DOUBLE`（Access 无 NUMERIC——用真实 CBDB 数据验证）
   - `varchar(N)` → 上限 `VARCHAR(255)`；**注意 utf8mb4 → utf8 兼容性**：若 INSERT 报 row-size 超限，降到 `VARCHAR(191)`（README §1）
   - `char(N)` → `VARCHAR(N)`（Access 没有定长 CHAR）
   - `text / mediumtext / longtext / tinytext` → `LONGTEXT`（Memo）
   - `date / datetime / timestamp / time` → `DATETIME`
   - `bit / tinyint(1)` → `SMALLINT`（按 README §3 避免 bool 全变 1 的坑）
   - `varbinary / binary` → `LONGBINARY`
4. **CREATE TABLE / INSERT** 走 `pyodbc`。默认跳过 `CBDB__*` 内部表（和 `sqlite_builder` 默认对齐）；跳过 `mysql2access.ipynb` cell 3 列出的 SKIP_TABLES（oauth_* / migrations / users / operations / password_resets / …）。**批量 INSERT 用 `cursor.executemany(...)`** —— notebook 是逐行 `execute`，5M+ 行表会很慢；我们沿用 `sqlite_builder` 的 `_BATCH_ROWS=1000`。
5. **特殊值规范化** 沿用 notebook cell 2 的逻辑：`b'\x00'`→0、`b'\x01'`→1、`'0000-00-00 00:00:00'`→None。
6. **输出 `BUILD_OUTPUT_DIR\cbdb_data.mdb`**，与固定的 `CBDB_USER_MDB` 组成完整 Access 栈。

CLI：`scripts/build_mdb.py` + `[project.scripts] cbdb-parity-build-mdb`。编排集成：`build_all.py` 增加 `_build_mdb_if_needed`，与现有 `_build_sqlite_if_needed` 并列，共享相同的 SHA 缓存不变式与 per-product manifest 槽。

**为什么不走 Docker MySQL。** 曾考虑作为兜底，但被排除：空 mdb 起步（曾以为最难）已被 `pypyodbc.win_create_mdb` 一行解决；dump 解析已被 `cbdb_parity.mysqldump` 解决。走 Docker 会重新引入 MySQL 依赖，且流水线更长（tar.gz → docker mysql:8 → notebook 代码 → mdb）远长于直链（tar.gz → 解析 → mdb）。Docker 路线**保留为逃生通道**，万一某个 CBDB-specific dump 形态把类型翻译器搞垮——和 4b 的政策一致。

**Codex review gate（和 4b 同规则）。** 1.3b 实施期间，**连续三轮 codex review 仍然指出严重问题**，就把出问题的那一步切到 Docker 兜底。由用户触发，不自动跑。

### 4b. Datadump → Avalonia SQLite

**主路线 —— 纯 Python 端口。** 决定命令是 `cbdb-online-main-server/app/Console/Commands/ExportMysqlToSqlite.php`（signature 为 `db:export-to-sqlite`），但它的输入是**在跑的 MySQL 连接**，不是 tar.gz。计划是把该命令的*逻辑*（以及它依赖的索引/地址重建命令 —— `RebuildIndexAddress.php`、`RebuildIndexYear.php`、`RebuildNameSearchIndex.php`、`RegenerateAddresses.php`、`ImportTradSimpMap.php`）直接 port 到 Python，使流水线变成：

&nbsp;&nbsp;&nbsp;&nbsp;`tar.gz` → Python 解析 MySQL dump → 直接写 `cbdb.sqlite`

这样每次 run 不需要起 MySQL，pipeline 自包含。输出 `BUILD_OUTPUT_DIR\cbdb.sqlite`。用现有的 `cbdb-user-mdb-tests/data/cbdb_online_sqlite/cbdb_20260328.sqlite3`（虽是 3 月底的旧版）做结构层面 sanity check。

**兜底路线 —— Docker MySQL。** 如果纯 Python 端口不现实（比如某条 artisan 命令依赖 MySQL 专属的、不好翻译的特性，如 collation-sensitive 名字检索索引），就退回到：`tar.gz` → 灌进一个一次性的 `mysql:8` Docker 容器 → 在该容器对应的 Laravel 连接上跑真正的 `php artisan db:export-to-sqlite` → 把 `cbdb.sqlite` 拷出来。封装为 `scripts/build_sqlite_docker.py`，仅当 Python 主路线失败或结果不一致时启用。

**决策点。** 阶段 1 必须**二选一并定下来**，再进阶段 2 —— 两条路同时维护不是目标。在跑任何 diff 之前先校验 BIOG_MAIN、ADDR_CODES、OFFICE_CODES 等关键表的行数与 Access 端一致，证明"同数据、两格式"。

### 4c. 单入口编排（✅ 已完成 —— `cbdb_parity.build_all`）
`scripts/build_all.py` + `cbdb-parity-build-all` CLI。从同一份 Datadump 跑 4a + 4b，把使用的 Datadump 文件名与 SHA 写进 `build_manifest.json`（位于 workspace 根，通过 `find_dotenv` 发现），让每份报告都能溯源到具体数据版本。SHA 缓存：当 manifest 已记录当前 SHA 且 product path 匹配当前目标且文件存在时跳过重建，`--rebuild` 强制重建。**外部四仓的 refresh 是强制的，没有 `--skip-refresh` 选项**。

目前只接了 4b（sqlite）。等 4a 的 Phase 1.3b 落地，编排器会增加并行的 `_build_mdb_if_needed`；manifest 不变式（按 SHA 锚定的 sibling 保留、partial-write 保护、SHA 变化时的 stale-sibling 清空）已就位。

## 5. 查询覆盖清单
1. 爬 `cbdb-desktop-app/Cbdb.App.Avalonia` + `Cbdb.App.Core`，列出 Avalonia 当前实现的所有查询/视图（人物查询、官职、亲属、社会关系、地名等），输出 `coverage/avalonia_queries.yaml`：`{id, name, params, status: implemented|missing}`。
2. 爬 `cbdb-user-mdb-tests`（重点 `test_vba_*.py`、`cbdb_driver/`、`cbdb_replay/`），列出现有框架能驱动的所有 Access 查询，输出 `coverage/access_queries.yaml`。
3. 合并为 `coverage/matrix.md`：Avalonia 功能 ↔ 对应 Access 查询 ↔ 状态（已配对 / 仅 Avalonia / 仅 Access / 双缺）。

## 6. 差分测试框架（Phase 3）
- 基于 pytest，沿用 `cbdb-user-mdb-tests/tests/test_vba_differential.py` 与 `cbdb_driver`/`cbdb_replay` 的差分模式。
- `coverage/matrix.md` 中每一对查询：
  1. **Access 端** — 用现有 `cbdb_driver`（pywinauto）驱动真实 Access UI，或对**生成的** `cbdb_data.mdb`（Phase 1.3b 输出）走 pyodbc 直接发 SQL（看查询是否纯 UI）。**按 §1 严格流水线规则，本机已有的 mdb 不允许作为输入**。
  2. **Avalonia 端** — 两种方案先做 spike：(a) Appium/FlaUI 驱动 UI；(b) 写一个小的 .NET 测试宿主直接调用 `Cbdb.App.Core` 的查询服务并返回 JSON。(b) 更快更稳，默认优先用 (b)，除非要校验 UI 绑定本身。
  3. 把两端结果归一化到同一个记录结构，排序后 diff。
  4. 每个查询写 `reports/<query_id>/{access.json, avalonia.json, diff.json, summary.md}`。
- 公共参数夹具（人物 ID、官职 ID、亲属起点等）放 `tests/fixtures/`，两端用同一份输入。

**Starter set（头 3 个配对查询 —— 经 Phase 2 矩阵分析后从原 plan 的 BIOG/office/kinship 调整）。** 按 `coverage/matrix.md` Tier 1，三对**严格 same-shape**、不需要进一步形状协商即可驱动的查询：
1. **Entry 查询** —— Avalonia `IEntryQueryService.QueryAsync` ↔ Access `cbdb_replay/lookatentry` + Form_LookAtEntry CmdQuery
2. **Office 查询** —— Avalonia `IOfficeQueryService.QueryAsync` ↔ Access `cbdb_replay/lookatoffice` + Form_LookAtOffice CmdQuery
3. **Status 查询** —— Avalonia `IStatusQueryService.QueryAsync` ↔ Access `cbdb_replay/lookatstatus` + Form_LookAtStatus CmdQuery

BIOG basic、kinship recursive、associations 有形状不匹配，需要在 Phase 4 做窄化处理后再配对。

## 7. 报告与根因循环
- 顶层 `reports/SUMMARY.md`：总查询数、已配对、通过、失败、Avalonia 缺失。
- 每个失败查询保留：输入、两端输出、diff、`hypothesis.md`（人工或 LLM 写的根因，例如 schema 不一致、缺 join、代码表漂移等）。
- `reports/known_issues.md` 记录已确认的 Avalonia 缺口，避免重复噪声。

## 8. 分阶段与状态

- **阶段 0 — repo 初始化**
  - ✅ 0.1 `git init` + LICENSE（CC BY-NC-SA 4.0 官方文本）+ README + AGENTS + `.gitignore` + `.env.sample`
  - ✅ 0.2 `cbdb_parity.config`（`.env` 加载器、严格校验、基于 find_dotenv 的发现）
  - ✅ 0.3 `cbdb_parity.refresh` + `cbdb-parity-refresh` CLI（强制 refresh gate）
  - ✅ 0.4 `gh repo create cbdb-project/cbdb-access-avalonia-parity --public` + 初始 push

- **阶段 1 — Datadump → 两个数据库**
  - ✅ 1.0 `cbdb_parity.datadump`（按 date tag 取最新、`r|gz` 流式、SHA）
  - ✅ 1.1 `cbdb_parity.mysqldump`（forward-only mysqldump 解析器，全链路 fail-loud）
  - ✅ 1.2 `cbdb_parity.sqlite_builder` + `cbdb-parity-build-sqlite`（`ExportMysqlToSqlite` 的 Python port；实测：94 表 / 574 万行 / 559 MB / 405 秒）
  - ✅ 1.3a `cbdb_parity.access_schema`（TablesFields.xlsx loader）
  - ✅ 1.3b 代码完成（`cbdb_parity.access_types`、`cbdb_parity.mdb_builder`、`cbdb-parity-build-mdb` CLI、build_all 集成、24 个测试）。Reviewer round 2 PASS。**Codex 最后一轮待跑**（代码完成时遇到 codex 用量上限，下次可用窗口后再过 gate）。提交最后一笔代码时，真实 mdb 端到端构建正在后台跑。
  - ✅ 1.4 `cbdb_parity.build_all` + `cbdb-parity-build-all`（SHA 缓存、manifest 不变式、partial-write 保护、强制 refresh）
  - ✅ 1.5 `cbdb_parity.parity_check`（mdb 与 sqlite 之间的行数 diff）

- **阶段 2 — 查询覆盖矩阵**
  - ✅ `coverage/avalonia_queries.yaml`（29 方法 / 9 服务）+ `coverage/access_queries.yaml`（43 查询 / 11 forms）+ `coverage/matrix.md`（16 直接配对 + 4 形状不匹配 + 4 仅 Access）

- **阶段 3（1–2 周）** —— 差分框架骨架 + 头 3 个配对查询（Entry / Office / Status，见 §6 starter set）。
  - ✅ 3a（路线调整 —— 不再走 .NET test host，因为用户机器只有 .NET runtime，没装 SDK）：`cbdb_parity.avalonia_query_sql`（从 `Sqlite*QueryService.cs` 提取 raw-string SQL）+ `cbdb_parity.avalonia_query`（用 Python sqlite3 复跑提取的 SQL，因为 Microsoft.Data.Sqlite 和 Python sqlite3 都包同一个 SQLite 引擎，所以行结果 bit-identical）。`EntryQueryRequest` 镜像 + `entry_query()` 已在真实 .build/cbdb.sqlite 上端到端验证。**Codex 一轮待跑。**
  - ✅ 3b：`cbdb_parity.diff_report`（DiffStats / DiffResult / `diff_rows` 支持复合 key + compare-fields 子集 + `write_report` 产出 WORK_PLAN §6/§7 文件树，hypothesis.md 跨次运行保留）+ `cbdb_parity.access_query`（cbdb_replay 桥接：`$ACCESS_TESTS_REPO/tests` 注入 sys.path、EntryQueryRequest → EntryQueryInputs 映射、行投影到 9 列公共子集）。**Codex 一轮待跑。**
  - ✅ 3c entry pair 烟雾测试：`tests/test_phase3c_entry_pair.py` —— 同一 request 喂两侧，按 `(person_id, sequence)` + 公共字段 diff，写报告，断言 `diff.stats.matches`。prereq（mdb、manifest 同 SHA、pyodbc、cbdb_replay）不满足时 pytest.skip。**Phase 1.3b 后台 build 完成 + 跑 `cbdb-parity-build-all` 锚定两端到同一 SHA 后，本测试会真正运行。**
  - ⏭ 3d（Office pair）和 3e（Status pair）按 3c 的同一模式扩展 —— `avalonia_query.py` / `access_query.py` 各加 `office_query`/`office_query_access` 与 `status_query`/`status_query_access`，对应烟雾测试镜像复制。

- **阶段 4（持续）** —— 按查询逐个扩覆盖，每个新查询同时产出 diff 报告与（如不一致）根因记录。目标：Tier 1 形状不匹配的几对（BIOG basic / associations / kinship / GroupData），然后 Access-only 类别（Texts / Networks / AssociationPairs / Place）等 Avalonia 端补齐对应功能。

## 9. 未决问题

**规划阶段已解决：**
- ✅ artisan 命令已找到：`db:export-to-sqlite`（`app/Console/Commands/ExportMysqlToSqlite.php`），辅助的索引/地址重建命令也定位完毕（见 §4b）。
- ✅ Avalonia headless：`Cbdb.App.Core` 全是 interface（`IEntryQueryService`、`IOfficeQueryService`、`IStatusQueryService`、`IGroupPeopleService`、`IPersonBrowserService`、`IPlaceLookupService`、`IDynastyLookupService`），SQLite 实现都在 `Cbdb.App.Data` 里。写一个小的 .NET 测试宿主直接 new `Sqlite*Service` 调用，**结构上可行**。阶段 3 用第一个查询做实证。
- ✅ Repo 名定为 `cbdb-access-avalonia-parity`，由本地 `gh` 在 `cbdb-project` org 下建。

**规划阶段已敲定：**
- ✅ **缓存**：生成的 Access `cbdb_data.mdb` 和 Avalonia `cbdb.sqlite` 都按 Datadump 文件名 + SHA 缓存。同一份 SHA 直接复用，除非 Datadump 换了或用户显式传 `--rebuild`。
- ✅ **Python → Docker 切换门槛**：**不**用工作日衡量。4a（1.3b）和 4b 实施期间，由用户**主动**触发 Codex review 检查 Python port 代码。如果**连续三轮 Codex review 仍然指出严重问题**，就把对应那一步切到 Docker MySQL 兜底。Codex review 由用户触发，不自动跑。
- ✅ **空 mdb 起步（1.3b）**：用 `pypyodbc.win_create_mdb()` —— 实测一行调用生成 172 KB 空 mdb。**不用** `pyodbc`（不存在文件直接报错）、**不用** ADOX/`win32com`（重）、**不用**在 repo 里 commit 模板（不可复现）。`pypyodbc` 加进 `[access]` extra 依赖，只用这一个函数；其他所有 mdb 操作继续走 `pyodbc`。
- ✅ **LICENSE**：Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International（CC BY-NC-SA 4.0）。
