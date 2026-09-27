# Validation：implement-delivery-loop AC 對照（D40 核准基準 v3）

> 全部 88 個 AC（AC-O01–O28、AC-G01–G20、AC-D01–D24、AC-F01–F16），來源為快照內 4 份 spec（sha256 見 result.json）。**目前所有項目狀態 = 未執行**；沒有任何測試、實測或 E2E 結果。本表是方法規劃，不是驗收結論。
> v3：依 re-review-v2 的 DR-04／DR-10 更新 AC-G06、G07、G11、G17、D05 五列。
> v2：依 review DR-01–DR-09 更新 22 列（標 DR-xx），新增 OS 層級；AC 集合不變。
> 本檔是唯一正式 AC 驗證對照；D40 核准方法，不代表執行通過。依 [tasks](../../openspec/changes/implement-delivery-loop/tasks.md) 分 S1／S2／S3 回填實際證據與版本；凍結候選只保留歷史。

## 層級與環境

| 代號 | 意義 | 環境 | 可宣稱範圍 |
| --- | --- | --- | --- |
| **F** | pytest＋fake runtime/GitHub（含故障注入、crash fixture、subprocess kill） | macOS 本機 Python 3.12.13＋CI Linux runner | 核心規則（V2/V3）；**不**證明任何真實 adapter |
| **OS** | 真實 OS sandbox 負例（macOS `sandbox-exec`；Linux bubblewrap／Landlock 待安裝），不需 runtime | 目標平台本機或 CI | 僅該 launcher＋OS 的拒寫/拒讀能力；不外推到其他平台或 runtime |
| **R** | 真實 runtime（OpenCode 1.18.32，核准 provider/model） | 本機 OpenCode，需登入與模型推論 | 該 runtime/profile 的能力（V4），不外推到其他接法 |
| **GH** | 真實 GitHub sandbox repo（S2 前決定） | `gh` 已登入且對 sandbox 有權限 | GitHub adapter 能力 |
| **E2E** | 真實 feature 完整交付 | orca-delivery＋OpenCode＋GitHub＋CI | V5/部分 V6；finding→fix→re-review 未發生就記未覆蓋 |
| **DOC** | 文件／skill 契約審查（Reviewer 檢查清單） | 人工＋獨立 Reviewer | 分析行為的契約遵循，不是自動化測試 |

## 證據位置代號

- **J-S1**：S1 CI artifact `pytest-junit.xml`＋runner evidence JSON（Red/Green，含 snapshot 與 digest），由 validation 文件引用 result ID。
- **J-S2**：S2 integration junit＋`receipts/`（原生回應、read-back）。
- **RUN**：E2E 的 `.delivery/runs/<run-id>/`（run.json、events.jsonl、results、evidence）＋PR/issue URL。
- **CHK**：validation 文件內的 DOC 審查紀錄（reviewer、版本、逐項結論）。

Pass 標準共通前提：測試由 runner 捕捉且 evidence digest 可核對；斷言針對可觀察結果（state 欄位、operations、外部呼叫次數、檔案內容），不只重述 enum。

## Delivery orchestration（AC-O01–O28）

| AC | 測法 | 層級 | Pass 標準 | 證據 | 狀態 |
| --- | --- | --- | --- | --- | --- |
| AC-O01 | `test_controller_flow::direct_to_implementer`：無 Project Lead 交接直接 start | F | 進 planning；未有 D11 decision 前無 dispatch op；owner/controller identity 保留 | J-S1 | 未執行 |
| AC-O02 | 第二來源（skill/另一 session）送 implementation/review assignment | F | 非 controller 建立的 assignment 被拒；局部 review 結果不改 G2 | J-S1 | 未執行 |
| AC-O03 | (DR-02) `test_versions::binding_observation`：以 issue body＋既有原生 plan 路徑建立 binding，並重複讀取 | F | binding 保存 locator/content_digest/adopted_at，可讀回；相同 bytes 重讀只更新 last_observed_at、version_key 不變；無改名、無 per-task PR | J-S1 | 未執行 |
| AC-O04 | project/feature spec 衝突或必要引用不可讀 | F | Blocked，列衝突與所見版本；無 dispatch op | J-S1 | 未執行 |
| AC-O05 | plan ready、無 decision／timeout／agent 同意 | F | phase=awaiting_approval 顯示待確認 plan_version；0 implementation dispatch | J-S1 | 未執行 |
| AC-O06 | approve_plan 指向目前版本 | F | 依序派 task，assignment 帶 AC IDs 與驗法；finding 修正不再要求 approve | J-S1 | 未執行 |
| AC-O07 | 修正需改 AC/spec 或範圍外需求 | F | 保存未完成項與影響；awaiting_approval/Blocked；無新 dispatch 直到新 decision | J-S1 | 未執行 |
| AC-O08 | adopt：已交接、D11 適用、程式完成；再建立 PR | F | 從 validating 開始；無 planning/implementation dispatch；PR 建立後 G1 以 R-unaffected 推導到新 version_key（DR-03） | J-S1 | 未執行 |
| AC-O09 | adopt 缺 D11／歷史 Red／固定 base／有未知 writer | F | 逐項缺口；缺確認→awaiting_approval，其餘 Blocked；不以 ready 通知判 G1 | J-S1 | 未執行 |
| AC-O10 | 三 gates 通過未 accept | F | ready_for_acceptance＋acceptance pending；0 merge/close/release 操作 | J-S1 | 未執行 |
| AC-O11 | accepted V1 後 head/spec 變 V2 | F | V1 accepted 保留於 history；V2 pending；gates 重評 | J-S1 | 未執行 |
| AC-O12 | 上游 accepted 未 merge | F（fake GitHub） | 下游可 planning；waits 含 dependency；0 implementation dispatch | J-S1 | 未執行 |
| AC-O13 | 上游 accepted＋merged＋baseline 含 merge commit | F | 解除 wait；仍需下游 D11/ownership/budget | J-S1 | 未執行 |
| AC-O14 | 同一 acceptance 重送與 restart | F | 僅 1 個 retro op/result | J-S1 | 未執行 |
| AC-O15 | 未明確開始 P03 | F＋DOC | 無 P03 adopt/Retro op；狀態保留待確認資訊 | J-S1、CHK | 未執行 |
| AC-O16 | skill 完成工作單位回傳 | F＋DOC | 結果經 import 才生效；skill 無法寫 Pass；自動 Retro 不呼叫 user-only skill | J-S1、CHK | 未執行 |
| AC-O17 | 草稿把他 repo 規則標為已確認政策 | DOC | Reviewer 指出來源差異；controller policy digest 不含該規則 | CHK | 未執行 |
| AC-O18 | 授權 Project Lead 委派 | F | 附授權來源的委派 → 經核對後派發；無授權者被拒；不取代 D11 | J-S1 | 未執行 |
| AC-O19 | 父子 session／相同入口 | F | 權限只依角色＋decision；父子標記不增加權限 | J-S1 | 未執行 |
| AC-O20 | project 分析拆 features | DOC／E2E | 產物可追溯研究、SA、roadmap；milestone/feature/task identity 分開 | CHK | 未執行 |
| AC-O21 | 單一 feature 聚焦分析 | DOC／E2E | 引用 baseline、補差異；scope/AC 未知回人 | CHK | 未執行 |
| AC-O22 | Project Lead 草案 tasks 由 Implementer 校準 | F＋DOC | 草案 plan 不能 approve 派工；最終 tasks 有版本 | J-S1、CHK | 未執行 |
| AC-O23 | 詳設發現跨 feature 影響 | F | 受影響 task 停派、保存影響；未受影響 task 可繼續 | J-S1 | 未執行 |
| AC-O24 | project vs feature SA 深度 | DOC | SA 產物層級與 AC 穩定性符合 SA 契約 | CHK | 未執行 |
| AC-O25 | 模板齊全但有阻擋 | DOC | 交接列阻擋與 owner，不宣告 ready | CHK | 未執行 |
| AC-O26 | 有 SA 確認但無 D11 | F | 0 implementation dispatch | J-S1 | 未執行 |
| AC-O27 | 研究與描述衝突／需 prototype | DOC | 區分現況與需求、先提目的範圍 | CHK | 未執行 |
| AC-O28 | 功能驗收 vs 業務成果 | DOC | 分開記錄，未量測者保留狀態 | CHK | 未執行 |

## Delivery gates（AC-G01–G20）

| AC | 測法 | 層級 | Pass 標準 | 證據 | 狀態 |
| --- | --- | --- | --- | --- | --- |
| AC-G01 | (DR-03) `test_controller_flow::pre_pr_to_pass`：G1(pr=null)→push＋PR→G2∥G3→Pass | F；E2E | Pass 只在三 gates 的 current assessment 同 version_key；G1 經 R-unaffected 推導且原 evidence 身份不變；task succeeded 不產 Pass | J-S1、RUN | 未執行 |
| AC-G02 | review clean＋CI fail；CI ok＋changes_required | F | 無 Pass；兩 gate 各自保存；同版本 batch | J-S1 | 未執行 |
| AC-G03 | reviewer succeeded＋verdict blocked | F | G2 unknown、phase blocked、rounds 不變 | J-S1 | 未執行 |
| AC-G04 | 摘要稱通過但 log 缺/hash 錯/exit≠0/snapshot 不符 | F | G1 非 passed，逐項 reason＋producer | J-S1 | 未執行 |
| AC-G05 | tracked 驗收文件引用 runner result | F | 程式版本與 evidence 關係可核對；不要求文件自我 SHA | J-S1 | 未執行 |
| AC-G06 | (DR-04) Red@R（baseline＋overlay snapshot，含 untracked 新測試與 stage 後改動檔的工作樹版本）、Green@H 不同 SHA | F（真 git tmp repo） | G1 passed；R 由 snapshot checkout replay 得相同 failing IDs；R 相對 parent 的差異 ⊆ scope 且無 exclude 路徑；lineage 記 P→A→H | J-S1 | 未執行 |
| AC-G07 | 只有 green／syntax red／replay 冒充；(DR-04) staged scope 外檔、staged 排除檔、baseline tracked 排除檔被修改、已 commit 的 scope 外檔、測試期間 drift | F（真 git） | missing/invalid 並列原因；拒絕案例不寫 tree/commit/ref、不執行測試、controller repo 無違禁 blob；staged 排除檔只被略過；replay 標性質；無法取得→Blocked | J-S1 | 未執行 |
| AC-G08 | (DR-05) `test_integration`：兩 task 以 CAS fast-forward 依序整合後，整合 head 的 regression 紅 | F（真 git） | G1 failed，保存 integration.log（T0→A）與失敗輸出；worker 回報的 green 不採用 | J-S1 | 未執行 |
| AC-G09 | 純文件 N/A 經 reviewer 接受 | F | eligibility 綁 diff digest；G1 可過；G2 未自動過 | J-S1 | 未執行 |
| AC-G10 | 設定行為變更自宣 N/A／eligibility 未完成 | F | G1 不過；拒絕原因可見 | J-S1 | 未執行 |
| AC-G11 | 合規 reviewer clean；(DR-10) review result 的 binding digests 與當前 VersionSet 相符 | F；R | G2 passed 需 isolation 能力報告 verified（§10.3）＋receipt profile digest 相符＋actual model 相符＋讀過當前 binding digests；只由 controller 派出的 review 產生，人工 decision 不能產生 | J-S1、J-S2 | 未執行 |
| AC-G12 | (DR-01) subagent review；clone＋env 清理＋事後 ref 不變但無拒寫證據；sandbox 下 reviewer 寫 author repo／update-ref／run.json／讀 gh 憑證（直接與孫程序） | F；OS；R | 前兩者 G2 unknown；OS/R 層每個負例被拒（EPERM/EACCES 或認證失敗）才可能 verified，任一成功 → unverified＋Blocked | J-S1、J-S2 | 未執行 |
| AC-G13 | 空集合與 7 種非成功狀態、skipped/neutral 無 policy | F；GH | 每種皆不過且 reason 對應 | J-S1、J-S2 | 未執行 |
| AC-G14 | 舊 attempt success＋新 attempt pending；未知 app 同名 | F；GH | 採最新 attempt 與核准 app | J-S1、J-S2 | 未執行 |
| AC-G15 | (DR-08) adapter 端到端：H 無 check、M（`pull/{n}/merge`）有 required check；base 前進後舊 M | F（contract）；GH | 取得 M 並驗 parents=[當前 base_tip, H] 才採用並保存 mapping；舊 M → stale；M 未計算 → unknown | J-S1、J-S2 | 未執行 |
| AC-G16 | H2 時 H1 結果晚到；(DR-02) 相同 body 輪詢 10 次＋restart 期間 V1 的 review 到達 | F | H1 存歷史不評入；同內容輪詢不改 version_key，V1 review 仍被採用並可到 Pass；findings/budget 不重置 | J-S1 | 未執行 |
| AC-G17 | (DR-03) head 同、base 前進：merge-tree 乾淨與衝突兩分支；(DR-10) S1 下 G2 clean → S2 新增 AC → adopt_binding；plan 改釘新 skill digest；controller_version 變更；矩陣未列欄位 | F（真 git） | base 乾淨：base_recheck→三 gates 同 key 得 Pass；衝突：G1 failed→correcting。S2：G2 stale 直到新契約 review、G1 對新 AC missing、`reuse` decision 被拒、期間 Pass 不可能。skill：evidence 標 method_changed、G2 stale。controller：全數重算不沿用。未列欄位：stale | J-S1 | 未執行 |
| AC-G18 | Pass 前 re-read 不一致；Pass 後 push | F | 前者無 Pass 並 reconcile；後者舊 Pass 保留、現行失效 | J-S1 | 未執行 |
| AC-G19 | fake 通過而 adapter 能力未驗 | DOC＋報告 | 驗收報告按能力列缺口，不宣稱 V4/E2E | CHK | 未執行 |
| AC-G20 | 真實 review clean 無 finding | E2E | clean 保存；finding→fix→re-review 標未覆蓋；無虛構 blocker | RUN、CHK | 未執行 |

## Durable delivery（AC-D01–D24）

| AC | 測法 | 層級 | Pass 標準 | 證據 | 狀態 |
| --- | --- | --- | --- | --- | --- |
| AC-D01 | `delivery status` 與 run.json 頂層欄位 | F＋DOC | phase、版本、gates 理由、blockers、next_action 直接可見 | J-S1、CHK | 未執行 |
| AC-D02 | 手改 gate＝passed；設定變更 | F | 偵測手改、重算 gates；設定 schema/版本重驗 | J-S1 | 未執行 |
| AC-D03 | (DR-06) 兩 subprocess 同時 start；clone A 結束/崩潰後 clone B 以不同 run 啟動同 feature | F | 同時：恰一方取得；順序：B 被拒並顯示 authority 登記的 A state_dir；A 不可讀 → Blocked，不建空 run | J-S1 | 未執行 |
| AC-D04 | worker 超時且 status unknown；(DR-05) 舊 attempt 事後 commit | F（真 git） | 保存 unknown＋dispatch identity；未確認停止前 0 替代 attempt；舊 attempt 的 clone 不被 fetch、整合 ref 不變 | J-S1 | 未執行 |
| AC-D05 | result 的 workspace/attempt/snapshot/scope 不符；(DR-04) snapshot tree 含 scope 外或 exclude 路徑（匯入時 `git diff-tree` 再驗） | F（真 git） | 原件保留、拒作 evidence、列差異 | J-S1 | 未執行 |
| AC-D06 | 只有 native assistant message、無通知；(DR-07) prompt 已被接受但 receipt 未存 | F；R | adapter 產 result（producer=adapter＋native IDs）；receipt 由 messages 補存；lifecycle 不足記未確認 | J-S1、J-S2 | 未執行 |
| AC-D07 | result 已存但通知遺失／匯入前 crash | F | resume 從 inbox 以 durable blob 匯入一次、不重派 | J-S1 | 未執行 |
| AC-D08 | 相同 result 重送；同 attempt 不同 bytes | F | 前者無新 transition/op；後者保留雙方並 Blocked | J-S1 | 未執行 |
| AC-D09 | (DR-09) snapshot 提交前/後 crash；引用未 durable blob；已引用 blob 遺失；SIGKILL 隨機 200 次；Linux strace 順序 | F；OS（Linux CI） | 讀到完整舊或新版；未 durable 引用拒提交；遺失 blob → Blocked；strace 顯示 blob/dir fsync 早於 snapshot rename；power-loss 不在此宣稱 | J-S1 | 未執行 |
| AC-D10 | history 未寫完、重放、尾筆殘缺、中段損壞 | F | 補齊不重複；尾筆診斷保存；中段→Blocked | J-S1 | 未執行 |
| AC-D11 | run.json 缺失/壞/未知 schema | F | 明確錯誤、0 dispatch、原檔不變、不建空 run | J-S1 | 未執行 |
| AC-D12 | GitHub 已接受但回應遺失後 restart；(DR-07) runtime prompt 已接受但回應遺失 | F；GH；R | 各以 marker 查回、同一 op 收斂；comment 數=1；同 session prompt 數=1 | J-S1、J-S2 | 未執行 |
| AC-D13 | unknown 且查不到 marker；(DR-07) prompt_sending 查無 marker 訊息、stop 可/不可確認 | F | GitHub：Blocked＋查詢證據、0 重貼；dispatch：同 session 0 重送，stop 確認→新 attempt（計 infra retry），不可確認→Blocked | J-S1 | 未執行 |
| AC-D14 | restart 時 worker 已完成、review 已存、issue 發布 pending；dispatch 各 stage 與 integrate 各點 crash | F | 匯入完成結果、只恢復未完成 stage/op；外部呼叫次數符合 design §11 不變式；0 重派 | J-S1 | 未執行 |
| AC-D15 | resume 發現外部 head/base/spec 改變 | F | 保存所見版本與原因；舊 Pass/accept 不沿用 | J-S1 | 未執行 |
| AC-D16 | infra op 3 次皆失敗；程式錯誤被分類 | F | 保存 3 attempts 並 Blocked；程式錯誤進 correction | J-S1 | 未執行 |
| AC-D17 | active 達 4h；restart 讀到已到限；(DR-06) 另一 run 在同 feature 啟動 | F | 0 新派工、unknown interval 保存；feature 累計（authority lineage）不因新 run 歸零；延長需 decision | J-S1 | 未執行 |
| AC-D18 | requested≠actual model／workspace；只有 input_accepted | F；R | 不宣稱成功，保存差異與 native IDs | J-S1、J-S2 | 未執行 |
| AC-D19 | adapter 能力不足、候選未核准 | F；R | 具體 Blocked＋最小能力需求；無自動換 runtime | J-S1、J-S2 | 未執行 |
| AC-D20 | 無 Orca/Codex/Claude Code 的環境 | R | 以 PATH 隔離這些程式後，OpenCode 路徑完成 start/dispatch/collect/resume | J-S2 | 未執行 |
| AC-D21 | 兩種 runtime 的 native IDs | F | attempt 對回 run/task/attempt＋來源 runtime；無補造 ID | J-S1 | 未執行 |
| AC-D22 | 一種接法通過、另一種未驗 | F＋DOC | capability 報告分開，無共用成功標記 | J-S1、CHK | 未執行 |
| AC-D23 | 未選用接入故障 | F；R | OpenCode profile 不受影響；無自動改派 | J-S1、J-S2 | 未執行 |
| AC-D24 | Implementer 與 Reviewer 同在 OpenCode、不同 model，各自 sandbox profile | F；R | 分別保存 runtime、requested/actual model 與 isolation 報告；G2 需 reviewer 報告 verified | J-S1、J-S2 | 未執行 |

## Finding resolution（AC-F01–F16）

| AC | 測法 | 層級 | Pass 標準 | 證據 | 狀態 |
| --- | --- | --- | --- | --- | --- |
| AC-F01 | AC 缺陷＋命名偏好 | F | 前者 blocking、後者 nonblocking；皆有 ID 與依據 | J-S1 | 未執行 |
| AC-F02 | 同問題移位/改名/新輪；同位置不同問題 | F | `matches` 沿用 ID；未指認者新 ID；無自動合併 | J-S1 | 未執行 |
| AC-F03 | 修正 commit＋GitHub thread resolved | F | 仍 blocking；新 head 先 G1 | J-S1 | 未執行 |
| AC-F04 | reviewer 確認或人工裁決 | F | closure 含 actor/source/version/reason/evidence | J-S1 | 未執行 |
| AC-F05 | CI 先失敗、review 未完成 | F | 無派修 op 直到 review 完成；首次派修 round=1 | J-S1 | 未執行 |
| AC-F06 | correction result 缺部分回應 | F | 標不完整並列缺 ID；無 finding 解除 | J-S1 | 未執行 |
| AC-F07 | 已 3 輪仍有缺陷；(DR-06) 換 clone/新 run 嘗試第四輪 | F | Blocked；0 第四輪；rounds 以 feature lineage 加總；延長需 decision | J-S1 | 未執行 |
| AC-F08 | 首次 dispute 被接受 | F | finding resolved；rounds 不變 | J-S1 | 未執行 |
| AC-F09 | dispute 仍在／restart 後重送 | F | Blocked；dispute 次數=1 不重置；0 第二次覆核 | J-S1 | 未執行 |
| AC-F10 | dispute 伴隨新 head | F | 先 G1，再合併最新 review | J-S1 | 未執行 |
| AC-F11 | Pass 後首次人工退回 | F | human_acceptance finding；Pass 失效；檢查剩餘 rounds 後派修 | J-S1 | 未執行 |
| AC-F12 | 範圍外新想法／spec 錯誤 | F | 不進 correction；Blocked 交 Project Lead/使用者 | J-S1 | 未執行 |
| AC-F13 | 完整 review＋issue 摘要 | F；GH | PR 可讀完整 review、issue 有摘要＋連結、皆帶 run/result/finding IDs | J-S1、J-S2 | 未執行 |
| AC-F14 | 發文失敗／unknown | F；GH | 只恢復發布；review 不重做；publication 狀態如實 | J-S1、J-S2 | 未執行 |
| AC-F15 | 同 blocker 經 2 次有效修正仍未解 | F | 下次派修前 Blocked，顯示每輪 commit/覆核與剩餘預算 | J-S1 | 未執行 |
| AC-F16 | 已解除 blocker 再現；相似文字新問題 | F | reviewer `matches` 才 reopen→Blocked；新問題不誤算 | J-S1 | 未執行 |

## 尚未覆蓋與限制（誠實聲明）

- 所有列為「未執行」；本輪未寫產品程式、未跑任何測試或推論。
- D40 已選交付 repo `yschiang/orca-delivery`。R/GH/E2E 仍需 S2 sandbox repo、runtime reviewer profile、OpenCode 登入／推論證據；本次 bootstrap 使用 D39 Opus＋GPT，不宣稱產品 runtime 已通過。
- 真實 finding→fix→re-review（D10；project-intent.md 情境 A13，非四份 spec 的 AC）只能在 E2E 自然發生；不以人為 blocker 補展示（AC-G20）。
- 平台：只規劃 macOS/Linux；Windows/WSL2 未覆蓋（Q-PLATFORM）。
- Worker 權限邊界（design.md §10）：目前只有本輪 macOS Darwin 27.0 的 tmp probe（非產品測試）；Linux launcher、OpenCode 在 sandbox 下、keychain 與網路未測。未通過負例套件的 profile 一律 unverified。
- Durability：process 層級（SIGKILL）與 Linux syscall 順序可測；主機斷電／儲存 crash 未覆蓋（需 VM 硬重置），macOS 目錄 `F_FULLFSYNC` 支援待測。
- G3 merge snapshot 與所有 GH 層案例依 S2 GitHub sandbox 與權限實測。

## S1 實作執行紀錄（bootstrap-s1-20260927／s1-impl-01，進行中）

本段只記錄 S1 worker 在本機實際執行的測試與未執行項目；不是 G1/G2/G3 結論，也不改動上方 AC 對照。原始 Red/Green 證據（命令、cwd、起迄時間、exit、完整 stdout/stderr、HEAD/tree、hash）保存在 run 目錄 `s1-run/evidence/<task>/`，不進 Git。

| 層級 | 已實際執行（本機 macOS 27.0、Python 3.12.13） | 未執行／未覆蓋 |
| --- | --- | --- |
| F | tasks 1.1、1.2、1.4–1.9、2.1–2.9、2.11–2.13 與 2.10 的部分行為；全量回歸指向 worker head | CI 尚未執行（未 push）；必要 check `test` 聚合 Linux 與 macOS job，任一失敗或 skipped 即失敗，JUnit 以 artifact 上傳 |
| F／Linux | — | `test_blob_and_dir_fsync_precede_snapshot_rename`（strace 順序）只在 Linux 執行；本機為 skipped，**不算通過**；CI 以 `DELIVERY_REQUIRE_LINUX_CHECKS=1` 強制執行 |
| OS | macOS Seatbelt 負例套件（直接與孫程序）：寫 author repo、update-ref、寫 run.json／blobs／authority／他 attempt inbox 與 clone、讀憑證檔、push 均被拒；keychain 項目與 `gh auth token` 以合成憑證＋未受限對照執行驗證被拒（輸出丟棄、只記 exit）；移除 keychain 規則可被偵測；寫自己 clone／inbox 成功 | Linux launcher（bubblewrap／Landlock）未實作亦未安裝：`run_suite` 在 Linux 回 `unverified`／`not_run`，對應 AC 未覆蓋；OpenCode runtime 在 sandbox 下的隔離屬 S2 task 4.3 |

環境觀察：本機 `/usr/local/bin/git` 為 x86_64 build，在 Seatbelt 下 exec 失敗（"Bad CPU type"）；OS 負例改釘 `/usr/bin/git`，使拒絕可歸因於邊界而非 binary。`git push` 被拒時不回報 EPERM 文字，該負例以「remote ref 未產生」的效果核對判定。

待獨立 Reviewer 核對的文字歧義：design.md §5.3 矩陣的 skills×G3 格寫 R-unaffected，但 R-reobserve 定義與 task 2.1（DR-10）驗收要求「G3 在任何 key 變更後重新查詢」。依協調者指示採既有明確驗收（G3 一律 R-reobserve），未修改 spec/design。

### S1 延續（s1-impl-02）

- Task 2.10 主迴圈：`delivery.loop.step()` 每步重讀 run.json，串接真 git clone、outbox 分段派工、fake runtime（fake worker 以真 runner 保存 Red）、inbox 匯入、CAS 整合、controller 自跑 Green＋Red replay、G1／G2／G3、correction batch 與 re-review；`tests/test_loop.py` 驗 finding→fix→re-review→Pass、缺 Red 不放行、隔離未驗證不放行、CI 失敗與 review 同批、未核准不派工、fenced 派工 Blocked。均為 fake adapter（F 層），非真實 runtime／GitHub／E2E。
- 迴圈揭露並已修正：integrate 讀 design 的 task list（原假設 dict）；Blocked 詳情欄位與 `_block` 參數同名（TypeError）。
- CLI 接線見 `docs/implementation/cli.md`；需 S2 adapter 的命令 exit 3，不宣稱外部完成。
- 2.14（真 CI、獨立 review）由協作者執行；1.3 的 Linux strace 仍待 CI。

### S1 完成（s1-impl-03）

主迴圈接線（F 層，fake runtime／GitHub，真 git）：
- G1 可修缺失（整合回歸、red 測試在 head 未通過）退回原 producing task 新 attempt，不增 round；缺／無效／不可重現歷史 Red → Blocked。
- 派工 guard：feature authority、ticket、目前 plan binding、skill pin、implementer sandbox 報告、累計 active 預算（activity 區間＋carried）、D27 依賴（未 merge 等待，不派工）；`authorize_dispatch` 以 task list 與實算條件執行。
- Outbox：integrate 先登記再執行（pending→in_flight→effect→commit），crash 後依 ref 收斂；review 經 outbox 發 PR 全文與 issue 摘要。
- 版本重讀：checking 前、Pass 前與 ready_for_acceptance 靜止時重讀 head／base／merge-base／bindings；base-only → R-base（merge-tree＋merge 結果 Green）；base 衝突 → correction batch；契約變更 → candidate＋awaiting_approval，`adopt_binding` 後重評 G1 並新契約 review。
- 決策：各 kind 履行或明確拒絕；accept 登記 retro op；ac_defect return 建 batch 與 fix task；abandon_run 經 authority。start 不重置既存 run；adopt 匯入 plan／tasks／bindings／handoff。
- 證據：red／green／replay 原始輸出為 durable blob；CLI evidence write-once；N/A eligibility（預篩＋獨立 reviewer，綁 diff digest）在主迴圈。
- 2.7 recurrence 由真 re-review 計數；D25 爭議一次獨立覆核（accepted 解除、upheld Blocked），不增 round。
- 每個改變狀態的 step 寫 events.jsonl；resume 對遺留 activity 計入 crash 區間。

仍未覆蓋（S1 範圍外或待協作者）：真實 runtime／GitHub adapter 與 sandbox 下的 runtime 啟動（S2）；G3 `source: merge` 的 M 映射需 GitHub adapter（S2 3.1，現為 unknown 而不放行）；retro op 的執行（S3 orchestrate reference）；Linux launcher；1.3 Linux strace 與 2.14 真 CI／獨立 review。
