# 工作计划

## 0. 范围契约（必读）

本仓库是**检测 / parity 测试框架**。所有贡献者——人或 agent
——都受以下两条规则约束。

### 0.a — 不修改其他 repo

- 我们暴露 Avalonia ↔ Access 不一致，在 `reports/known_issues.md`
  里记录，再由 parity gate 通过 `Suppress until …` 子句跳过。
- 我们**不修改上游 Avalonia 代码库**（`cbdb-desktop-app`）或
  任何其他仓库——无论本地还是 push 分支。即便 parity 测试让
  bug 一目了然，修复工作属于那个代码库的拥有者。
- 当 parity 测试因为某个已记录的上游 bug 而失败时，处理
  方式**永远**是：重新装载 auto-skip、链接 `known_issues.md`
  条目、把问题以 issue 之外的方式交给上游团队。从不在本 repo
  里给其他 repo 打补丁。

### 0.b — 不转写（2026-05-30 加入）

本 repo 不在 Python 里**重新实现**上游逻辑。每个测试必须直接调用
**上游代码本身**，而不是它的 Python 等价物。具体说：

- **Avalonia 端**：测试通过 `Cbdb.App.ParityHost` 调用
  `cbdb-desktop-app` 的真实 service（见 Phase 5）。从
  `Sqlite*Service.cs` 手抽 SQL 再用 Python `sqlite3` 跑、
  手 port BFS 状态机、或者其他形式的"在 Python 里模仿 C# 的
  行为"——Phase 5c-final 之后全部禁止。Phase 3–4 的 mirror
  层（`cbdb_parity/avalonia_query_sql.py` + `avalonia_*` 的
  SQL-extract 路径）已经退役。
- **Access 端**：测试调用 `cbdb-user-mdb-tests` 的
  `cbdb_replay.lookat*` 模块——这些是用户验证过的查询脚本，
  构成 Access 端的"真实代码"。
  `cbdb_parity/access_query.py` / `access_office_query.py` /
  `access_status_query.py`（Phase 3c/3d/3e）是已经落地的模板。
  在 `cbdb_parity/access_*.py` 里手写 `_ACCESS_SQL` 字符串
  来重建 Avalonia 的 join 形状，是 Access 端等价的 mirror-layer
  转写，同等禁止。
- **推论**：如果某个 Tier-2 surface 两端都没有"真实代码"
  可以调用（例如某些 Phase 4 per-person accessor 在
  `cbdb_replay.lookat*` 下没有对应物），按本规则**就不能**
  有 Phase 4 pair test。用 Phase 5c 的 mirror-vs-host 检查
  作为 Avalonia 端的 oracle，并在 `reports/known_issues.md`
  记录 Access 端的缺口。清理计划见 Phase 6。

陪本 repo 的 `cbdb-desktop-app` 视为**只读引用**。本机对该
工作树的修改、以及 push 到其任何 remote，都明确不在本 repo
任何 `/goal` 的范围内。

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
| `MARIADB_HOST` | Phase 1.6 中间缓存（§4d）使用的 MariaDB 主机。 | `localhost` |
| `MARIADB_PORT` | MariaDB 端口。 | `3306` |
| `MARIADB_USER` | 对 `MARIADB_DATABASE` 拥有 `CREATE / DROP / INSERT` 权限的用户。 | `root` |
| `MARIADB_PASSWORD` | MariaDB 密码。必填，缺失 fail-loud。 | `notSecureChangeMe` |
| `MARIADB_DATABASE` | Datadump 导入进去的库名。 | `cbdb_data` |
| `MARIADB_CONTAINER_NAME` | 信息性字段；仅在 `MARIADB_AUTO_LAUNCH=1` 时使用。 | `cbdb-parity-mariadb` |
| `MARIADB_FORCE_REIMPORT` | `1` = SHA 匹配也强制 drop 重导；`0` = 信任 DB 内的 provenance 行。 | `0` |
| `MARIADB_AUTO_LAUNCH` | `1` = 发现容器停了就 `docker start <CONTAINER_NAME>`；`0` = 要求用户自己起容器。 | `0` |

同步提交 `.env.sample`（占位值），`.env`（真实本地路径与密码）加进 `.gitignore` —— 永远不要把真实机器路径或密码提交进公开 repo。

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

### 4d. MariaDB 中间缓存层（⏳ Phase 1.6 —— Phase 1.3b 真实跑出经验之后加入）

Phase 1.3b 在真实 1.4 GB 五月 27 号 Datadump 上跑端到端时撞到两个 pyodbc/Jet 的硬伤，即便 Python 端口本身按设计跑通：

1. **Jet 2 GB 事务 work-buffer 上限** —— 即便最终 mdb 写完 < 1 GB，单事务批量导入到 `Microsoft Access Driver` 在累积的 work-buffer 跨过 .mdb 格式 2 GB 硬限那刻立刻 `HY001`。已在 `mdb_builder._drain` 改成**每张表 commit 一次**修复。
2. **dump 行违反 declared PK** —— Datadump 偶有重复值的 PK 列被 TablesFields.xlsx overlay 标成 PK，Jet 直接 `IntegrityError 23000` 整个事务 abort（即便 `$MYSQL2ACCESS_DIR` 里那份生产 mdb 也不强制 PK）。**抑制 overlay 的 PRIMARY KEY 子句**修复（NOT NULL 与 DataFormat 仍然生效）。

两条都打了补丁，Datadump 直链路径能跑完，但 **Datadump → Access 写入**本质上被 Microsoft Access ODBC 驱动按行加锁 + 没有任何 bulk-load 快速路径所限制（对比 SQLite 的 `synchronous=OFF / journal_mode=OFF`）。`$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb` 历史上的做法 + 用户实测都走的是 **MariaDB 中转** —— `Datadump → MariaDB` 快（Python parser 路径的 5-10×），`MariaDB → Access` 直接复用 notebook 验证过的 pyodbc 模板。

**MariaDB 中间层是 CACHE，不是替代任何一边的产物。**两个最终产物仍是 `cbdb.sqlite`（喂 Avalonia 端）和 `cbdb_data.mdb`（喂 Access 端）。mdb 仍然按 Phase 3 的设计流给 `cbdb_replay` 驱动的 pyodbc 测试用。Phase 1.6 让 MariaDB 取代 in-process mysqldump parser 成为两个 builder 的**默认 import source**；`cbdb_parity.mysqldump` 直链路径保留为非 Docker 主机的 fallback，通过 `source='datadump'` 选择。

**模块 / 配置布局（`Phase 1.6`）：**

- `.env` 新增 key（同步写进 `.env.sample` 与 §2 输入表里）：
  - `MARIADB_HOST=localhost`
  - `MARIADB_PORT=3306`
  - `MARIADB_USER=root`
  - `MARIADB_PASSWORD=…`  （必填，无默认 —— 缺失就 fail-loud）
  - `MARIADB_DATABASE=cbdb_data`
  - `MARIADB_CONTAINER_NAME=cbdb-parity-mariadb`（informational；我们默认**不**自动起容器，工具运行假设用户已经 `docker compose up`）
  - `MARIADB_FORCE_REIMPORT=0`（1 = 不管 SHA 是否一致都 drop 重导；0 = 信任 DB 里写入的 provenance 行）
  - `MARIADB_AUTO_LAUNCH=0`（1 = `cbdb_parity.mariadb` 发现容器停了会 `docker start`；0 = 直接报错"请先启动容器"。default 0 在多人共享工作站上更可预测）

- `cbdb_parity.mariadb`：
  - `connect(cfg) → pymysql.Connection`
  - `ensure_imported(cfg, info: DatadumpInfo)`：
    1. 连上后建库（如不存在）。
    2. 查 `_cbdb_parity_provenance(datadump_sha, imported_at)` 单行表里的 SHA。
    3. SHA 匹配且 `MARIADB_FORCE_REIMPORT=0` → 直接返回 cached。
    4. 否则：`DROP DATABASE IF EXISTS cbdb_data; CREATE DATABASE cbdb_data;`，把 .tar.gz 流送进 `mysql` CLI（`tar -O -xzf … | mysql …`）或 pymysql `executescript`，最后写 provenance 行。

- `sqlite_builder` 和 `mdb_builder` 增加 `source={'datadump','mariadb'}` 参数（1.6 落地后默认 `mariadb`，`datadump` 留给非 Docker 主机做 fallback）：
  - `mariadb` 路径：`SHOW TABLES` + `SELECT * FROM <t>` 逐表 → 现有的 CREATE/INSERT 循环。两个 builder 共用 `_pull_table_rows(conn, table) → (TableSchema, Iterable[Row])` 辅助函数，剩下的代码路径（skip 列表、batching、manifest、per-table commit）完全不变。

- `build_all` 编排器：
  - 第一步跑 `mariadb.ensure_imported(cfg, info)`。
  - 然后跑 sqlite + mdb 子构建器，源都换成 MariaDB。
  - `MARIADB_AUTO_LAUNCH=1` 时编排器可以 `docker start <CONTAINER_NAME>`；否则报"请启动容器" + rc=2。

**这是对 Phase 1.3b 的补充，不是替代** —— §1 严格流水线规则继续禁止用本机已有的用户 mdb 替代生成的产物。MariaDB import 是**我们流水线的一部分**，只是位于 Datadump 与两个写出器之间。

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

BIOG basic、kinship recursive、associations 当时有形状不匹配，需要做窄化处理后再配对——这一步在 Phase 4 落地，Phase 5c-final + Phase 6 之后被重新评估（结果是把大部分由此产生的 bridge 按 §0.b 非合规退役；当前状态见 §8 Phase 4 历史段和 §9 Post-Phase-9 status）。

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
  - ✅ 1.3b 代码完成（`cbdb_parity.access_types`、`cbdb_parity.mdb_builder`、`cbdb-parity-build-mdb` CLI、build_all 集成）。Codex review 跑到 v10 + Phase 3d v7 都干净通过。首次端到端跑五月 27 号 Datadump 时撞到两个真实问题，已合入补丁：
    - Jet 2 GB 事务 work-buffer 上限 → **per-table commit** in `_drain`。
    - PK 列重复值 `IntegrityError 23000` → 抑制 **PRIMARY KEY 子句**（NOT NULL / DataFormat 仍然生效）。
    Datadump 直链已可走通；MariaDB 中间路径（§4d，Phase 1.6）落地后会替代它作为默认。
  - ✅ 1.4 `cbdb_parity.build_all` + `cbdb-parity-build-all`（SHA 缓存、manifest 不变式、partial-write 保护、强制 refresh）
  - ✅ 1.5 `cbdb_parity.parity_check`（mdb 与 sqlite 之间的行数 diff）
  - ✅ **1.6 —— MariaDB 中间缓存**（`cbdb_parity.mariadb` + `cbdb-parity-import-mariadb` CLI + `cbdb_parity.mariadb_source` 事件适配；sqlite_builder + mdb_builder 默认 `source=mariadb`；build_all 先跑 `ensure_imported`）。实测：Datadump → MariaDB 226 秒、MariaDB → SQLite 130 秒（比原直链路径快 3.1×）。Codex 在 1.6a 上跑了 v1..v9；1.6b/c 那一轮 gate 队列在 codex 用量限制重置之后。形状见 §4d。

- **阶段 2 — 查询覆盖矩阵**
  - ✅ `coverage/avalonia_queries.yaml`（29 方法 / 9 服务）+ `coverage/access_queries.yaml`（43 查询 / 11 forms）+ `coverage/matrix.md`（16 直接配对 + 4 形状不匹配 + 4 仅 Access）

- **阶段 3（1–2 周）** —— 差分框架骨架 + 头 3 个配对查询（Entry / Office / Status，见 §6 starter set）。
  - ✅ 3a（路线调整 —— 不再走 .NET test host，因为用户机器只有 .NET runtime，没装 SDK）：`cbdb_parity.avalonia_query_sql`（从 `Sqlite*QueryService.cs` 提取 raw-string SQL）+ `cbdb_parity.avalonia_query`（用 Python sqlite3 复跑提取的 SQL，因为 Microsoft.Data.Sqlite 和 Python sqlite3 都包同一个 SQLite 引擎，所以行结果 bit-identical）。`EntryQueryRequest` 镜像 + `entry_query()` 已在真实 .build/cbdb.sqlite 上端到端验证。**Codex 一轮待跑。**
  - ✅ 3b：`cbdb_parity.diff_report`（DiffStats / DiffResult / `diff_rows` 支持复合 key + compare-fields 子集 + `write_report` 产出 WORK_PLAN §6/§7 文件树，hypothesis.md 跨次运行保留）+ `cbdb_parity.access_query`（cbdb_replay 桥接：`$ACCESS_TESTS_REPO/tests` 注入 sys.path、EntryQueryRequest → EntryQueryInputs 映射、行投影到 9 列公共子集）。**Codex 一轮待跑。**
  - ✅ 3c entry pair 烟雾测试：`tests/test_phase3c_entry_pair.py` —— 同一 request 喂两侧，按 `(person_id, sequence)` + 公共字段 diff，写报告，断言 `diff.stats.matches`。prereq（mdb、manifest 同 SHA、pyodbc、cbdb_replay）不满足时 pytest.skip。**Phase 1.3b 后台 build 完成 + 跑 `cbdb-parity-build-all` 锚定两端到同一 SHA 后，本测试会真正运行。**
  - ✅ 3d（Office pair）：`cbdb_parity.avalonia_office_query` + `cbdb_parity.access_office_query` + `tests/test_phase3d_office_pair.py`。字段命名对齐 `Cbdb.App.Core.OfficeQueryRecord` snake-case 属性名；C# reader 的 57/64 列序错位通过 `_sql_row_to_record_row` 镜像。Access bridge 拒绝 cbdb_replay/lookatoffice 无法忠实复现的分支（person_keyword / dynasty_ids / 有 place ids 时的 subordinate flags / 空 office_codes），避免误报。Codex v1..v7 干净通过。
  - ✅ 3e（Status pair）：`cbdb_parity.avalonia_status_query` + `cbdb_parity.access_status_query` + `tests/test_phase3e_status_pair.py`。形状同 3d，36 字段，C# reader 列序与 SELECT 一致没有错位。Codex 队列等待用量限制重置。

- **阶段 4（已完成 2026-05-28）** —— 按查询逐个扩覆盖，每个新
  查询同时产出 diff 报告与（如不一致）根因记录。目标：Tier 1
  形状不匹配的几对（BIOG basic / associations / kinship /
  GroupData），然后 Access-only 类别（Texts / Networks /
  AssociationPairs / Place）等 Avalonia 端补齐对应功能。
  落地后 Phase 5 / Phase 6 对 Phase 4 做了重大重构（见下文）。

- **阶段 5（2026-05-29 落地）** —— 转向通过新的
  `Cbdb.App.ParityHost` 控制台直接调用 .NET Avalonia 执行。
  之前 Phase 3-4 走 "提取 SQL + Python 重跑" 路径是因为用户
  机器只有 .NET runtime 没装 SDK。SDK 8.0.421 装上后，可以
  停止在 Python 里 mirror C# 语义，改为直接调用真实的 C#
  service。

  - **5a — ParityHost 控制台（住在本 repo 内，不进上游）
    （✅ 落地 2026-05-29）**：
    - 项目位置：`parity_host/Cbdb.App.ParityHost/`（`dotnet new
      console -f net8.0`），**不**进 `cbdb-desktop-app`。
    - 通过 `$(AvaloniaRepo)` MSBuild 属性走
      `<ProjectReference>` 引用 `Cbdb.App.Core` /
      `Cbdb.App.Data`；`AvaloniaRepo` 从环境变量读取。
    - CLI：`cbdb-parity-host <service> <sqlite-path>` →
      STDIN 读 JSON request → STDOUT 写 JSON response →
      STDERR 写 `{error, stack}`。
    - 编码契约（Windows 上 load-bearing）：双向 UTF-8（无 BOM）。

  - **5b — Python harness 切换（✅ 落地 2026-05-29）**：
    每个 `cbdb_parity/avalonia_*.py` 加新执行模式
    `via_parity_host(...)`，subprocess 调用 ParityHost
    二进制，JSON-serialise request，parse JSON response。
    原 SQL-extract 路径暂时保留作为 diff 对照。

  - **5c — 退役 Python mirror 层（✅ 落地 2026-05-29）**：
    via-ParityHost 路径与 mirror 路径证明等价后，删除 SQL
    extractor + 关联的重写（`_csharp_params_to_sqlite`、
    `_join_display`、`_to_bool_or_none`、AddrField casefold、
    NULL sequence → 0 等等）。

  - **5d — kinship expandNetwork=true 互验（✅ 落地
    2026-05-29，已在 5c-final 阶段退役）**：BFS 状态机
    （`avalonia_kinships_expanded.py` 中的 ~530 行手 port）
    与 ParityHost 直接调用做 byte-for-byte 对照，证明等价
    后整段 port 删除。

  - **5e — 覆盖扩展（✅ 落地 2026-05-29）**：上游已有的
    lookup/group 接口（DynastyLookup / PlaceLookup /
    GroupPeople）通过 ParityHost 加 dispatch + Python
    封装（`cbdb_parity/avalonia_lookups.py`）+ smoke 测试
    （`tests/test_phase5e_lookups_smoke.py`）。Texts /
    Networks / AssociationPairs 因为上游还没有 service，
    按 §0.a 不在本 repo 范围内，等上游落地后再补 host
    dispatch + Python wrapper + smoke test。

  Phase 5 总账：364 passed, 7 skipped, 1 xfailed（落地时）。

- **阶段 6（2026-05-30 落地）** —— 把 §0.b "不转写" 规则
  追溯应用到 Phase 4。Phase 5c-final 退役了 Avalonia 端的
  Python mirror 层，但 Phase 4 在 Access 端留下的手写
  `_ACCESS_SQL` bridge 仍然违反 §0.b——它们在
  `cbdb_parity/access_*.py` 里重建 Avalonia 的 join。
  Phase 6 把 Phase 4 对齐到新规则。

  Access 端的"真实代码"是 `cbdb-user-mdb-tests` 的
  `cbdb_replay.lookat*` 模块（Phase 3c/3d/3e 通过
  `cbdb_parity/access_query.py` / `access_office_query.py`
  / `access_status_query.py` 已经在用，是 Phase 6 每个重写
  借鉴的模板）。

  - **6a — 改写有 cbdb_replay 对应物的 bridge（✅ 落地
    2026-05-30）**：实际只有 1 个 surface 合格：

      | surface       | 上游模块                         | 替换的 bridge                      |
      |---------------|----------------------------------|------------------------------------|
      | kinships      | `cbdb_replay.lookatkinship`      | `cbdb_parity.access_kinships`      |

    把 `_ACCESS_SQL` + pyodbc 管路换成
    `_ensure_cbdb_replay_on_path` + `replay_run` + 字段投影
    模式（模板：`cbdb_parity/access_office_query.py`）。

    **执行中发现（2026-05-30）**：associations 原本也在 6a
    范围，但
    `cbdb_replay.lookatassociations.AssocQueryInputs` 没有
    `person_id` 输入——它的 SQL 是
    `WHERE c_assoc_code IN (...)`，回答的是"匹配这些
    assoc_codes 的所有行"，而 Avalonia 的
    `GetAssociationsAsync(personId)` 回答的是 per-person
    问题。包装它去回答 per-person 问题需要 Python 侧按
    `c_personid` 后过滤——这就是 orchestration 端的转写
    模式，违反 §0.b。associations 因此**降级到 6b**（删除）。

  - **6b — 删除没有 cbdb_replay 对应物的 bridge（✅ 落地
    2026-05-30）**：13 个 surface——12 个完全没有
    `cbdb_replay.lookat*` 模块，加上 6a 发现的 associations：

    ```
    addresses, altnames, associations, biog_basic, detail,
    entries（per-person），events, institutions,
    possessions, postings, sources,
    statuses_person, writings
    ```

    删除文件清单：每个 surface 对应的
    `cbdb_parity/access_<surface>.py`、
    `tests/test_phase4_<surface>_pair.py`、
    `reports/<surface>_basic_person/`。这些 12 个
    PersonBrowser 系列 surface 的 Avalonia 端 oracle 由
    `tests/test_phase5c_person_mirror_vs_host.py` 保留；
    associations 也在该测试里有
    `test_associations_mirror_vs_host`。

    `coverage/matrix.md` 同步更新，标记每行"无 Access ground
    truth；在 `reports/known_issues.md` 的 `tier2_per_person`
    跟踪"。

  - **6c — Phase 5e pair tests 结构性不可行（✅ 落地
    2026-05-30）**：原计划用
    `cbdb_replay.lookatgroupdata` / `cbdb_replay.lookatplace`
    把 group_people / place_lookup 从 smoke-only 升级为 pair
    test。检查发现两者都答错了问题：

    - **place_lookup vs lookatplace**：Avalonia 的
      `GetPlacesAsync` 返回 **place 下拉选项**；
      `lookatplace.run` 返回 **给定地址处的人**
      （BIOG_MAIN 按 `c_index_addr_id` 过滤）。
      不同问题，不同输出形状。
    - **group_people vs lookatgroupdata**：Avalonia 的
      `GroupPeopleQueryResult` **只有 5 个 category sub-table**
      （StatusRecords / OfficeRecords / EntryRecords /
      TextRecords / AddressRecords），所有 `include_*` 关掉
      返回 5 个空列表；`lookatgroupdata.run` 在没开 category
      flag 时返回 **base BIOG_MAIN 记录**，开了任何 flag
      就抛 NotImplementedError。两端输出形状没有重合。
    - **dynasty_lookup**：cbdb_replay 完全没有对应模块。

    操作：3 个 Phase 5e surface 全部保持 smoke-only。当前的
    `tests/test_phase5e_lookups_smoke.py` 就是 §0.b 兼容的
    底线。

  - **6d — biog_basic keyword 分支覆盖（✅ 落地 2026-05-30）**：
    在 `tests/test_phase5c_person_mirror_vs_host.py` 加两个
    host-vs-mirror case 覆盖
    `SqlitePersonBrowserService.SearchAsync` 的两个非空
    keyword 分支：
    - `test_biog_basic_person_id_keyword_mirror_vs_host`：
      数字 keyword `"1762"` 走
      `int.TryParse → hasPersonIdKeyword=true`，应只返回王安石。
    - `test_biog_basic_fuzzy_keyword_mirror_vs_host`：
      非数字 keyword `"獾郎"`（王安石的别名"獾郎"）走
      LIKE-across-names + ALTNAME_DATA UNION 分支。该
      keyword 在所有 10 个 BIOG_MAIN 主名字段中 0 命中，
      在 ALTNAME_DATA 里命中 1 次。任何非空结果都证明
      ALTNAME_DATA 那条 UNION arm 跑过了。

    Mirror（`avalonia_biog_basic.biog_basic_query`）经过
    Phase 5c-final 之后就是一层薄 via_host 封装，两条路径
    都路由进 ParityHost 调上游真实 SearchAsync——这两个
    case gate 的是封装的 keyword 透传 + dataclass→JSON
    序列化，不是任何第二份上游实现。

  Phase 6 总账：354 passed, 6 skipped, 1 xfailed（落地时）。
  相对 Phase 6 之前的 364 passed，删了 12 个 pass（13 个
  pair test 中 postings_pair 本来就 skip）、加了 2 个 6d
  case。这 12-test 的减少是执行 §0.b 的明确代价——那些
  测试断言的是"我自己手写的 SQL == upstream 的 SQL"，新
  规则把这归类为伪 oracle。

- **阶段 7（2026-05-30 起规划）** —— 本 repo 内的整理 +
  CI 骨架 + 运行时优化。所有在**不修改**
  `cbdb-desktop-app`、`cbdb-user-mdb-tests` 且**不向它们提
  issue**的前提下还能做的事。需要上游改动的事项（Texts /
  Networks / AssociationPairs service、per-person
  `lookat<surface>` 模块、`lookatkinship` 的 LEFT JOIN
  变体、形状匹配 `GroupPeopleQueryResult` 的
  `lookatgroupdata` 变体、`lookatdynasty`、
  `lookat_place_options`）按 §0.a 明确不在范围内。给其他
  repo 提 issue 也按 2026-05-30 用户指示明确排除。

  Phase 7 拆成八个独立子阶段，每个以 codex sign-off + `git
  push` 收尾，节奏同 Phase 5/6。

  - **7a (✅ 落地 2026-05-30) — `coverage/matrix.md` Tier 3/4
    显式标记 out-of-scope**。Tier 3（仅 Access 的导出工作流：
    GIS、Neo4j、UCINet、Pajek、Gephi）和 Tier 4（每个 form
    的 bulk-IO helper）原本为完整性列在矩阵里，但它们产出
    文件而不是可 diff 的行数据。在每个 tier 头加了一段说明，
    按 §0.a 明确标记**不在本 repo parity 范围内**。纯文档。

    *Codex round*：干净。

  - **7b (✅ 落地 2026-05-30) — `WORK_PLAN.md §9 未决问题`
    Post-Phase-6 收尾段**。§9 原本停在规划阶段决策；加了
    "Post-Phase-6 status (2026-05-30)" 子节，列举 (a)
    `known_issues.md` 里抑制了什么、为什么，(b) 每个抑制
    重新打开需要什么，(c) suite 计数契约（354/6/1）。
    纯文档。

    *Codex round*：抓出三个问题——354/6/1 契约最初锚在
    "HEAD" 但 7c 马上要加 4 个 passing 测试，所以锚要改成
    Phase 6 close 的 commit (`dddedc1`)；"Active
    suppressions" 表里混进了一条历史 breadcrumb 行（不是真
    的 active）；`avalonia_gap (legacy)` umbrella 的 re-arm
    条件太弱（"at least one"），改成 umbrella 一直挂到四个
    service 都到位。

  - **7c (✅ 落地 2026-05-30) — `reports/SUMMARY.md`
    自动生成 hook**。加了 `cbdb-parity-summary` CLI 入口，
    包装已有的 `cbdb_parity.summary_report.write_summary`，
    让 `reports/SUMMARY.md` dashboard 可以按需重生。退出码：
    0 正常、2 reports 树不存在。加了 3 个 CLI 测试覆盖 happy
    path、missing-dir、默认 cwd 解析。

    *Codex round*：抓出两个问题——rewrite happy-path 测试
    没有预设 sentinel `SUMMARY.md`，所以一个静默追加或拒绝
    的 CLI 会 false-pass（改成写一个 sentinel 后断言它消
    失）；`--reports-dir` 接受任何 `exists()` 的路径，
    如果是文件后面会在 `iterdir()` 崩溃（加了 `is_dir()`
    检查返回 exit 2 + 受控诊断，并加第 4 个测试钉住）。

  - **7d (✅ 落地 2026-05-30) — Phase 5c 多 fixture
    参数化**。每个 `test_phase5c_person_mirror_vs_host.py`
    case 原本只用 `person_id=1762`（王安石）；把每个
    per-person accessor 跨三个 fixture 参数化、跨两个朝代
    ——王安石（北宋）、李白（唐，32540）、朱熹（南宋，
    3257）。11 个 accessor × 2 个新 fixture = +22 个
    passing case。

    *Codex round*：抓到一个真的 false-pass 类——helper 接
    受 `[] == []` 当成 pass，所以任何在 canonical 数据集
    上零行的 (accessor, person_id) 组合都默默通过，根本没
    跑上游 SQL。直接 `COUNT(*)` 探测 `cbdb.sqlite` 显示
    possessions 和 institutions 对三个 fixture 都是 0，
    events 对两个 fixture 是 0。修复：加 `_EXPECTED_EMPTY`
    显式 allow-list + 双向 gate：不在 allow-list 且 host 返
    回 0 → FAIL；在 allow-list 但 host 返回 ≥1 → FAIL。
    并把 `label` 参数透过 `_run_person_pair` 串进去，让 assert
    消息按 fixture 名字定位失败。

  - **7e (✅ 落地 2026-05-30) — Phase 4 kinships pair
    orphan-kin 证明 case**。`kinships_basic_person` known
    issue 记录了 cbdb_replay INNER JOIN 丢 orphan kin、
    Avalonia LEFT JOIN 保留，但 canonical fixture（王安石
    /1762）没 orphan kin，缺口看不到。加了一个运行时
    detector，扫描当前 build 找 orphan kin——既包括
    `c_kin_id` 在 BIOG_MAIN 找不到对应行的情况，也包括
    `NULL c_kin_id` 行（INNER JOIN 两类都丢，LEFT JOIN
    两类都保留）——找到就用那人跑 pair 并断言文档化的
    差异形状；没找到就用精确诊断 skip。2026-04-30
    Datadump 两条路径都是 0 orphan，所以测试在落地版上
    skip；detector 已经连好，未来 dump 触发任一路径都会
    arm。

    *Codex round*：抓出三个问题——detector 排除了
    `NULL c_kin_id` 行，但那个也触发 gap（INNER JOIN 丢
    NULL）；count-only 断言
    （`rows_only_in_avalonia == expected_orphan_count`）
    可能 false-pass，如果同一个人还有不相关的 only-in-Avalonia
    差异（改成按 spliced `kin_person_id` 集合做 row-identity
    检查）；skip 消息说 "any future dump arms it" 但没说
    smoke-test 的前置条件（mdb/sqlite 已构建、manifest SHA
    匹配、pyodbc 已装）。

  - **7f (✅ 落地 2026-05-30) — Phase 4 replay_scan
    kinship 扩展**。6a 之后 kinships 已经 §0.b 兼容；扩展
    `test_phase4_replay_scan.py` 让它也跑跨朝代 seed person
    的 `cbdb_replay.lookatkinship` ——三个：李白（唐）、
    范仲淹（北宋）、朱熹（南宋）。每个都在 fixture-design
    时验证非空。

    *Codex round*：抓出两个问题——case payload 验证只
    检查 dict-with-key 不检查 value 类型，所以
    `{"person_id": "32540"}` 或 `{"person_id": True}` 这种
    损坏 payload 会越过契约边界（改成加 non-bool-int 验证；
    `bool` 是 `int` 的 subclass 在 Python 里所以要显式拒
    绝）；kinship dispatch 分支有跟 7d 同一类的 empty-row
    trivial pass 漏洞（加了对 Avalonia 和 access 两侧 row
    数都 ≥1 的断言再做 diff）。

  - **7g (✅ 落地 2026-05-30) — GitHub Actions CI
    workflow**。`.github/` 原本不存在。加了一个 workflow，
    在 `push` 和 `pull_request` 时 (1) 装 dev + harness
    extras（**不**装 access —— pyodbc 只在 Windows 上），
    (2) 跑 `pytest --collect-only` 抓 import / syntax
    regression，(3) 跑非 DB 单元测试，(4) lint `cbdb_parity/`
    和 `tests/`（ruff）。**不**尝试 build mdb 或 sqlite，
    **不**尝试 spin up ParityHost；那些测试跑留在本地。

    顺便把 repo 已有的 ruff 状态清干净让 lint job 能过：
    auto-fix 了 29 个问题（主要是 I001 import 顺序 + 没用
    的 import）跨 21 个文件，并修了一个真的 B904 在
    `cbdb_parity.parity_host`（一个 `except` 块 re-raise
    `ParityHostError` 没用 `from exc`，丢了下层 JSON-decode
    失败的上下文）。

    *Codex round*：发现初版 `RUF002/RUF003` global ignore
    比实际需要宽——会默默接受未来 prose 里出现的偶发
    ambiguous-Unicode。改成 `[tool.ruff.lint.per-file-ignores]`
    只 scope 到三个文件，那里的 `×` / `−` 是有意的技术符号
    （`access_status_query.py`、`avalonia_postings.py`、
    `test_parity_host_vs_mirror.py`）；其他位置 ruff 继续
    抓 homoglyph。

  - **7h (✅ 落地 2026-05-30) — ParityHost NDJSON daemon
    模式**。每个 host call 原本付 ~1s 的 `dotnet run
    --no-build` 冷启动。NDJSON daemon 模式让一个 host
    进程保持存活，stdin 流式接收每行一帧的
    `{service, sqlite_path, request}` JSON 帧，stdout 流式
    回每行一帧的 `{ok: …}` 或 `{error, stack}`。one-shot
    模式作为调试路径保留。

    实现：
    - C# 侧：新 `--daemon` flag 让 `Program.Main` 进入
      `while ((line = await Console.In.ReadLineAsync()) != null)`
      循环。per-frame 失败不杀 daemon；EOF on stdin 退出 0。
      每次写完 response 行后必须 `FlushAsync()`——Windows 上
      stdout 缓冲否则不会 drain 直到进程退出。
    - Python 侧：`cbdb_parity.parity_host.ParityHostDaemon`
      context manager 起 daemon，per-frame `{"error"}`
      payload 上升为 `ParityHostError`，EOF 时 raise
      `ParityHostError("daemon died after N frames")` 带
      stderr。
    - per-frame 错误保持 daemon 存活；daemon 死亡是硬重启
      信号。

    Phase 8a 随后把这个 daemon 接入了重流量测试文件（见
    Phase 8）；7h 本身只落 daemon + 4 个 smoke 测试，没改
    已有测试。

    *Codex round*：抓出三个问题——`per_call_timeout_seconds`
    存了但没强制，卡住的 dispatch 会让 pytest 永远挂
    （加了 helper 线程跑 `proc.stdout.readline()`，主线程
    按 timeout join）；正常运行期间没有东西 drain stderr，
    一个写 ~64 KB 到 stderr 的 child 会在 flush NDJSON
    response 前死锁（加了后台线程从 `__enter__` 到
    `__exit__` 把 stderr drain 到有界 `deque`）；
    `__exit__` 的 timeout-then-kill 路径把 stdout/stderr
    buffer 扔掉，丢了唯一有用的崩溃上下文（重排成 close-stdin
    → wait → 必要时 kill → 信号通知 stderr drain 线程退出
    并 join，保住捕获的行）。

  - **落地后的 suite delta**（纯加，不会有 §0.b
    regression）：7c 加了 4 个 CLI 测试，7d 加了 22 个参数
    化 case（11 个函数 × 2 个新 fixture），7e 加了 1 个
    case 但在 canonical dump 上当前 skip，7f 加了 3 个
    replay_scan kinship 行，7h 加了 4 个 smoke 测试；
    7a/7b/7g 纯 docs/CI/lint，加 0 个 passing case。
    Phase 7 净：33 个 pass + 1 个 skip。

  - **Phase 7 不做**（按 §0.a + 2026-05-30 用户指示）：
    - 请 `cbdb-user-mdb-tests` 加 12 个缺失 surface 的
      `lookat<surface>`、LEFT JOIN kinship 变体、形状匹配
      `GroupPeopleQueryResult` 的 `lookatgroupdata`、
      `lookatdynasty`、`lookat_place_options`。
    - 请 `cbdb-desktop-app` 加 Texts / Networks /
      AssociationPairs service 或暴露
      `GetPeopleAtPlacesAsync`。
    - 给两个 repo 任一提 GitHub issue 追踪以上事项（用户
      明确排除）。

  - **顺序**：7a → 7b → 7c → 7d → 7e → 7f → 7g → 7h。
    每步 codex sign-off + `git push`。7a/7b/7c 是非常小的
    纯文档改动，方便的话可以打包。7d → 7e → 7f 都改测试且
    全程保持绿。7g 与其他独立；7h 最后且最大。

- **阶段 8（2026-05-30 起规划）** —— Phase 7 收尾：兑现
  7h 推迟的运行时收益、扫除过时的注释与文案、把所有
  文档索引拉到一致的 Phase 7 之后状态。Phase 8 收完之后，
  repo 才算真正进入稳态——剩余只是等上游对 `known_issues.md`
  里每条 suppression 的对应动作。

  Phase 7 收尾审计（2026-05-30）发现的项目。所有项目都**不
  需要**改动 `cbdb-desktop-app` 或 `cbdb-user-mdb-tests`，
  也**不需要**给任何 repo 提 issue。按 §0.a + 2026-05-30
  用户指示，这些都明确不在范围内。

  Phase 8 拆四个子阶段，每个以 codex sign-off + `git push`
  收尾，节奏同 Phase 5/6/7。

  - **8a — 把 `ParityHostDaemon` 接入重流量测试**。
    Phase 7h 落地了 daemon 模式 + 4 个 smoke 测试，但**没
    有**让任何已有测试切到 daemon。现有的
    `invoke_parity_host` 和 `invoke_person_accessor_via_host`
    调用点仍然每次起一个 subprocess。7h WORK_PLAN
    承诺的 "host-using 子集 ~4m → ~30s" 还没兑现。

    具体动作：
    - 在 `tests/conftest.py` 加一个 session 级 pytest
      fixture，启动一次 `ParityHostDaemon`，session
      teardown 时关掉。
    - 给 `invoke_person_accessor_via_host` /
      `invoke_parity_host` 加一个可选的
      `daemon=<ParityHostDaemon>` kwarg，传入时改调
      `daemon.invoke(...)`。
    - 把 `tests/test_phase5c_person_mirror_vs_host.py` 和
      `tests/test_phase4_replay_scan.py`（两个最重的 host
      消费者）切到 fixture。
    - Phase 7d 的 `_run_person_pair` helper 是 5c 侧的
      集中注入点；replay_scan 侧的 kinship 分支直接调
      bridge，需要把 daemon 透传进去。

    验收（8a codex round 期间细化）：**host-using 子集**
    （test_phase5c_person_mirror_vs_host + test_phase4_replay_scan
    kinship 分支 + test_phase7h）降到 ≤90 秒。Phase 5c 文件
    单独从 ~70 秒降到 ≤30 秒（-60%+）。完整 suite 时间会变
    短但主要由非 host 测试（构建流水线、mariadb、lint
    setup 等）决定，所以"≤90 秒完整 suite"目标过于乐观，
    8a codex round 期间撤回。Codex 审最终实现，不只是 plan。

  - **8b — 过时文案 + 代码注释扫除**。Phase 7 收尾审计
    发现六处带有跨 phase 边界过时引用的位置：

    | 位置 | 当前文字 | 问题 |
    |---|---|---|
    | `cbdb_parity/parity_host.py` docstring（第 5-6 / 109 行） | "the NDJSON daemon mode that amortises that comes in a later commit (Phase 5a-5 per WORK_PLAN.md)" | Daemon 在 7h 落地，不是 5a-5。 |
    | `parity_host/Cbdb.App.ParityHost/Program.cs` 第 18 行 | "(NDJSON daemon mode comes in a later commit)" | 同上。 |
    | `cbdb_parity/access_office_query.py` 第 20 / 95 行 | "Phase 4 will widen the bridge as the cross-section grows" 等 | Phase 4 已闭环；cross-section 现在受 §0.b 约束，不会再扩。 |
    | `cbdb_parity/avalonia_biog_basic.py` 第 6 行 | "when a follow-up wants to cover that, just pass `keyword` through" | keyword 分支已经被 Phase 6d/7 的 `test_biog_basic_person_id_keyword_mirror_vs_host` 和 `test_biog_basic_fuzzy_keyword_mirror_vs_host` 覆盖。 |
    | `reports/known_issues.md` "Suppression sunset" 段 | "Per WORK_PLAN §7, every entry in this file should also have a follow-up tracking issue in `cbdb-project`'s issue tracker." | 与 2026-05-30 用户指示（F1+F2 排除）冲突。`known_issues.md` 自身就是 canonical 行动清单。 |
    | `reports/known_issues.zh-Hant.md` "豁免到期管理" 段 | 同上的繁中版本 | 镜像同步。 |

    每一处要么 (a) 改指向真实落地的 commit / phase，要么
    (b) 直接把过时的"未来时"删掉。sunset 段重写时显式说
    明 `known_issues.md` 自身就是 canonical 清单，每条
    "Suppress until" 行就是 actionable trigger。纯文档。
    Codex review。

  - **8c — 仅本地的 stale report 目录清理**。Phase 6b
    把 13 个 `reports/<surface>_basic_person/`（和
    `_basic`）目录从 git 里删了，但 Phase 6b 之前的
    本地 pytest 跑过留下的文件系统残留：

    ```
    reports/addresses_basic_person     reports/altnames_basic
    reports/associations_basic_person  reports/biog_basic_search
    reports/detail_basic_person        reports/entries_basic_person
    reports/events_basic_person        reports/institutions_basic_person
    reports/possessions_basic_person   reports/postings_basic_person
    reports/sources_basic_person       reports/statuses_basic_person
    reports/writings_basic_person
    ```

    `git ls-tree` 确认这些**没**被 git 跟踪；`git status`
    也不显示它们（不带新文件的未跟踪目录不出现）。它们
    只是 Phase 6b 之前的本地沉积物。

    动作：在 8c commit 的预备步里 `rm -rf` 掉本地这些目录
    （rm 本身没有 commit；commit 只捕获相关 doc-touch，或
    直接并入 8b）。**不需要**加 `.gitignore`——对应的
    pair test 已经删掉，未来跑测试不会再生成这些目录。
    其他 dev 本地 clone 里如果也有，自己重复 rm 即可。

    可选保险：在 `reports/.gitkeep` 的注释里加一行（如果有
    的话）提醒：退役的 per-surface 目录应该本地手动 rm。
    可选；只在有版本控制文件改动时走 codex review。

  - **8d — Phase 7 回填到 `WORK_PLAN.md` + zh-CN 同步**。
    Phase 7 当时在 `WORK_PLAN.md` 和 `WORK_PLAN.zh-CN.md`
    里**作为计划**写好就开始执行，7a-7h 全部落地之后两份
    都没收到 Phase 5b/5c/5d/5e 和 Phase 6a-6d 那种
    `(✅ 落地 YYYY-MM-DD)` 标记。Phase 7 子阶段还累积了
    codex round 的发现以及真实 suite delta，plan 里没体现。

    动作：
    - 给 `WORK_PLAN.md` 里每个 Phase 7 子阶段标题加
      `(✅ landed 2026-05-30)`（7a → 7h）。
    - 把每个子阶段的真实 codex round delta 追加进去
      （如 7c 加了 4 个 CLI 测试不是 0、7d 的 empty-row
      guard 抓到的 false-pass 类、7e 的 NULL c_kin_id
      detection 扩展、7f 的 payload typing 收紧、7g 的
      per-file RUF002/RUF003 scope、7h 的 timeout 强制 +
      stderr drainer + 安全 exit）。
    - 扩展 §9 的 "Post-Phase-6 status (2026-05-30)" 段，
      加一个 "Post-Phase-7 status (2026-05-30)" 子节，把
      新的 suite-count 契约锚定到 Phase 7 close
      （387 passed / 7 skipped / 1 xfailed，commit
      `46e8186`；Phase 8 审计修正了 Phase 8a-era 的 "388 /
      7 / 1" 说法，详见 Post-Phase-9 status 块里的每个
      sub-phase 算术）。
    - 刷新 `README.md` 的 "Repository status" 段：
      "Phases 1–6 landed (2026-05-27 → 2026-05-30).
      Current suite: 354 passed, 6 skipped, 1 xfailed."
      改为 "Phases 1–7 landed (2026-05-27 → 2026-05-30).
      Current suite: 387 passed, 7 skipped, 1 xfailed."
      架构图说明里加一句 `ParityHostDaemon` 已可用。
    - 把上面所有内容原样镜像到 `WORK_PLAN.zh-CN.md`——
      §0 的拆分、每个 Phase 7 子阶段 ✅ 标记、Phase 7
      close 锚点、同样的 codex round 注解。在中文做出的
      决策以 zh-CN 为准，让 zh-CN 镜像跟英文头不要差超过
      1–2 个 commit 是 §0.a 契约的一部分。

    在最终合并完的 edit 上跑 codex review（en + zh-CN
    一批合并审，这种纯文档子阶段可以这样做）。

  - **落地后的 suite delta**：Phase 8 加 **0** 个新通过的
    case。8a 是运行时变化（对 count 中性），8b/8c/8d 是
    文档 / 本地清理。387/7/1 契约（即 Phase 8 审计把
    Phase 7 close 从 388 修正到 387 之后的数字）是 Phase
    8 之后的 canonical suite size——每个 sub-phase 的算术
    见 §9 Post-Phase-9 status 块。

  - **Phase 8 不做**（按 §0.a + 2026-05-30 用户指示）：
    - 同 Phase 7 排除项——不改 upstream，不给任何
      repo 提 issue。
    - "用真实 PR 验证 CI" 不算单独任务：下一个有贡献者
      的 push 或 PR 会自动让 GHA 跑，那就是真实世界
      validation，代替任何合成前提检查。如果第一个 PR
      上 CI 红了，假设性的 Phase 8e 那时再落补丁。

  - **顺序**：8a → 8b → 8c → 8d。8a 是唯一改动代码的
    子阶段（也是唯一会看到 suite-runtime 变化的）；
    8b/8c/8d 都是文档 + 本地清理，方便的话可以打包成
    一个 commit，参考 7a/7b/7c 先例。每步 codex sign-off
    + `git push` 收尾。

- **阶段 9（2026-05-30 规划）** —— Phase 8 cosmetic follow-up。
  两个纯文档子阶段——Phase 8 收尾扫描时发现了，但小到可以
  单独走一遍。

  Phase 9 不改 suite count、运行时、或任何对外 API。两件
  事都是让 in-repo 文档准确反映 Phase 8 之后的真实情况。

  - **9a (✅ 落地 2026-05-30) — Phase 7 sub-phase prose
    改成 past-tense + codex annotations**（en + zh-CN）。
    8d 给每个 Phase 7 sub-phase 加了 `(✅ 落地 2026-05-30)`
    标签，但段落本体还停在规划态的未来时。把两份文档里
    每一段都改成了回顾式过去时，并在每段后附上该 sub-phase
    的实际 codex round delta 注释块：
      - 7a：codex 干净。
      - 7b：算术 + suppression-table 准确性 + Phase 6
        close-out 锚点。
      - 7c：rewrite happy-path 需要 sentinel + reports-dir-
        is-a-file rejection。
      - 7d：empty-row false-pass class → `_EXPECTED_EMPTY`
        allow-list + label 透传。
      - 7e：NULL c_kin_id detection + row-identity
        assertion + skip-msg 精确化。
      - 7f：payload typing 收紧 + kinship dispatch 分支
        empty-row guard。
      - 7g：per-file RUF002/RUF003 scope（原来是 global）。
      - 7h：timeout 强制 + 后台 stderr drainer + 更安全
        `__exit__`。

    *Codex round*：抓出三个问题——7e 段落本体没说全
    （detector 还要把 `NULL c_kin_id` 当 trigger，正文
    只写了无 BIOG_MAIN 对应行的情况）；7h 对 Phase 8a 的
    交叉引用还是 forward-looking（"later wires" → "subsequently
    wired"）；7d en/zh-CN 漂移于 "spanning two dynasties" 这个
    描述（加到 zh-CN 上对齐）。

  - **9b (✅ 落地 2026-05-30) — `AGENTS.md` Phase 7/8
    补段**。AGENTS.md 当时有 §0.b 但没提两件对新贡献者
    有意义的落地事项。加了一个 "Phase 7 + Phase 8
    operational landings" 子节：
      - `.github/workflows/ci.yml` 的 CI workflow（Phase 7g）
        ——跑什么、不跑什么、哪类改动要保持 CI 绿；
      - 通过 `parity_host_daemon` pytest fixture 启用的
        ParityHost daemon mode（Phase 7h + 8a）——两种模式
        契约、fixture 接入方式、
        `tests/test_phase5c_person_mirror_vs_host.py` 和
        `tests/test_phase4_replay_scan.py` 作为 opt-in 例子、
        host-using 子集 ~150s → ~61s 的运行时收益。

    *Codex round*：抓出三个问题——"`[access]` —— pyodbc
    is Windows-only" 是事实错误（pyodbc 本身跨平台；
    Windows-only 的实际原因是 `pypyodbc` + `pywinauto`
    加上 pyodbc 绑定的 Windows-only Access ODBC/ACE
    驱动）；CI 排除项 "build the mdb or sqlite (Windows
    ODBC + Datadump required)" 过度概括（sqlite 严格说
    不需要 Windows ODBC；实际理由是 Datadump + MariaDB
    cache 都在 contributor 本机，不在 GHA runner——按
    builder 拆分了说明）；子节日期 "(added 2026-05-31)"
    比实际 commit 日期 2026-05-30 晚了一天，借此发现
    Phase 7 起 WORK_PLAN / AGENTS / README 里 37 个
    `(✅ landed 2026-05-31)` 标签全部错了一天——一并
    sweep 到 2026-05-30。

  - **Suite delta**：0——纯文档。

  - **不做**（按 §0.a + 2026-05-30 指示）：同 Phase 8
    的排除项。

  - **顺序**：9a → 9b。每步 codex sign-off + `git push`
    收尾，保持 Phase 5/6/7/8 的 codex-per-step 节奏。

  - **不再 retro-fit**：Phase 9 显式终止"每个阶段回头
    清理上一个阶段 prose" 这条递归链。Phase 9 子阶段
    paragraph 本身在写它们的同一个 commit 里就带了
    past-tense + ✅ 标签 + codex 注释，**不会**有 Phase 10
    再回来 retro-fit Phase 9 的 prose。如果未来贡献者
    看到这里有事实错误，直接改就行；自我引用的递归
    到这段为止。

## 9. 未决问题

**规划阶段已解决：**
- ✅ artisan 命令已找到：`db:export-to-sqlite`（`app/Console/Commands/ExportMysqlToSqlite.php`），辅助的索引/地址重建命令也定位完毕（见 §4b）。
- ✅ Avalonia headless：`Cbdb.App.Core` 全是 interface（`IEntryQueryService`、`IOfficeQueryService`、`IStatusQueryService`、`IGroupPeopleService`、`IPersonBrowserService`、`IPlaceLookupService`、`IDynastyLookupService`），SQLite 实现都在 `Cbdb.App.Data` 里。写一个小的 .NET 测试宿主直接 new `Sqlite*Service` 调用，**结构上可行**。阶段 3 用第一个查询做实证。
- ✅ Repo 名定为 `cbdb-access-avalonia-parity`，由本地 `gh` 在 `cbdb-project` org 下建。

**规划阶段已敲定：**
- ✅ **缓存**：生成的 Access `cbdb_data.mdb` 和 Avalonia `cbdb.sqlite` 都按 Datadump 文件名 + SHA 缓存。同一份 SHA 直接复用，除非 Datadump 换了或用户显式传 `--rebuild`。
- ✅ **Python → Docker 切换门槛**：**不**用工作日衡量。4a（1.3b）和 4b 实施期间，由用户**主动**触发 Codex review 检查 Python port 代码。如果**连续三轮 Codex review 仍然指出严重问题**，就把对应那一步切到 Docker MySQL 兜底。Codex review 由用户触发，不自动跑。
- ✅ **Codex CLI 调用默认参数**：`codex --dangerously-bypass-approvals-and-sandbox -c model=gpt-5.4 -c model_reasoning_effort=medium review --uncommitted --title "..."`。在本机 Windows 上，codex 默认 sandbox 会 `spawn setup refresh` 报错把所有 shell 命令屏蔽掉，所以需要 dangerous-bypass；`gpt-5.4` + `medium` 是 per-section gate 的基线，保证多轮 review 之间的发现可比。详见 `AGENTS.md`，以及在什么场景下需要偏离这套默认（如 CI 机器、有特别微妙不变量的环节）。
- ✅ **LICENSE**：Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International（CC BY-NC-SA 4.0）。
- ✅ **空 mdb 起步（1.3b）**：用 `pypyodbc.win_create_mdb()` —— 实测一行调用生成 172 KB 空 mdb。**不用** `pyodbc`（不存在文件直接报错）、**不用** ADOX/`win32com`（重）、**不用**在 repo 里 commit 模板（不可复现）。`pypyodbc` 加进 `[access]` extra 依赖，只用这一个函数；其他所有 mdb 操作继续走 `pyodbc`。
- ✅ **MariaDB 中间缓存（Phase 1.6）**：Phase 1.3b 在真实 Datadump 上撞到 Jet 的两个硬伤（2 GB 事务 buffer 上限、PK-on-duplicates `IntegrityError 23000`）后，确定把 MariaDB 中间层作为 sqlite_builder + mdb_builder 的**默认** import source。该缓存层**不**违反 §1 严格流水线规则禁止使用本机已有 user mdb 的条款 —— 它由我们自己从 Datadump 灌出来，靠 in-DB SHA provenance 行做缓存校验。Phase 1.6 之前的 `cbdb_parity.mysqldump` 直链路径保留为非 Docker 主机的 fallback (`source='datadump'`)。**本条决策与前文 "连续三轮 codex → Docker MySQL 兜底" 的触发条件是互补的**，不是替代 —— 那一条仍然约束 **SQLite builder 内部** Python 端口 vs Docker MySQL 的选择。

### Post-Phase-6 status (2026-05-30)

Phase 7b 收尾时回填，2026-05-30 加入。锚定 Phase 6 关
闭、Phase 7 开始的那一刻 suite 和 suppression 的快照。

**Suite-count 契约（Phase 6 close 的 canonical 数字 ——
commit `dddedc1`）：**

- 354 passed
- 6 skipped（每条都有显式文档化的原因，详见下面）
- 1 xfailed（`entry/all_jinshi_general_song` replay scan
  case：cbdb_replay 没有 ORDER BY，被截断的行集与
  Avalonia 的硬 LIMIT 上限不重合；详细原因写在
  `tests/test_phase4_replay_scan.py` 和
  `coverage/replay_scan_results.md` 里）。

这些数字锚定到 Phase 6 close commit，不锚定 HEAD ——
Phase 7 子阶段会以 additive 方式把 passed 数往上推
（按预期不会有 §0.b regression；详见上面 Phase 7 子阶段
的 delta 说明）。任何改这些数字的改动都要在 commit
message 里把 delta 记下来，方便后人 reconstruct。

**当前 §0.b 兼容的 pair tests（4 个）：** Tier 1
entry / office / status 通过
`cbdb_replay.lookat{entry,office,status}`（Phase 3c/3d/
3e） + Tier 2 kinships 通过 `cbdb_replay.lookatkinship`
（Phase 6a）。

**`reports/known_issues.md` 里的活跃 suppression 以及
让每条 re-arm 的条件：**

| 条目 | re-arm 条件 |
|---|---|
| `kinships_basic_person`（INNER vs LEFT JOIN orphan-kin 缺口） | cbdb-user-mdb-tests 加 LookAtKinship 的 LEFT JOIN 变体，**或** parity request 显式排除 orphan-kin fixture。Phase 7e 加了 executable assertion 锚定当前缺口形状。 |
| `associations_basic_person`（lookatassociations 没有 person_id 输入——question-shape 不匹配） | cbdb-user-mdb-tests 加 LookAtAssociations 的 per-person 变体。 |
| `phase5e_lookups`（group_people / place_lookup / dynasty_lookup 都没有 §0.b 兼容的 pair） | 对称：要么 cbdb-user-mdb-tests 加合适的 `lookat*` 模块（place options / GroupPeopleQueryResult 形状的变体 / `lookatdynasty`），要么 cbdb-desktop-app 收敛到现有 cbdb_replay 的 question shape（例如 `GetPeopleAtPlacesAsync` 匹配 `lookatplace`）。 |
| `tier2_per_person`（12 个 surface 没 cbdb_replay.lookat* 模块，外加 associations 交叉引用） | cbdb-user-mdb-tests 加 per-surface `lookat<surface>` 模块。Phase 6b 移除了 bridge 和 pair test；本 repo 下游没什么要清理的。 |
| `avalonia_gap (legacy)` Texts/Networks/AssociationPairs/Place | 每个 surface 独立 clear，对应 service 在 cbdb-desktop-app 落地。umbrella 条目一直挂到四个都到位；落地一个**不**会清这一行——只会缩窄剩下的缺口。per-surface 进度看 `coverage/avalonia_queries.yaml`，不要看这一行。 |

`known_issues.md` 里的 `events_basic_person` /
`postings_basic_person` / `office_basic` legacy 条目
是 Phase 5c-final 和 Phase 6b 退役对应代码路径之前的
历史 breadcrumb。它们**不是**活跃 suppression，也没有
re-arm 条件——只作为 commit-history context 保留。

以上所有 re-arm 条件都要改别的 repo，按 §0.a 不在本
repo 范围内，按 2026-05-30 用户指示也不开 issue 去
请求。所以这些 suppression 等上游独立行动。

**用户已确认本 repo 不做的 out-of-scope 工作：**

- F1 —— 对
  `cbdb-project/cbdb-access-avalonia-parity`（或任何其他
  repo）提 GitHub issue 跟踪 `known_issues.md` 条目。
  2026-05-30 起 `known_issues.md` 本身就是 canonical
  action list。
- F2 —— 对 `cbdb-user-mdb-tests` 或 `cbdb-desktop-app`
  提 GitHub issue 请求上面 re-arm 条件里点名的上游改动。

Phase 7 当时是 Phase 6 close 时所看到的本 repo 内部
backlog；执行中带出一个收尾审计（即 Phase 8），Phase 8
又带出两个收尾的 cosmetic 缺口（Phase 7 子阶段 prose 还
停在 planning future tense，AGENTS.md 还没引用 CI/
daemon），合并成 Phase 9。最终收尾详见下面的
Post-Phase-9 status 段。

### Post-Phase-9 status (2026-05-30)

Phase 9b 收尾。Phase 7 当时是 Phase 6 close 看到的本 repo
backlog；执行中 Phase 7 收尾审计带出 Phase 8 的四个子阶段
（8a daemon binding、8b 文案 sweep、8c report-dir 清理、
8d 回顾），Phase 8 收尾审计又带出 Phase 9 的两个子阶段
（9a Phase 7 sub-phase prose 改成回顾式、9b AGENTS.md
Phase 7/8 操作段）。Phase 9 关闭后，suite-count 契约是：

- **387 passed**（Phase 6 close 时是 354 → +33 净 delta：
  Phase 7c 加 4、Phase 7d 加 22、Phase 7e 加 1 个 case 但
  在 canonical dump 上当前 skip（orphan-kin 证明 case）、
  Phase 7f 加 3、Phase 7h 加 4；Phase 7a/7b/7g 纯文档 /
  CI / lint，加 0 个 passing case；所以 Phase 7 净加
  4 + 22 + 0 + 3 + 0 + 4 = 33。Phase 8a 把已有的 Phase 7h
  daemon smoke test 绑到 session fixture，没改测试数。
  354 + 33 = 387）。
- **7 skipped**——都有文档：
  - 3 个 `replay_scan[entry/…_indexyears/_entryyears]`
    case，Avalonia EntryQueryRequest 无法表达
    `addr_field='person'`（上游 Avalonia 缺口；
    见 `coverage/matrix.md` Tier 1 第 2 行）。
  - `replay_scan[status/empty_codes]` 和
    `replay_scan[office/empty_codes]`（cbdb_replay picker
    契约对空 filter 返回零行，而 Avalonia 不带过滤跑；
    bridge 无法同时满足两种语义）。
  - `test_phase5c_person_mirror_vs_host::test_postings_mirror_vs_host`
    （5c-final 之后 postings mirror 是 `NotImplementedError`；
    嵌套 PersonPostingItem wire format 与 raw-row diff 不兼容）。
  - `test_phase4_kinships_pair::test_kinships_pair_orphan_kin_documented_divergence`
    （canonical 2026-04-30 Datadump 上 KIN_DATA 0 个 orphan；
    任何未来出现 orphan 的 dump 会自动 arm）。
- **1 xfailed**——`replay_scan[entry/all_jinshi_general_song]`，
  cbdb_replay 返回 ~40k 行而 Avalonia 截 10000 行没有对齐
  ORDER BY；语义对齐（dynasty-filter probe 已验证），
  只是行集不重合。

这些数字锚定到 Phase 9 close（commit `da1c6d2`）。Phase 9
纯文档，suite count 没动，继承 Phase 8 close 的锚点。后续
任何动这些数字的改动都要把 delta 写到 commit message 里。

Phase 8a 兑现了 Phase 7h daemon 的运行时收益：host-using
子集（Phase 5c + replay_scan kinship + 7h 本身）在 daemon
bind 下从 ~150 秒降到 ~61 秒。完整 `pytest tests/` 大约
~222 秒——剩下的成本是 daemon 改不了的非 host 部分
（构建流水线、mariadb cache、lint setup）。

**已抑制的活跃条目（再次确认 re-arm 条件）：**

| 条目 | re-arm 条件 |
|---|---|
| `kinships_basic_person` (INNER vs LEFT JOIN orphan-kin gap) | `cbdb-user-mdb-tests` 加 LEFT JOIN 变体 LookAtKinship；或 parity request 显式排除 orphan-kin fixture。Phase 7e 加了 executable assertion 锚定当前缺口形状。 |
| `associations_basic_person` (lookatassociations 没有 person_id) | `cbdb-user-mdb-tests` 加 LookAtAssociations 的 per-person 变体。 |
| `phase5e_lookups` (group_people / place_lookup / dynasty_lookup 都没有 §0.b 兼容 pair) | 对称：`cbdb-user-mdb-tests` 加合适 `lookat*` 模块，或 `cbdb-desktop-app` 收敛到现有 cbdb_replay 形状。 |
| `tier2_per_person` (12 个 surface 没 cbdb_replay.lookat*) | `cbdb-user-mdb-tests` 加 per-surface `lookat<surface>` 模块。Phase 6b 已完成本 repo 侧清理。 |
| `avalonia_gap (legacy)` Texts/Networks/AssociationPairs/Place | 每个 surface 独立 clear，对应 service 在 cbdb-desktop-app 落地。umbrella 一直挂到四个都到位。 |

所有以上 re-arm 条件都需要改动其他 repo，按 §0.a 不在本
repo 范围内，按 2026-05-30 用户指示也不开 issue 去请求。
所以这些 suppression 等上游独立行动。

Phase 9 关闭后 repo 真正进入稳态：本 repo 内没有待办。
Phase 9 自己显式终止了"每个阶段回头清理上一个阶段 prose"
的递归链（见 Phase 9 段落末尾的 "不再 retro-fit" 说明）。
下一次变化要么是下游使用者在 `known_issues.md` 里把过时
suppression 清理掉，要么是上游 commit（`cbdb-user-mdb-tests`
/ `cbdb-desktop-app`）让某条之前 skip 的 test 重新 arm。
