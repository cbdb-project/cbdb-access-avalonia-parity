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

### 4a. Datadump → Access "data" mdb
- 取 `DATADUMP_DIR` 中最新归档，解压到临时目录。
- 把 `$ACCESS_MYSQL_TRANSFER_REPO/mysql2access.ipynb` 与 `$MYSQL2ACCESS_DIR/mysql2access.ipynb` 中的 MySQL→Access 流程脚本化为 `scripts/build_access_data.py`（不再用 notebook），复用 `$MYSQL2ACCESS_DIR` 下已有的表/字段/主键 xlsx。
- 输出 `BUILD_OUTPUT_DIR\cbdb_data.mdb`，与固定的 `CBDB_BJ_User.mdb` 组成完整 Access 栈。

### 4b. Datadump → Avalonia SQLite

**主路线 —— 纯 Python 端口。** 决定命令是 `cbdb-online-main-server/app/Console/Commands/ExportMysqlToSqlite.php`（signature 为 `db:export-to-sqlite`），但它的输入是**在跑的 MySQL 连接**，不是 tar.gz。计划是把该命令的*逻辑*（以及它依赖的索引/地址重建命令 —— `RebuildIndexAddress.php`、`RebuildIndexYear.php`、`RebuildNameSearchIndex.php`、`RegenerateAddresses.php`、`ImportTradSimpMap.php`）直接 port 到 Python，使流水线变成：

&nbsp;&nbsp;&nbsp;&nbsp;`tar.gz` → Python 解析 MySQL dump → 直接写 `cbdb.sqlite`

这样每次 run 不需要起 MySQL，pipeline 自包含。输出 `BUILD_OUTPUT_DIR\cbdb.sqlite`。用现有的 `cbdb-user-mdb-tests/data/cbdb_online_sqlite/cbdb_20260328.sqlite3`（虽是 3 月底的旧版）做结构层面 sanity check。

**兜底路线 —— Docker MySQL。** 如果纯 Python 端口不现实（比如某条 artisan 命令依赖 MySQL 专属的、不好翻译的特性，如 collation-sensitive 名字检索索引），就退回到：`tar.gz` → 灌进一个一次性的 `mysql:8` Docker 容器 → 在该容器对应的 Laravel 连接上跑真正的 `php artisan db:export-to-sqlite` → 把 `cbdb.sqlite` 拷出来。封装为 `scripts/build_sqlite_docker.py`，仅当 Python 主路线失败或结果不一致时启用。

**决策点。** 阶段 1 必须**二选一并定下来**，再进阶段 2 —— 两条路同时维护不是目标。在跑任何 diff 之前先校验 BIOG_MAIN、ADDR_CODES、OFFICE_CODES 等关键表的行数与 Access 端一致，证明"同数据、两格式"。

### 4c. 单入口编排
`scripts/build_all.py` 一次完成 4a + 4b，把使用的 Datadump 文件名与 SHA 写进 `build_manifest.json`，让每份报告都能溯源到具体数据版本。

## 5. 查询覆盖清单
1. 爬 `cbdb-desktop-app/Cbdb.App.Avalonia` + `Cbdb.App.Core`，列出 Avalonia 当前实现的所有查询/视图（人物查询、官职、亲属、社会关系、地名等），输出 `coverage/avalonia_queries.yaml`：`{id, name, params, status: implemented|missing}`。
2. 爬 `cbdb-user-mdb-tests`（重点 `test_vba_*.py`、`cbdb_driver/`、`cbdb_replay/`），列出现有框架能驱动的所有 Access 查询，输出 `coverage/access_queries.yaml`。
3. 合并为 `coverage/matrix.md`：Avalonia 功能 ↔ 对应 Access 查询 ↔ 状态（已配对 / 仅 Avalonia / 仅 Access / 双缺）。

## 6. 差分测试框架
- 基于 pytest，沿用 `cbdb-user-mdb-tests/tests/test_vba_differential.py` 与 `cbdb_driver`/`cbdb_replay` 的差分模式。
- `matrix.md` 中每一对查询：
  1. **Access 端** — 用现有 `cbdb_driver`（pywinauto）驱动真实 Access UI，或对生成的 `cbdb_data.mdb` 走 pyodbc 直接发 SQL（看查询是否纯 UI）。
  2. **Avalonia 端** — 两种方案先做 spike：(a) Appium/FlaUI 驱动 UI；(b) 写一个小的 .NET 测试宿主直接调用 `Cbdb.App.Core` 的查询服务并返回 JSON。(b) 更快更稳，默认优先用 (b)，除非要校验 UI 绑定本身。
  3. 把两端结果归一化到同一个记录结构，排序后 diff。
  4. 每个查询写 `reports/<query_id>/{access.json, avalonia.json, diff.json, summary.md}`。
- 公共参数夹具（人物 ID、官职 ID、亲属起点等）放 `tests/fixtures/`，两端用同一份输入。

## 7. 报告与根因循环
- 顶层 `reports/SUMMARY.md`：总查询数、已配对、通过、失败、Avalonia 缺失。
- 每个失败查询保留：输入、两端输出、diff、`hypothesis.md`（人工或 LLM 写的根因，例如 schema 不一致、缺 join、代码表漂移等）。
- `reports/known_issues.md` 记录已确认的 Avalonia 缺口，避免重复噪声。

## 8. 分阶段
- **阶段 0（1–2 天）**：repo 初始化、`.env`/`.env.sample`、`.gitignore`、推到 `cbdb-project` 组、跨 repo `git pull` 工具。
- **阶段 1（3–5 天）**：Datadump→Access（移植 `mysql2access`）、Datadump→SQLite（移植 `cbdb-online-main-server` artisan）、行数一致性校验。
- **阶段 2（2–3 天）**：覆盖清单 + 配对矩阵。
- **阶段 3（1–2 周）**：差分框架骨架 + 头 3 个配对查询端到端（建议：人物基本查询、官职查询、亲属查询），打通两端驱动。
- **阶段 4（持续）**：按查询逐个扩覆盖，每个新查询同时产出 diff 报告与（如不一致）根因记录。

## 9. 未决问题

**规划阶段已解决：**
- ✅ artisan 命令已找到：`db:export-to-sqlite`（`app/Console/Commands/ExportMysqlToSqlite.php`），辅助的索引/地址重建命令也定位完毕（见 §4b）。
- ✅ Avalonia headless：`Cbdb.App.Core` 全是 interface（`IEntryQueryService`、`IOfficeQueryService`、`IStatusQueryService`、`IGroupPeopleService`、`IPersonBrowserService`、`IPlaceLookupService`、`IDynastyLookupService`），SQLite 实现都在 `Cbdb.App.Data` 里。写一个小的 .NET 测试宿主直接 new `Sqlite*Service` 调用，**结构上可行**。阶段 3 用第一个查询做实证。
- ✅ Repo 名定为 `cbdb-access-avalonia-parity`，由本地 `gh` 在 `cbdb-project` org 下建。

**规划阶段已敲定：**
- ✅ **缓存**：生成的 Access `cbdb_data.mdb` 和 Avalonia `cbdb.sqlite` 都按 Datadump 文件名 + SHA 缓存。同一份 SHA 直接复用，除非 Datadump 换了或用户显式传 `--rebuild`。
- ✅ **Python → Docker 切换门槛**：**不**用工作日衡量。阶段 1 §4b 期间，由用户**主动**触发 Codex review 检查 Python port 代码。如果**连续三轮 Codex review 仍然指出严重问题**，就把出问题的那条命令（或整条 §4b pipeline）切到 Docker MySQL 兜底。Codex review 由用户触发，不自动跑。
- ✅ **LICENSE**：Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International（CC BY-NC-SA 4.0）。
