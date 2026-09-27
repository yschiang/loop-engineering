# Tasks：implement-delivery-loop（D40 核准基準 v3）

> D11 已依 D40 取得使用者確認；S1 可依本計畫派工，S2/S3 仍遵守 D27。格式沿 OpenSpec `tasks.md`（`- [ ] X.Y`，驗法寫在同一行）；task 下補 Writing Plans 的 Files／Interfaces／Red 測試（見 design.md §14 的適配差異）。
> 每個行為 task 遵守 Superpowers TDD：先寫失敗測試並以 `delivery evidence run --kind red` 保存（1.2 之前以 git commit＋原始輸出保存），再最小實作、Green、commit。路徑相對 orca-delivery repo。
> 測試層級：**F**=pytest＋fake adapters（含真 git tmp repo、subprocess kill、crash fixture）；**OS**=真實 OS sandbox 負例（不需 runtime）；**R**=真實 runtime；**GH**=真實 GitHub sandbox repo；**E2E**=完整交付。
> v3：回應 re-review-v2 的 DR-04（task 1.2）與 DR-10（tasks 2.1、2.3、2.10）；其餘沿用 v2。
> v2：回應 DR-01–DR-09，受影響 task 以「(DR-xx)」標示；未新增產品 scope。

## 整合策略與切片 [D40 已核准]

| 切片 | 內容 | 主要 AC | 驗收層級 | 前置 |
| --- | --- | --- | --- | --- |
| **S1 core** | 群組 1–2：store、authority、outbox、sandbox profile＋OS 負例、budget、versions、gates、findings、整合、狀態機、CLI | 大部分 AC-D/G/F、AC-O 的 controller 部分 | F＋OS（V2＋V3） | D11、GitHub 目標、CI |
| **S2 adapters** | 群組 3–4：GitHub、OpenCode、sandbox 下的 runtime 隔離 | AC-D18–D24、G11–G15、G19、D12 real | R＋GH（V4） | S1 accepted＋merged（D27）、reviewer profile、OpenCode 登入 |
| **S3 orchestrate** | 群組 5：skill router、操作文件、E2E | AC-O16–O28、G20、intent A13 | E2E（V5） | S2 accepted＋merged |

D40 採三個 feature PR。單一 PR／四 PR 為歷史替代方案，未選用。每個切片獨立 ticket 與驗收範圍，88 個 AC 的完整交付到 S3 才能總結。

- 產品整合模型依 design.md §9.2：per-attempt clone → controller 以 CAS fast-forward 寫整合 branch。Bootstrap 期間由協作者依同契約協調，evidence 標 `coordinated_by=collaborator`。
- S1 完成後，可用 `delivery gate eval` 對 S2/S3 做**非權威**自檢；G2/G3 以獨立 reviewer 與真實 CI 為準。

## 0. 前置（非程式，D11 前後）

- [x] 0.1 D40 已核准 v3 design/tasks/validation 與技術預設；驗法：`approval.json` 保存三份候選 digests 與使用者確認來源
- [ ] 0.2 D40 已選 private `yschiang/orca-delivery`，本機 origin 已連結；建立各切片 issue 並核對 required check `test`（GitHub Actions）與權限；GH 實測 sandbox repo 延至 S2 前選定，不阻擋 S1；驗法：repo/issue API 可讀，S1 CI 結果可讀
- [ ] 0.3 記錄 bootstrap Reviewer 的 provider/model 與派工通道（D39）；驗法：receipt 含 requested／actual model，或明列缺口

## 1. S1-A Durable foundation

- [x] 1.1 建立 Python 3.12 專案骨架（uv、pytest、`delivery` entry point、CI workflow `test`）；驗法：`uv run pytest` 與 `delivery --help` 成功
  - Red：`test_cli_help_lists_commands`
- [x] 1.2 (DR-04) Evidence runner 與 baseline＋overlay Red snapshot（design.md §6.1 v3）；驗法：`tests/test_runner.py` 以真 git tmp repo 通過
  - Interfaces：Produces `run_evidence(kind, task_id, attempt_id, argv, cwd, scope_paths) -> Evidence`、`snapshot_worktree(cwd, t0, scope_paths, excludes) -> Snapshot | Refusal`
  - Red 測試（每案都斷言 worker `.git/index` bytes 與 `git status --porcelain` 前後不變）：
    - 只有 untracked 新測試 → snapshot 含該檔；
    - tracked 修改＋untracked 測試混合 → 皆在；
    - stage 後又改動的檔案 → snapshot 為工作樹版本，非 staged 版本；
    - 已 stage 的排除檔（`.env.fake`）→ 不在 tree，且 fetch red ref 後 controller repo 內沒有該 blob；
    - 已 stage 的 scope 外檔案 → `snapshot_refused`、未寫 ref、未執行測試；
    - baseline 已 tracked 的排除檔：被修改 → 拒絕；未修改 → 以 baseline 保留；
    - worker 已 commit 的 scope 外檔（T0..HEAD）→ `committed_scope_violation`；
    - 測試期間改動 allowed 檔 → `snapshot_drift`；
    - 從 snapshot checkout 重跑 → 相同 failing IDs；
    - 語法錯誤 → `collection_error`（AC-G07）
- [ ] 1.3 (DR-09) Durable blob 協定＋snapshot 提交屏障＋引用完整性（design.md §8）；驗法：`tests/test_store.py`、`tests/test_store_crash.py` 通過；Linux CI 另跑 strace 順序檢查
  - Red 測試：
    - commit 引用未 durable 的 handle → 拒絕；
    - 殘留 tmp 或已 link 未刪 tmp 的 fixture → resume 正常；
    - 刪除一個已引用 blob → resume Blocked 且檔案不變；
    - `os.link` 撞名但內容不同 → conflict＋Blocked；
    - 未知 schema_version／壞 JSON → 明確錯誤；
    - 外部改 gate → `manual_edit_detected`；
    - SIGKILL 隨機中斷 200 次後不變式成立（process 層級）；
    - `strace -f -e trace=fsync,link,rename` 顯示所有 blob fsync 早於 snapshot rename（僅 Linux）
- [x] 1.4 events.jsonl pending history、ID 去重、尾筆截斷、中段損壞；驗法：`tests/test_events.py`（AC-D10）
- [x] 1.5 Result 匯入：inbox → durable blob、同內容去重、不同內容 conflict、身份不符拒收；驗法：`tests/test_results.py`（AC-D05, D07, D08）
- [x] 1.6 (DR-06) Feature authority locator、flock、run lineage 與預算加總（design.md §9.1）；驗法：`tests/test_authority.py` 通過（AC-D03, D17, F07）
  - Red 測試：
    - 兩 subprocess 同時 start → 恰一方成功；
    - clone A 的 run 用掉 3 輪後 controller 結束（fake worker 仍活）→ clone B start 同 feature 被拒，輸出 A 的 state_dir；
    - A 的 state_dir 被移走 → B 得到 Blocked，不建空 run；
    - `abandon_run` decision 後新 run 繼承已用 rounds/active time；
    - lineage 中任一 run 不可讀 → Blocked；
    - project.json 被刪 → 由 authority 修復
- [x] 1.7 (DR-07) Outbox 引擎與 dispatch 分段恢復（design.md §11），以 fake runtime/GitHub 注入故障；驗法：`tests/test_outbox.py`、`tests/test_dispatch_recovery.py` 通過（AC-D06, D12–D14, D16, F14）
  - Red 測試：故障矩陣每一格斷言最終 stage 與外部呼叫次數
    - crash 在 session create 前 → 恰 1 次 create；
    - create 回應遺失且 lookup 查得 → 不重建；
    - session_created 後、prompt 前 → 送 1 次；
    - prompt 回應遺失、messages 有 marker → accepted、不重送；
    - prompt 回應遺失、messages 無 marker → 同 session 0 次重送，stop＋新 attempt；
    - stop 無法確認 → Blocked；
    - accepted 後 receipt 未存 → 由 messages 補存；
    - session lookup 得 2 個 → Blocked
- [x] 1.8 Budget：active interval 聯集、crash unknown interval、per-op retries；驗法：`tests/test_budget.py`（AC-D16, D17）
- [ ] 1.9 (DR-01) Sandbox profile 產生器與 OS 負例套件（design.md §10），不需 runtime；驗法：`tests/os/test_sandbox_macos.py -m os` 在 macOS 通過；Linux launcher 未安裝時該測試標 skipped 並在 validation 記未覆蓋
  - Red 測試：以 profile 啟動 `sh`／`python` 並分別以直接呼叫與孫程序執行 §10.4 清單，拒絕項須得 EPERM/EACCES、允許項成功；profile 缺規則時 isolation 報告必須為 `unverified`

## 2. S1-B Gates、findings、整合與狀態機

- [x] 2.1 (DR-02, DR-03) Bindings/observations、`VersionSet`、gate 完整依賴矩陣與推導規則 R-unaffected／R-base／R-reevaluate／R-reobserve（design.md §5，DR-10）；驗法：`tests/test_versions.py`、`tests/test_assessments.py` 通過（AC-O03, G11, G16, G17, D15）
  - Red 測試：
    - 相同 issue body 輪詢 10 次＋restart → version_key 不變，V1 發出的 review 仍被採用；
    - body 改 1 byte → candidate binding＋awaiting_approval；
    - pr null→34 → G1 經 R-unaffected 推導、原 evidence 身份不變；
    - base 變 → G1 不沿用，必須有 base_recheck evidence；
    - (DR-10) 矩陣完整性：VersionSet 每個欄位對 G1/G2/G3 都有一格；未知欄位或未列 skill 名稱 → 該 gate stale；
    - (DR-10) S1 下 G2 clean → S2 新增 AC → `adopt_binding` → G2 stale、G1 對新 AC missing、Pass 不可能；含 `reuse` 欄位的 decision 被 schema 拒絕；
    - (DR-10) plan binding 改釘新 skill digest → G1 evidence 標 `method_changed`、G2 stale，須新契約 review；
    - (DR-10) controller_version 變更 → 各 gate 經 R-reevaluate／R-reobserve 重算，不直接沿用；新 evaluator 更嚴時原 passed 轉 failed；
    - (DR-10) G3 在任何 key 變更後都重新查詢，不沿用舊 assessment
- [x] 2.2 G1 evaluator：Red 有效性、replay、controller Green、lineage（integration.log）、adopt 缺 Red、N/A；驗法：`tests/test_gate_g1.py`（AC-G04–G10）
- [x] 2.3 (DR-01) G2 evaluator：profile/actual model、session 獨立、isolation 只依 §10.3 能力報告＋receipt；驗法：`tests/test_gate_g2.py`（AC-G03, G11, G12, D24）
  - Red 測試：
    - clone＋env 清理＋事後 ref 不變但無 verified 報告 → G2 unknown；
    - receipt 的 profile digest 與報告不符 → unknown；
    - (DR-10) review result 回報的 binding digests 與當前 VersionSet 不符或缺漏 → 不支持當前 key；
    - (DR-10) 新契約 review clean 且 digests 相符 → G2 passed
- [x] 2.4 (DR-08) G3 evaluator 與 source SHA 選取（head/merge mapping、stale M）；驗法：`tests/test_gate_g3.py` 參數化 7 種非成功狀態＋skipped/neutral＋source 案例（AC-G13–G15）
- [x] 2.5 Pass 判定與 re-read；驗法：`tests/test_pass.py`（AC-G01, G02, G18）
- [x] 2.6 Finding registry：ID、`matches`、blocking 分類、closure 權限；驗法：`tests/test_findings.py`（AC-F01–F04）
- [x] 2.7 Correction batch/rounds（含 base_conflict 項）、一次 dispute、recurrence；驗法：`tests/test_correction.py`（AC-F05–F10, F15, F16）
- [x] 2.8 Decisions 與 acceptance（approve_plan、adopt_binding、accept/return、abandon_run、budget_extension）；驗法：`tests/test_decisions.py`（AC-O05–O07, O10, O11, F11, F12, D02）
- [x] 2.9 (DR-05) `integrate` operation：fetch、scope 核對、CAS fast-forward、crash 恢復、舊 attempt fencing（design.md §9.2）；驗法：`tests/test_integration.py` 以真 git tmp repo 通過（AC-G08, D04）
  - Red 測試：
    - 兩 task 依序整合，task 2 的 T0 = task 1 的 A；
    - 舊 attempt 晚到 → 不整合、ref 不變；
    - crash 在 update-ref 前（ref==T0）→ 重做；
    - crash 在 update-ref 後、snapshot 前（ref==A）→ 收斂為 succeeded、不重做；
    - ref 為第三值 → Blocked；
    - scope 外修改 → 拒絕；
    - 整合後 regression 紅 → G1 failed
- [ ] 2.10 狀態機、adopt、依賴檢查（D27）、Project Lead 授權；驗法：`tests/test_controller_flow.py` 以 fake runtime/GitHub 跑完整路徑（AC-O01–O04, O08, O09, O12, O13, O18, O19, O22, O23, O26）
  - (DR-03) 必含兩個端到端案例：
    - pre-PR G1 → push＋PR 建立 → G2/G3 → Pass；
    - Pass 前 base-only 變更 → R-base 重驗 → 重新收齊三 gates 得 Pass，另一分支為 merge-tree 衝突 → correcting；
  - (DR-10) 另含：契約變更 S1→S2 → awaiting_approval → adopt_binding → planning/implementing 補新 AC → 新契約 review＋G3 重新查詢 → Pass
- [x] 2.11 Resume/reconcile：各 crash 點的磁碟 fixture＋fake adapter 以 `os._exit` 中斷的 subprocess 測試（含 dispatch stages、integrate、blob 屏障）；驗法：`tests/test_resume.py`（AC-D07, D09, D14, D15）
- [ ] 2.12 Publication 內容與 `delivery status`；驗法：`tests/test_publication.py`、`tests/test_status.py`（AC-F13, F14, D01）
- [ ] 2.13 Retro operation 去重與 P03 guard；驗法：`tests/test_retro.py`（AC-O14, O15）
- [ ] 2.14 S1 整合驗證：`uv run pytest` 全綠＋CI `test` 綠＋獨立 review；驗法：G1/G2/G3 evidence 由 `docs/validation/implement-delivery-loop.md` 引用

## 3. S2-A 真實 GitHub adapter

- [ ] 3.1 (DR-08) GitHub adapter（`gh api`）：PR/comment/review/check-runs/statuses/rules/`pulls/{n}` merge 欄位、`pull/{n}/merge` fetch，與 fake 共用 contract tests；驗法：`tests/contract/test_github_contract.py` 對 fake 通過
- [ ] 3.2 GitHub sandbox 實測（repo 由 0.2 決定）；驗法：`tests/integration/test_github_real.py -m gh` 通過並保存 receipts（AC-D12, G13–G15, F13 real）
  - 案例：marker 查回、分頁、check attempts、required rules
  - (DR-08) 案例：H 無 check、M 有 required check → 取得並採用；base 前進後舊 M → stale

## 4. S2-B Runtime adapters 與隔離實測

- [ ] 4.1 Runtime contract tests＋第二個 fake runtime；驗法：`tests/contract/test_runtime_contract.py`（AC-D21, D22）
- [ ] 4.2 (DR-07) OpenCode adapter：從 1.18.32 `/doc` 快照釘住 endpoints，實作分段 dispatch，preflight 驗 session 列表一致性、model identity、原生 message 擷取；驗法：`tests/integration/test_opencode.py -m runtime` 實際推論通過（AC-D06, D18–D20, D23, D24）
  - 故障案例：session 建立後、prompt 前 kill controller → 恢復後恰 1 則 prompt
- [ ] 4.3 (DR-01) Runtime 在 sandbox 下的隔離實測：以 §10 launcher 啟動 `opencode serve`，由 agent 工具（bash）執行 §10.4 負例清單＋允許項，並產出 isolation 能力報告；驗法：`tests/integration/test_isolation.py -m runtime`（AC-G11, G12, D19, D24）
  - 通過標準：全部拒絕項被拒才標 verified；OpenCode 需要的額外寫入路徑列入報告
  - Linux launcher 不可用 → 報告 unverified，對應 AC 記未覆蓋
- [ ] 4.4 選配 adapters（Orca／Claude Code／Codex）：**僅在使用者選用時**建立；未選用則在 validation 標「未覆蓋」

## 5. S3 Orchestrate skill 與 E2E

- [ ] 5.1 `orchestrate` skill router＋references，保留 user-only 限制並記錄 skill 版本；驗法：skill 載入測試＋文件審查清單（AC-O16, O17, O20–O28）
- [ ] 5.2 操作文件（README、runbook：start/resume/decide/status/preflight）；驗法：新 session 依文件從 `delivery status` 接續（V5）
- [ ] 5.3 E2E：在 orca-delivery 內一個小型真實 feature 走完 issue→D11→TDD→PR→真實 review/CI→Pass；有成立 finding 就完成 fix→re-review，沒有就如實記未覆蓋；中途 kill controller 驗證不重派/重貼；驗法：run 目錄與 PR 連結（AC-G19, G20；project-intent A13）

## 自檢（Writing Plans self-review 的適配）

- Spec coverage：88 個 AC 皆映射至 task（見 [validation](../../../docs/validation/implement-delivery-loop.md)）；DR-01–DR-10 的行為驗法分別落在 1.2、1.3、1.6、1.7、1.9、2.1、2.3、2.4、2.9、2.10、3.1–3.2、4.2–4.3（DR-10 在 2.1／2.3／2.10）。
- 本計畫以測試名稱與斷言意圖描述 Red；D11 通過後，每個 task 的 assignment 附完整測試碼（Writing Plans 的「No Placeholders」在 assignment 層落實），這是相對原 skill 的明示調整。
