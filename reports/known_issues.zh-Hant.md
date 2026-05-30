# 已知差異 — 已從閘門條件中豁免

> 繁體中文版。權威版本仍為 [`known_issues.md`](known_issues.md)；本檔僅作為閱讀輔助，若兩份內容有出入請以英文版為準。
>
> **範圍提醒**: 本倉庫是一個**檢測 / parity 框架**。它的職責是把
> Avalonia ↔ Access 不一致暴露出來、在這裡記錄、並讓 parity 閘門
> 優雅地跳過。**Avalonia 程式碼的修復屬於上游
> `cbdb-desktop-app` 倉庫**，不在此處。即便 parity 測試讓 bug
> 一目了然，本倉庫**不應**修改 Avalonia 源碼。下面的條目維護到
> 上游維護者修補為止。

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

### office_basic / postings_basic / GroupPeople — Python 框架讀不了內插 `$@"…{appointmentCodeExpr}…"` SQL

- **首次發現**: 2026-05-28,Datadump SHA `ed294faed44b`
- **側別**: 框架(Python 鏡像層)
- **類別**: 鏡像缺口 — **並非** Avalonia bug
- **描述**: `cbdb-desktop-app/Cbdb.App.Data/SqliteOfficeQueryService.cs`、
  `SqlitePersonBrowserService.cs` (`GetPostingsAsync`)、以及
  `SqliteGroupPeopleService.cs` 全部都用 C# **內插**逐字字串
  (`$@"…appt.c_appt_code = {appointmentCodeExpr}…"`)構造
  POSTED_TO_OFFICE_DATA SQL,其中 `appointmentCodeExpr` 由
  `SqliteSchemaCompatibility.GetPostingAppointmentCodeExpressionAsync`
  在執行時計算 — 它在執行時讀取 SQLite schema,挑選實際存在的
  `pto.c_appt_code` 或 `pto.c_appt_type_code`。所以**真正的 C#
  程式碼並沒有 bug** — 它在執行時處理兩種欄位名變體。
- **為什麼框架還是看到它壞**: Python parity 鏡像
  (`cbdb_parity.avalonia_query_sql.extract_sql_blocks`)
  刻意排除帶 `$@"…"` 內插的區塊,因為它們的 `{placeholder}`
  替換項在 C# 執行時才確定 — 把它們當可執行 SQL 回傳會破壞
  下游 sqlite3 / pyodbc 呼叫端。所以 postings / office /
  GroupPeople 的 SQL 抽取會回傳空,相依測試丟出
  `LookupError` ("no SQL block … contains …")。先前記錄的
  `sqlite3.OperationalError: no such column` 說法是錯的 —
  那是我們先前一次誤導性「上游修復」嘗試的後果,我們把欄位名
  硬編碼,反而擊敗了執行時 shim。
- **根本原因**: parity 框架「從 C# 抽 SQL 再用 Python sqlite3
  跑」的方法,無法重現 C# 用 schema 內省在執行時決定 SQL 的
  程式路徑。
- **豁免理由**: 不是 Avalonia bug — 上游沒有需要修的。
  正確的解法是 Phase 5(透過 `Cbdb.App.ParityHost` 跑真正的 C#),
  完全繞過 SQL 抽取,拿到執行時解析後的字串。Phase 5 落地之前,
  受影響的三個測試(`tests/test_phase3d_office_pair.py`、
  `tests/test_phase4_postings_pair.py`,以及 `office-*` 掃描案例)
  捕捉 LookupError 自動跳過。
- **豁免至**: `Cbdb.App.ParityHost` (Phase 5) 落地並把受影響的
  測試切換過去。

### [已解決 2026-05-28] kinship_expanded_network — Python 移植已落地

`cbdb_parity/avalonia_kinships_expanded.py` 現已完整鏡像
`GetExpandedKinshipsAsync` 從頭到尾(KinshipReductionRules dict、
ReduceKinship / ResolveKinshipDisplay / Extend / BuildNotes、
maxLoop=10 BFS、深度上限、最終 OrderBy chain)。
`tests/test_phase4_kinships_expanded.py` 斷言六項該移植的結構不變式
(unique-by-kin、衍生列的深度上限、direct ⊆ expanded、單調計數、
確定性)外加一個 ReduceKinship 單元測試。原始條目保留於下作為紀錄。

---

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

### avalonia_gap — Texts / Networks / AssociationPairs / Place / GroupData

**狀態 (2026-05-28)**: 已記錄為永久缺口。在 `cbdb-desktop-app` 中
實作這些上游服務需要每項約 250 行 C# (request/record/interface/
SQLite 實作) 再加上對應的 parity Python 鏡像與 pair test。
不在現階段 parity-completion 工作範圍內;以下為每個服務的實作
切入點文件,供未來 Avalonia 貢獻者使用。

**給實作者的指引**:每個 `cbdb_replay/lookat*.py` 內含一份
**部分參考實作**,可作為起點 — 但須注意這些 replay 模組僅涵蓋
Access form 的**最簡 smoke-test 子分支**。Access VBA form 支援的
選項遠多於 cbdb_replay 目前模型(例如 multi-hop 圖遍歷、
完整人口統計聚合、二次網路)。Avalonia 作者應:

1. 在 `Cbdb.App.Core/<X>QueryRequest.cs` 鏡像 request 形狀
2. 在 `Cbdb.App.Core/<X>QueryRecord.cs` 鏡像每一列
3. 加入 `Cbdb.App.Core/I<X>QueryService.cs` (`Task<…QueryResult>
   QueryAsync(string sqlitePath, …QueryRequest request, …)`)
4. 以 cbdb_replay SQL 為**起點**;對照
   `cbdb-user-mdb-tests/tests/golden_helpers.py` 內的 Access VBA
   以及原始 `Form_LookAt*.vb` / `.frm` 模組(若有),補齊 form
   實際支援的完整選項矩陣。
5. 加上 parity Python 鏡像與 Access bridge,依照現有 Entry/
   Status/Office bridge 模式。

**各功能切入點**(每項附上 replay 起點與 cbdb_replay **尚未**
涵蓋的範圍):

- **Texts**(最單純、最完整): `cbdb_replay/lookattexts.py` 約
  第 50-200 行。回傳 `(person, text, role)` 三元組,按
  `biblcat_codes` 過濾。15 column SELECT × 3 INNER JOIN;
  端到端移植約 150 SLOC。cbdb_replay 在此項相對於 Access 的
  覆蓋度尚算完整。
- **Place**: `cbdb_replay/lookatplace.py`。起點:僅實作
  `source='individual'` 模式。Access `Form_LookAtPlace.vb`
  額外暴露 checkbox 驅動的來源模式 `Kin`、`Office`、`Status`、
  `Entry`、`Institution`、`AssocPerson`、`AssocPlace`,replay
  模組皆未模型化。Avalonia 實作者應查閱 VBA 取得完整的來源
  模式矩陣。
- **Networks**: `cbdb_replay/lookatnetworks.py`。起點:僅
  1-hop 非親屬關聯邊。Access `network_personal_expansion`
  支援多跳遍歷、kin+association 混合邊、深度限制擴展 — 是
  replay seed 之上相當可觀的延伸。
- **AssociationPairs**: `cbdb_replay/lookatassociationpairs.py`。
  起點:僅直接 ASSOC 邊。Access `assocpairs_path_queries`
  支援 path-style queries (A → B 經中介人物),replay 尚未
  模型化。
- **GroupData**: `cbdb_replay/lookatgroupdata.py`。起點:僅
  回傳匯入人物的 base list。Access `groupdata_demographic_stats`
  產出 histograms / frequency tables / cross-tabulations —
  真的是與任何現有 Avalonia 服務形狀不同的東西,需要產品層
  決策是否在 Avalonia 加入聚合功能。

(歷史 Tier 1「Avalonia gap」交叉引用保留於下。)

### avalonia_gap (legacy entry) — Texts / Networks / AssociationPairs / Place

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

### kinships_basic_person — cbdb_replay INNER JOIN 漏掉 orphan kin（2026-05-30 加入）

- **首次發現**: 2026-05-30，Phase 6a 重寫期間
- **側別**: Access（cbdb_replay 範圍）
- **類別**: row-set 契約缺口
- **描述**: Avalonia 的 `GetKinshipsAsync`（expandNetwork=false）
  用 `LEFT JOIN BIOG_MAIN kin ON kin.c_personid = kd.c_kin_id`，
  所以 `c_kin_id` 沒有 BIOG_MAIN 對應行的 KIN_DATA 行仍會
  以 `kin_name_chn` / `kin_name` = NULL 出現在結果中。
  `cbdb_replay.lookatkinship.run` 用
  `INNER JOIN BIOG_MAIN AS BIOG_MAIN_1`，會悄悄丟掉這些 orphan。
- **根本原因**: cbdb_replay 的 LookAtKinship 歷史上是個顯示
  query（Access UI 不會顯示 orphan kin），所以 INNER JOIN
  在那個語境下可以接受。Avalonia 的新 per-person accessor 是
  data API，把 orphan 留給 caller 處理。兩者面向不同。
- **依然存在的覆蓋**: Phase 5c mirror-vs-host
  （`test_phase5c_person_mirror_vs_host.py`）依然會帶著 orphan
  跑 Avalonia 側，Avalonia 端的 oracle 沒有丟。
- **豁免理由**: 這是 `cbdb-user-mdb-tests` 的 query 範圍差，
  不是 CBDB 資料 bug。harness 應該把它**暴露出來**（pair test
  一旦遇到 canonical fixture 上出現 orphan kin 就會 row-count
  失敗），而不是在 bridge 裡用轉寫的 LEFT JOIN 掩蓋——那會
  違反 §0.b。
- **豁免至**: `cbdb-user-mdb-tests` 加入一個用 LEFT JOIN 的
  LookAtKinship 變體，或 parity request 明確排除有 orphan kin
  的 fixture。蘇軾（1762）目前沒有 orphan kin，所以現行 pair
  test 通過。

### associations_basic_person — lookatassociations 答錯問題（2026-05-30 加入）

- **首次發現**: 2026-05-30，Phase 6a 重寫期間
- **側別**: Access（cbdb_replay 範圍）
- **類別**: question-shape 不匹配
- **描述**: `cbdb_replay.lookatassociations.AssocQueryInputs`
  暴露 `(assoc_codes, addr_ids, year_filter)`，但**沒有
  `person_id`**。它的 SQL 是 `WHERE c_assoc_code IN (...)`，
  回答的是「匹配這些 association codes 的所有行」，不是
  Avalonia `GetAssociationsAsync(personId)` 回答的「person X
  的所有 associations」。
- **根本原因**: LookAtAssociations 歷史上在 Access UI 裡是
  code-driven 的跨 person 查詢（例如「所有 assoc_code='teacher'
  的行」）。Avalonia 的 per-person accessor 是不同的 question
  shape，cbdb_replay 沒有對應模組。
- **依然存在的覆蓋**: Phase 5c mirror-vs-host
  （`test_phase5c_person_mirror_vs_host.py`）依然 gate Avalonia
  端，上游 C# 那一半依然有覆蓋。
- **豁免理由**: 按 §0.b，跨引擎檢查唯一可接受的方式是
  (a) 抓出目標 person 用過的所有 assoc_codes，(b) 用那些
  codes 調 lookatassociations，(c) 按 personid 後過濾——
  這整個流程本身就是轉寫模式（Python 中介了一個上游不執行
  的派生）。
- **豁免至**: `cbdb-user-mdb-tests` 加入 LookAtAssociations
  的 per-person 變體。和 `tier2_per_person` 同組追蹤；
  Phase 6b 已在同一批 commit 裡刪掉 bridge 和 pair test。

### phase5e_lookups — 不存在 §0.b 兼容的 pair test（2026-05-30 加入）

- **首次發現**: 2026-05-30，Phase 6c 期間
- **側別**: 雙側（question-shape 不匹配）
- **類別**: 結構上無法跨引擎 diff
- **描述**: Phase 6c 原本計畫把 `group_people` 和 `place_lookup`
  從 Phase 5e smoke-only 升級到走 `cbdb_replay.lookatgroupdata`
  / `cbdb_replay.lookatplace` 的完整 pair test。檢查後發現兩個
  cbdb_replay 模組都答錯了問題：

  - **place_lookup**: Avalonia 的
    `IPlaceLookupService.GetPlacesAsync` 返回 UI 的
    **place 下拉選項**——資料庫中每一個 place。最接近的
    cbdb_replay 模組 `lookatplace.run` 返回 **給定地址處
    的人**（BIOG_MAIN 按 `c_index_addr_id IN (addr_ids)`
    過濾）。不同 question shape。
  - **group_people**: Avalonia 的 `GroupPeopleQueryResult`
    完全由 5 個 category sub-table 組成（`StatusRecords`、
    `OfficeRecords`、`EntryRecords`、`TextRecords`、
    `AddressRecords`）。所有 `include_*` 關掉時返回 5 個
    空 list。`lookatgroupdata.run` 在沒有 category flag
    時返回 **base BIOG_MAIN 記錄**，任何 flag 開啟就拋
    `NotImplementedError`。兩端的輸出形狀沒有兩側都非空
    的交集。
  - **dynasty_lookup**: 完全沒有 cbdb_replay 對應物
    （`DYNASTIES` 是個小 lookup 表；cbdb_replay 從來沒包它）。
- **依然存在的覆蓋**: `tests/test_phase5e_lookups_smoke.py`
  通過 ParityHost 為這三個 surface 各跑一次 smoke——只用
  Avalonia API 驗證返回一個合理的非空形狀。
- **失去的覆蓋**: 這三個 surface 的跨引擎 row-by-row 檢查。
  按 §0.b，當沒有上游驗證過的 Access query 回答相同問題時，
  失去這層覆蓋是可以接受的。
- **豁免理由**: 按 §0.b 唯一允許的 Access 端調用是
  `cbdb_replay.lookat*`。當前三個可用模組
  （`lookatplace`、`lookatgroupdata`、dynasty 沒有）都不
  回答 Avalonia 的 question shape。
- **豁免至**: 任一側獲得對應的 question shape。Access 端：
  `cbdb-user-mdb-tests` 加 (a) 一個處理下拉選項形狀的
  `lookat_place_options`，或 (b) 一個返回形狀與
  `GroupPeopleQueryResult` 的 category sub-tables 匹配的
  `lookatgroupdata` 變體，或 (c) 一個 `lookatdynasty` lookup
  模組。對稱地，Avalonia 端的改動如果收斂到已存在的
  cbdb_replay 形狀（例如新加一個對齊 `lookatplace` 的
  `GetPeopleAtPlacesAsync`），同樣可以重新打開這個 pair test。

### tier2_per_person — 12 個 surface 沒有 Access ground truth（2026-05-30 加入）

- **首次發現**: 2026-05-30
- **側別**: Access（缺口）
- **類別**: Access 端缺 oracle（結構性）
- **描述**: 12 個 Phase 4 Tier-2 per-person accessor 在
  `cbdb-user-mdb-tests` 中都沒有任何 `cbdb_replay.lookat*`
  模組：

  ```
  addresses, altnames, biog_basic, detail, entries（per-person），
  events, institutions, possessions, postings, sources,
  statuses_person, writings
  ```

  cbdb_replay 只有 `lookat{entry, office, status, kinship,
  associations, associationpairs, place, networks, groupdata,
  texts}`——上述 12 個都沒有。原 Phase 4 pair test 用
  `cbdb_parity/access_*.py` 裡手寫的 `_ACCESS_SQL` 字串重建
  Avalonia 的 join shape，這正是 WORK_PLAN §0.b（2026-05-30）
  禁止的轉寫模式。`associations` 是另外一種情況：模組存在
  但輸入沒有 `person_id`，所以回答的是結構不同的問題（見上面
  `associations_basic_person` 條目）。它在 Phase 6b 與這 12
  個一同刪除，總共 13 個。
- **根本原因**: 這些 per-person surface 在 Access 側歷來都是
  人手通過 Access UI 觸發，從來沒有經過 `cbdb_replay` 的查詢
  腳本。沒有上游驗證的 query 可調，本 repo 對這些 surface 上
  「Access 端應該返回什麼」沒有 oracle。
- **依然存在的覆蓋**: Phase 5c mirror-vs-host
  （`tests/test_phase5c_person_mirror_vs_host.py`）對這 12 個
  surface 中的每一個（外加 associations）都跑了真實的上游 C#
  service，「Avalonia 端輸出對不對」這一半 parity 問題依然
  在 gate。
- **失去的覆蓋**: 「Access 引擎與 Avalonia 引擎在這個 per-person
  surface 上 row-by-row 一致」這條跨引擎斷言——但截至
  2026-05-30 那個斷言是 false-oracle 對比（手寫 SQL vs 上游
  SQL），保留它違反 §0.b。
- **豁免理由**: 按 §0.b 唯一允許的 Access 端調用是
  `cbdb_replay.lookat*`。這 12 個 surface 沒有對應模組，
  所以 Phase 4 pair test 必須撤掉，等待 `cbdb-user-mdb-tests`
  把對應 lookat 模組加進來。
- **豁免至**: `cbdb-user-mdb-tests` 為對應的 surface 加上
  `lookat<surface>` 模組。WORK_PLAN Phase 6 已執行的清理動作：
  刪掉 `cbdb_parity/access_<surface>.py` 和對應的
  `tests/test_phase4_<surface>_pair.py`。

## 豁免到期管理

依 WORK_PLAN §7,本檔每個條目都應該在 `cbdb-project` 的 issue tracker
中對應一個追蹤 issue。本檔只是快速參考;canonical 行動清單在
issue tracker。
