# Proposal：orchestrate 經 Orca 派 Implementer、收回結果，卡住時交給人（orca-dispatch）

> 草稿（2026-10-03）：範圍照 roadmap 的 Feature 2 列與 D79 寫；「待決與依賴」第 1 項（要不要拆）可能把其中一部分切成另一個 Feature。

## Why

Feature 1 之後，loopctl 保存狀態與人工決策，核准後 `next` 回報下一步是派工，但沒有東西真的去派：Feature 1 的 Implementer 都是協調者手動以 `claude -p` 派出、手動等結果。B1 的 API 502 因此約 10 分鐘沒人發現，而且只是因為人問了「進度」；等待迴圈最長可能 2 小時都不會察覺。Feature 2 交付從交接包到 Implementer 結果匯入的最小完整路徑：orchestrate 依 `next` 經 Orca 派 Implementer，外部操作先登記再讀回，結果先保存再去重匯入，察覺卡住就停下交人（D76、D79）。

需求輸入：[`docs/requirements/delivery-controller/`](../../../docs/requirements/delivery-controller/README.md)，依勘誤 E-5（Orca）、E-6（察覺卡住）讀。現況研究：[research.md](../../../docs/research/2026-10-03/orca-dispatch/research.md)，驗證與更正：[verification.md](../../../docs/research/2026-10-03/orca-dispatch/verification.md)。

## What Changes

- **orchestrate skill**：從交接包開始，依序叫 spec-to-plan，把 design 與 plan 登記到 loopctl，停在 ◆確認開工；核准後只依 `next` 行動，結果只經 loopctl 匯入（D69(5)、AC-O16）。plan-to-code 的派工改經 loopctl 與 Orca；其他步驟是否跟著改，見待決 3。
- **政策檔 `workflow.yaml`**：加入兩個 profile（Implementer：Orca 的 Claude agent、`claude-opus-5-5`、effort 依 task；Reviewer：Orca 的 Codex agent、`gpt-6-astra` xhigh）與卡住門檻（預設 30 分鐘），以人工 `policy_change` 核准（D53）。
- **R1 preflight**：對兩個 profile 各跑一次。model、effort、cwd 由 native 紀錄讀回；權限負例（寫出擁有範圍、`git push`、`gh`、派工以外的 `orca` 子命令、`loopctl decide` 都被拒）；worker 把 Orca 的 preamble 當成任務並交出 `worker_done`。receipt 記錄 Orca 與 agent CLI 的版本。`next` 只在 profile 驗證過、政策已核准且 digest 相符時給派工；Orca 版本改變時先重跑（D76(5)）。
- **外部寫入**：派工、後續提示與停止都先登記（identity、目標、payload digest、marker），再經 Orca 執行一次並讀回；結果不明轉 unknown 並 Blocked，由人以 `resolve_operation` 處理；核准失效時，還沒送出的操作標為 superseded（E-1）。
- **Assignment 與結果**：assignment 帶 run／task／attempt、核准的版本與 digest、擁有範圍、AC ID 與驗法；結果檔先完整保存，核對身份與版本後只匯入一次；重複到達不重複生效，同一 attempt 內容不同則保留雙方並 Blocked。
- **觀察**：讀 Orca 的 worker 狀態與 native 紀錄。連續讀取失敗有上限，到限 Blocked，由人以 `resolve_read` 授權一次新的讀取。writer 結束只認兩種證據：結果已匯入且 native turn 已完成，或停止已經確認。
- **察覺卡住**：session 結束卻沒交結果、turn 以 API 錯誤結束，或連續 30 分鐘沒有新輸出時，停止派工、保存理由與證據並交人；unknown 不視為已停止（D79、E-6）。
- **能力證據矩陣**：依接法（Orca＋claude、Orca＋codex）分欄，每項能力標 `fake`、`profile-probe`、`real-E2E` 或 `none`（AC-G19、D22）。
- **engineer 工作區 clear 時機的實驗**（D76(6)；見待決 11）。
- **`status`／`next`／`decide`**：顯示 attempt、外部寫入與卡住理由；envelope 的 `safety`、`blocked` 開始有值；`decide` 新增 `resolve_read`、`resolve_operation`；`budget_extension` 的目標依 D79 調整（待決 13）。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

三份都在 `openspec/specs/`（Feature 1 併入）。已有的 requirement 以 MODIFIED 補上 Feature 2 成立的部分，其餘從需求輸入以 ADDED 帶入；每條只寫本 Feature 結束時成立的部分（roadmap「跨 Feature 的 AC」）。

- `delivery-orchestration`：MODIFIED ORC-01、ORC-03；ADDED ORC-08。
- `delivery-gates`：ADDED GAT-05、GAT-08。
- `durable-delivery`：MODIFIED DUR-02、DUR-08；ADDED DUR-03、DUR-04、DUR-06、DUR-09。

首先驗證的 AC（19 條）：O02、O06、O16、G11、G12、G19、D04、D05、D06、D08、D12、D13、D16、D17、D18、D19、D21、D22、D23。其中 O02、D13、D16、D17 從 Feature 1 移來，D17 照 E-6 改成察覺卡住。另外 D07、O07、O23 在本 Feature 成立一部分；O29、O30 隨 ORC-01、ORC-03 的 MODIFIED 一起保留。哪些能在本 Feature 完成、哪些只成立一部分，要等待決 1、5 定了才能確定（verification §二）。

## 和 roadmap 不同的地方

目前沒有。待決 1、4、5、11 的回答可能改變 roadmap 的 Feature 2 列，屆時記在這裡並更新 roadmap。

## 不做

- G1、G3、push、PR 與 CI 讀取：Feature 3。
- Reviewer 派工、G2、finding 迴圈、`accept`／`return`、PR Pass 與 review 發布：Feature 4；本 Feature 的 Codex profile 只跑 R1。
- 只有 OpenCode 的環境（AC-D24）：Feature 2b。本日目標與多個 Feature 同時執行：Feature 5。
- 沒有 Orca 的部署（AC-D20）、adopt、Project Lead 委派、Retro：M2。
- 主動執行時間與各角色的時間上限（D79 拿掉）；常駐 watchdog（D47）。
- 參考實作 `delivery/thin-controller@fcefecc` 只作參考，沿用的程式照 TDD 重做，舊測試、審查與 preflight 紀錄不算證據（D75）。

## Impact

- 程式：`src/loopctl/` 新增 Orca adapter、外部寫入、觀察、assignment 與結果匯入、preflight、卡住偵測；延伸 `next`、`decisions`、`cli`、`state`。讀 `workflow.yaml` 的 profile 需要決定是否加入 pyyaml 作執行依賴（design）。
- 規模：驗證後估計程式約 3,000～4,400 行、含測試約 10,000～14,600 行，是 Feature 1 的 1.8～2.6 倍，約 12～18 個 task（verification §一第 2 點）。
- 環境：Orca 要以 git repo 註冊 loop-engineering，並建立 `engineer`、`reviewer` 工作區；Orca 的權限預設要改（待決 2）。
- Skills：新增 `skills/orchestrate/`；plan-to-code 要改，spec-to-plan 的 `tasks.md` 格式可能要變成機器可讀（待決 3）。

## 待決與依賴

| # | 項目 | 是否阻擋 Design | 負責 |
| --- | --- | --- | --- |
| 1 | 要不要拆：校準後是 Feature 1 的 1.8～2.6 倍；可先切出「R1 preflight＋Orca adapter＋能力矩陣」 | 是 | Project Lead（roadmap 重切） |
| 2 | Orca worker 的權限由哪裡帶：Orca 全域設定（也改到使用者自己的分頁），或自己開 terminal（失去 Orca 的 stop 與 launch 紀錄）。目前預設是跳過權限，R1 一定不過 | 是 | Project Lead |
| 3 | orchestrate 跑的 run 裡，plan-to-code 的哪些步驟改經 loopctl 與 Orca：派工、attempt 計次（D69(2)）、收件檢查、逐 task 審查、ticket 紀錄 | 是 | Project Lead |
| 4 | `engineer` 是目前 Feature 的 worktree 的名稱，還是一個固定 checkout（後者和每個 Feature 一個 branch 衝突） | 是 | Project Lead |
| 5 | Reviewer 的放置（每次一個 clone，或 git worktree 加 sandbox），以及 Codex 的 R1 在本 Feature 還是 Feature 4 | 是 | Project Lead |
| 6 | worker 繼承的設定（本機 gateway、hooks、plugins、預設 model）哪些要固定或排除 | 是 | Project Lead |
| 7 | D38（OpenCode 預設、Orca／Codex／Claude Code 選配）確認為部署層級的選擇，或修訂 | 是（DUR-09 的寫法） | Project Lead |
| 8 | Orca mailbox 由誰消化；worker 的 `ask` 與 escalation 是否一律交人 | 是 | spec，Project Lead 同意 |
| 9 | orchestrate 的 ticket 留言是否算 DUR-06 的外部寫入（D60 的「另議」） | 是 | Project Lead |
| 10 | worker session 的 API 或 infra 錯誤：照 D16 重試 2 次，還是照 D79 算卡住交人 | 是 | Project Lead |
| 11 | clear 時機的實驗：保留、移到 Feature 3，或依 Feature 1 的數據定為每個 task 清空（修訂 D76(6)） | 否 | Project Lead |
| 12 | Feature 2 自己的 task 用什麼派：照 Feature 1 用 `claude -p`，或手動經 Orca | 否（plan-to-code 前定） | Project Lead |
| 13 | D79 沒提到的單次呼叫上限是否保留；`budget_extension` 的 `active`、`ci_wait`、`attempts` 目標怎麼處理；agent CLI 換版是否重跑 R1 | 否 | spec，Project Lead 同意 |
| — | 依賴：Feature 1 已接受並 merge；base 是 `main@458ab77` | 否 | — |
| — | Orca 1.4.218；R1 尚未在這個版本跑過 | 否 | Engineer |
