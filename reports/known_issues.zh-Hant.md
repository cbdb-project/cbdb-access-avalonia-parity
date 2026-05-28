# 已知差異 — 已從閘門條件中豁免

> 繁體中文版。權威版本仍為 [`known_issues.md`](known_issues.md)；本檔僅作為閱讀輔助，若兩份內容有出入請以英文版為準。

本檔列出 Access ↔ Avalonia 之間，差異測試框架已經發現並分析過、且
維護者已決定後續執行**不應**阻擋 parity 閘門的項目。

本列表由人手維護 — `cbdb_parity.summary_report.write_summary` 會在
頂層 `SUMMARY.md` 儀表板中引用本檔,但永遠不會覆寫本檔。

## 格式

每個條目使用以下結構:

```
### <query_id> — <一行標題>

- **首次發現**: YYYY-MM-DD,Datadump SHA `<short-sha>`
- **側別**: Avalonia / Access / 雙方
- **類別**: 形狀不符 / 資料版本漂移 / Avalonia 缺口 / Access 缺口 / 框架瑕疵
- **描述**: 一段說明發生了什麼問題
- **根本原因**: 一段說明(細節連結到該查詢的 `hypothesis.md`)
- **豁免理由**: 為何刻意不阻擋閘門

每個條目最後加入:

- **豁免至**: 一個 Datadump 日期、一個 commit SHA、「永久」,
  或者「直到 Avalonia 新增 X」 — 任何能讓豁免具有時間邊界的條件。
```

## 經實證確認安全(已不再是問題)

### BIT 欄位完整性 — bool-1 回讀錯誤在此**不會**觸發

- **驗證日期**: 2026-05-28,Datadump SHA `ed294faed44b`
- **側別**: Access(透過 pyodbc + Microsoft Access Driver 回讀)
- **描述**: `accessAndMySQLTransfer/README.md §3` 警告 Access 在
  回讀 BIT 欄位時無論存入何值都會傳回 `1`(「所有布林值都變成 true」
  的問題)。我們的 verbatim ipynb-pattern mdb 建構器將 MySQL BIT
  對應到 Access BIT(與產生正式版 `cbdb.mdb` 的 ipynb 一致);
  另一個 SMALLINT 改寫的方案在 303 MB 處因 Jet 2 GB temp-file
  洩漏崩潰。
- **實證檢查**(BIOG_MAIN.c_female 直方圖,MariaDB 與建構好的 Access
  mdb 互比): `{None: 24,265, 0: 576,616, 1: 57,607}` — 雙方完全一致。
  回讀錯誤在本資料集的 pyodbc + Microsoft Access Driver 路徑上**不會**
  觸發,因此 parity 測試不會被它誤導。
- **若日後真的觸發了**: 該錯誤會呈現為 Access 直方圖
  `{None: 24265, 1: 634223}`(每個 0 都被讀成 1)。重檢容易;
  每次拿到新 Datadump SHA 後重跑上述檢查,若有偏差再加入 known_issues
  條目即可。

## 目前已豁免

### office_basic — Avalonia 引用不存在的 `pto.c_appt_type_code`

- **首次發現**: 2026-05-28,Datadump SHA `ed294faed44b` (cbdb_data_20260527.tar.gz)
- **側別**: Avalonia
- **類別**: Avalonia 缺口(schema 漂移)
- **描述**: `cbdb-desktop-app/Cbdb.App.Data/SqliteOfficeQueryService.cs:307`
  SELECT 了 `pto.c_appt_type_code`,而第 365 行的 JOIN 也讀取它。
  但 `POSTED_TO_OFFICE_DATA` 表上只有 `c_appt_code`。在真實 CBDB
  資料上這個查詢會丟出
  `sqlite3.OperationalError: no such column: pto.c_appt_type_code`,
  所以 office-pair smoke 測試完全無法跑 Avalonia 那一側。這正是
  parity 框架設計用來捕捉的那一類發現 — Avalonia 程式碼引用了
  正式版 MySQL Datadump 匯出的 CBDB SQLite 中**並不存在**的欄位。
- **根本原因**: Avalonia 的提交歷史很可能把 Avalonia 查詢裡的
  `c_appt_code` 改名為 `c_appt_type_code`,卻沒有在 SQLite 匯出端做
  相應改名(SQLite 端仍從 MySQL 的 `c_appt_code` 推導)。又或者該
  改名是為了某個未真正落地的 schema migration 而做的預先動作。
- **豁免理由**: 這是個真正的 Avalonia 缺陷,需要在 `cbdb-desktop-app`
  上游修復。此處豁免可以避免 parity 閘門因 office_basic 而長期變紅,
  同時上游修復處於進行中。
- **豁免至**: Avalonia `SqliteOfficeQueryService.cs` 改為 SELECT 實際
  存在的欄位(`c_appt_code`),或 SQLite 匯出層加入別名。

### postings_basic — Avalonia 引用不存在的 `pto.c_appt_type_code`

- **首次發現**: 2026-05-28,Datadump SHA `ed294faed44b`
- **側別**: Avalonia
- **類別**: Avalonia 缺口(schema 漂移)
- **描述**: `cbdb-desktop-app/Cbdb.App.Data/SqlitePersonBrowserService.cs`
  的 GetPostingsAsync 在
  `LEFT JOIN APPOINTMENT_CODES appt ON appt.c_appt_code = pto.c_appt_type_code`
  中 SELECT 了 `pto.c_appt_type_code`。與 `office_basic` 是同一個
  上游缺陷: schema 上的欄位是 `pto.c_appt_code`,而非
  `pto.c_appt_type_code`。在真實 CBDB SQLite 上會丟出
  `sqlite3.OperationalError: no such column: pto.c_appt_type_code`,
  所以 postings-pair 測試完全無法跑 Avalonia 那一側。
- **根本原因**: 與上方 office_basic 條目完全相同的改名不一致。
  上游修一次提交就能同時解決兩者。
- **豁免理由**: 真正的 Avalonia 缺陷,需上游修復。
  `tests/test_phase4_postings_pair.py` 內建了自動跳過模式 —
  捕捉到該 OperationalError 時就 skip,並指向本檔。
- **豁免至**: 與 office_basic 相同 — Avalonia 改為 SELECT
  `c_appt_code`,或 SQLite 匯出層加入別名。

### kinship_expanded_network — Avalonia GetExpandedKinshipsAsync 的 Python 移植被延後

- **首次發現**: 2026-05-28
- **側別**: 框架(Python 移植尚未實作)
- **類別**: 框架缺口
- **描述**: `tests/test_phase4_kinships_pair.py` 只涵蓋了
  直接(`expandNetwork=false`)分支。Avalonia
  `SqlitePersonBrowserService.GetExpandedKinshipsAsync` 中的
  `expandNetwork=true` 分支會做帶有深度限制(`maxUp=2, maxDown=2,
  maxMarriage=1, maxCollateral=1, maxLoop=10`)的迭代圖遍歷 — 一個
  使用 `KinshipTraversalState.Extend` 和 `ReduceKinship` 的確定性
  狀態機。移植到 Python 屬於機械性工作,但並非小工程,會讓
  `cbdb_parity.avalonia_kinships` 大幅膨脹。
- **根本原因**: 人力配置 — Tier 2 階段優先追求 SQL 層級的 parity。
- **豁免理由**: Tier 2 已經驗證 1-hop SQL 在 SQLite 與 Access 上一致。
  遞迴遍歷純粹屬於後處理 — 是否移植取決於是否有獨立的 Python 端
  狀態機實作,與 parity 契約本身無關。
- **豁免至**: GetExpandedKinshipsAsync 的 Python 移植落地
  (可能位於 `cbdb_parity.avalonia_kinships_expanded`)。

### group_data_demographics — 僅 Access 有;Avalonia 無對應

- **首次發現**: 2026-05-28
- **側別**: Avalonia(缺口)
- **類別**: 僅 Access 的流程
- **描述**: Access `Form_LookAtGroupData` / `CmdRun`
  (`groupdata_demographic_stats`)為一個人物群計算人口統計分布
  (出生年直方圖、status 頻率等)。Avalonia 的
  `IGroupPeopleService.QueryAsync` 傳回的是「按關係分組的每人記錄」
  (等同於對一批人逐一跑 Tier 2 per-person accessor 後串接的結果);
  它**不會**產生人口統計。兩者是名副其實的不同問題,並非形狀不符。
- **根本原因**: Avalonia 未實作人口統計聚合流程。
- **豁免理由**: 沒有可比的對象。一旦 Avalonia 新增人口統計聚合,
  本條目應被一個配對測試取代。
- **豁免至**: Avalonia 新增人口統計聚合的服務或方法。

### entry_all_jinshi_general_song — LIMIT 截斷 + 缺 ORDER BY(**不是**語意分歧)

- **首次發現**: 2026-05-28,Datadump SHA `ed294faed44b`,由
  `tests/test_phase4_replay_scan.py` 暴露。
- **側別**: 雙方(測試設計問題)
- **類別**: 框架缺口(測試輸入對於行數上限來說太寬)
- **描述**: 對於「Song 朝所有 entry」這個無其他過濾條件的查詢,
  掃描首輪報告兩側各 4919 / 4993 行、僅 144 行匹配。**最初判斷
  (語意分歧)是錯的** — 見下方「實證澄清」。
- **實證澄清**(2026-05-28 在 limit=10000 下的探針): 比較
  三個 Avalonia 變體與三個 cbdb_replay 模式:

  | Avalonia 變體                | rep:dynasty | rep:entry-960-1279 | rep:index-960-1279 |
  |---|---|---|---|
  | `A_dynasty_ids=(15,)`        | **9871/9871 (100%)** | 6483 | 3952 |
  | `B_use_entry_year_range`     | 9812 | **9933/9933 (100%)** | 4211 |
  | `C_use_index_year_range`     | 9268 | 6309 | **9802/9802 (100%)** |

  每個 Avalonia 變體都與其對應的 cbdb_replay 模式 100% 對齊。
  原本失敗有兩個疊加原因,**都不是**語意分歧:

  1. **Avalonia LIMIT 上限**:
     `SqliteEntryQueryService.cs:329` 把 `request.Limit` 鉗在
     `[1, 10000]`。cbdb_replay 的 `year_mode='dynasty'` 對 Song
     返回約 40,621 個 unique `(person_id, sequence)` — Avalonia
     永遠無法返回超過 10,000 行。
  2. **cbdb_replay 沒有 ORDER BY**: 見 `lookatentry.py`,
     `grep ORDER` 找不到結果。pandas 按 Access ODBC 給出的物理
     /索引順序讀取;Avalonia 的
     `ORDER BY entry_label, c_year, c_personid, c_sequence` 得到
     截然不同的前 10,000 行。

  在 limit=5000 (測試用值)下,兩側的前 5000 行切片在
  `person_id` 上**零重疊** —— 它們是同一個約 40k 行的母集合的
  兩個互不相交的切片。
- **根本原因**: 測試所問的問題的真實結果集超過了 Avalonia 寫死
  的 LIMIT 上限。兩側語意是正確的;只是比對視窗不夠大。
- **豁免理由**: 在掃描中標記為 `xfail`(不是 `skip`),
  以便任何修復都會以 XPASS 的形式被察覺。
- **豁免至**: 滿足下列其一:(a) 上游 cbdb-user-mdb-tests 用例
  收窄到能在 10000 行內塞下的子集(例如 `entry_codes=[36]`
  只取進士);(b) Avalonia 調高 LIMIT 上限;(c) cbdb_replay
  增加 ORDER BY,使其前 N 行切片成為確定性結果可比對。
- **報告位置**: `reports/replay_scan/entry__all_jinshi_general_song/`。

### avalonia_gap — Texts / Networks / AssociationPairs / Place

- **首次發現**: 2026-05-28
- **側別**: Avalonia(缺口)
- **類別**: 僅 Access 的流程(4 個獨立功能)
- **描述**: Access 有測試框架驅動的流程: `texts_basic_search`
  (Form_LookAtTexts)、`network_personal_expansion`
  (Form_LookAtNetworks)、`assocpairs_path_queries`
  (Form_LookAtAssociationPairs)、以及 `place_basic_search`
  (Form_LookAtPlace)。Avalonia 對這四個流程都沒有對應的服務
  (見 `coverage/avalonia_queries.yaml`)。
- **根本原因**: Avalonia 偏向 person-centric 的流程
  (PersonBrowser 的 per-person accessors);text/place/network-centric
  流程尚未從 Access 移植過來。
- **豁免理由**: 在 Avalonia 實作其中至少一項之前無從比較。
  `coverage/matrix.md` 列出了各自條目;本條目作為快速交叉引用。
- **豁免至**: Texts / Networks / AssociationPairs / Place 至少其一
  在 `cbdb-desktop-app` 落地。

## 豁免到期管理

依 WORK_PLAN §7,本檔每個條目都應該在 `cbdb-project` 的 issue tracker
中對應一個追蹤 issue。本檔只是快速參考;canonical 行動清單在
issue tracker。
