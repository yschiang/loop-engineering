# Proposal：loopctl preflight：確認 Orca 的 Claude、Codex worker 能安全派工（orca-preflight）

> 由 Feature 2 切出（D80）；範圍照 roadmap 的 Feature 2a 列。Project Lead 2026-10-03 同意範圍與預設（「照這份」）。

## Why

Feature 2 要經 Orca 派 Implementer，但派工前必須先知道派出去的 worker 是不是我們要的：實際跑的 model 與 effort、在哪個目錄、能不能做不該做的事。目前沒有任何東西核對這些，而 Orca 1.4.218 在本機預設以 `--dangerously-skip-permissions`（Claude）與 `--dangerously-bypass-approvals-and-sandbox`（Codex）啟動 worker（verification §一第 1 點）。DUR-02 規定「未驗證的 profile SHALL NOT 被默認可用」。本 Feature 交付 R1：在派工之前，對兩個 profile 各派一個探測 worker，用 native 紀錄與權限負例證明它們可用；沒驗證過就不給派工。實測結果也回答 Feature 2 的 spec 需要的事實（D80(3)）。

需求輸入：[`docs/requirements/delivery-controller/`](../../../docs/requirements/delivery-controller/README.md)，依勘誤 E-5（Orca）讀。研究：[research.md](../../../docs/research/2026-10-03/orca-dispatch/research.md) §4、§6、§7，以及 [verification.md](../../../docs/research/2026-10-03/orca-dispatch/verification.md)。

## What Changes

- **政策檔 `workflow.yaml` 的 `profiles`**：
  - `implementer`：Orca 的 Claude agent、`claude-opus-5-5`；
  - `reviewer`：Orca 的 Codex agent、`gpt-6-astra`、effort xhigh（D76(2)）。
  - 每個 profile 寫明 transport、runtime、model、探測時的 effort、權限設定、可寫範圍、允許的 `orca` 子命令，以及保留與排除的設定來源（待決 2）；以人工 `policy_change` 核准並綁定 digest（D53）。逐 task 的 effort 屬於派工，在 Feature 2。
- **`loopctl preflight`**：以一個 run 為脈絡，該 run 的政策未核准就拒絕執行；不需要協調權，也不寫 feature 狀態。先持久記錄 marker 與 handle，再經 Orca 派一個帶唯一 marker 的探測 worker 到探測工作區，逐項判定，任一項不成立就是 `unverified` 並寫明原因：
  - 恰好一份 native 紀錄含 marker；model、effort、工作目錄取自那個 turn，和 profile 與探測工作區相符；
  - 權限負例：寫出可寫範圍、`git push`、`gh`、允許清單以外的 `orca` 子命令、`loopctl decide`。「被拒」指 native 紀錄顯示 worker 嘗試了、被 runtime 的權限或 sandbox 擋下，而且資源沒變；Reviewer 另做「改不到 Implementer 探測工作區的檔案與 branch」；
  - worker 把 Orca 交付的任務當成任務，並交出 `worker_done`；
  - 停止以 process-info 確認探測 agent 的程序已不存在；
  - 沒有載入被排除的設定；兩個 profile 的 model 不同（D52）。
- **Receipt**：記錄脈絡 run、digest、Orca 與 agent CLI 的版本、marker、native session ID、讀回值、實際權限模式、執行模式、權限設定的來源、任務的送達方式、每個負例、載入的設定，以及判定依據的 native 紀錄摘錄（遮蔽後）與 digest。native transcript 約 30 天會被清掉，所以摘錄要留在 receipt（verification §三）。不含 dispatch capability 等憑證。中斷的 preflight 不產生 `verified`；下一次先停掉殘留的探測 worker（清理結果記在持久紀錄與輸出），停不掉就不派新的探測 worker。目前版本讀不到時，receipt 不適用。
- **適用的 receipt**：receipt 存在 run 狀態之外，帶自身內容的 digest。每個 profile 以最新一份為準；對一個 run，只有 `verified`、綁定的 digest 等於該 run 已核准的 digest、Orca 與 agent CLI 版本都等於目前值才適用（D81），所以已核准同一 digest 的 run 可以共用。
- **`status`／`next`**：`status` 顯示每個 profile 的驗證狀態、版本與原因。已核准的 run 中，政策未核准時 `next` 回報需要 `policy_change`；Implementer 沒有適用的 receipt 時回報 `preflight` 動作，附 profile 與原因。重跑 preflight 不需要人工決策。
- **ORC-01**：controller 原本「不啟動 agents」；改為只有 `preflight` 可以依已核准的政策、以固定的命令經 Orca 派出、讀回、停止探測 worker；`preflight`、`status`、`next` 可以以固定的命令讀 Orca 與 agent CLI 的版本。仍然不常駐，也不執行呼叫者或 worker 提供的命令。
- **未選用的接入**：Herdr、OpenCode 不存在或故障時，不影響已選的 profile，也不會被呼叫（AC-D23）。
- **能力證據矩陣**：依接法分欄（Orca＋claude、Orca＋codex），每格記證據類型（`fake`、`profile-probe`、`real-E2E`）與 verdict，沒執行的標 `none`。本 Feature 填 `fake` 與 `profile-probe`（AC-G19、D22）。
- **兩個 profile 的真實 R1 各跑一次**，receipt 存進 repo（見「驗收條件」）。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `delivery-orchestration`：MODIFIED ORC-01（`preflight` 是 controller 唯一可以派出 agent 的地方）。
- `delivery-gates`：ADDED GAT-05（只有 Reviewer profile 的部分：model 讀回、不同模型、隔離負例；G2 判定在 Feature 4）、GAT-08（能力證據矩陣；真實驗收的 finding 迴圈部分在後面的 Feature）。
- `durable-delivery`：MODIFIED DUR-01（狀態檔的下一步只依 run 狀態，可不可以派工由 `status`、`next` 依 receipt 與目前版本重算）、DUR-02（worker 只能寫授權範圍、不能呼叫狀態寫入命令，以真實負例驗證）；ADDED DUR-09（profile、preflight、receipt、適用規則與派工管制）。

AC（14 條）：D01、D18、D19、D22、D23、D26、D27、D28、D29、D30、D31、G19、G23、G24。新 ID 的依據見下一節。D18、D19、D22、D23、G19 都只成立 R1 與矩陣的部分：每次派工的核對在 Feature 2，`real-E2E` 欄由 Feature 2～4 與 R3 補上，D23 的 OpenCode-only 變體在 M2。

## 驗收條件

Project Lead 2026-10-03 決定（回答「Implementer 必須 verified」）：

- 兩個 profile 都要有真實 R1 的 receipt，結果如實記錄。
- Implementer（Claude）的 receipt 必須是 `verified`，因為 Feature 2 靠它派工。
- Reviewer（Codex）可以是 `unverified`；缺口寫進能力證據矩陣，而且在 Feature 4 派 Reviewer 之前必須解決。

| 驗法 | AC |
| --- | --- |
| CI 的可控制測試（fake `orca`，CI 上沒有 Orca） | 全部 14 條 |
| 另外以真實 receipt 證明 | D29（Implementer 為 `verified`）、D18、D27、D28、G24（Reviewer，結果如實）、G19、D22（矩陣的 `profile-probe` 欄） |

## 和 roadmap 不同的地方

依 Feature 1 的做法（原 AC 的觸發情境在本 Feature 不存在時，成立的部分改用新 ID，原 ID 不改寫、不重用）：

| 原 AC | 觸發情境 | 首先驗證 | 本 Feature 成立的部分 |
| --- | --- | --- | --- |
| AC-G11 有效獨立 review | 派 Reviewer 做 G2 | Feature 4 | 兩個角色同一 model 時 Reviewer profile 不可用：新增 AC-G23 |
| AC-G12 局部 review 或隔離無法證明 | 判定 G2 | Feature 4 | Reviewer 的隔離負例：新增 AC-G24 |

AC-D01 是 Feature 1 已驗收的 AC；MODIFIED DUR-01 改了它的 THEN（`status` 另顯示依 receipt 與目前版本判定的結果），所以重新列入本 Feature 的驗收。

其他新 ID 來自 requirement 本文與已確認的範圍：

- AC-D26：沒有適用的 R1 就不派工（D76(5)、D81）。
- AC-D27：worker 的權限負例（DUR-02）。
- AC-D28：worker 載入的設定與憑證（DUR-09、待決 2）。
- AC-D29：探測全部成立時的主流程。
- AC-D30：政策未核准時不探測。
- AC-D31：preflight 中斷後的處理。

### 需求原文沒有帶入的句子

| 原文（需求輸入） | 處理 |
| --- | --- |
| DUR-09「OpenCode SHALL 仍是預設 runtime（D38）」「Orca、Codex／ChatGPT 相關入口及 Claude Code SHALL 為選配，使啟動／resume、派工、結果回收與工作區管理不依賴這些選配程式」 | 依 D81 讀成部署層級：每個部署在 profiles 自選，本部署選 Orca＋Claude Code＋Codex；spec 寫「選配指不是每個部署都必須有」 |
| DUR-09「不引入另一套外層 orchestrator」 | 由 D76(3)(4) 處理：協調權與人工決策在 loopctl，Orca 只傳遞；orchestrate 在 Feature 2 |
| DUR-09「派工前 SHALL 核對安裝版本、工具權限、實際 repo/workspace/branch、認證可用性與結果通道」 | preflight 核對全部；每次派工的核對在 Feature 2 |
| DUR-02「實際 worktree SHALL 只有一個有效 writer」「Timeout、lease 到期…不等於舊 worker 已停止」「對可核對的身份、版本、digest…不符保存證據並 Blocked」 | 屬於派工與重派：Feature 2 |
| DUR-02 第二段（第一片只有一個 Implementer worktree；Reviewer 用獨立 clone） | Reviewer 的獨立 clone 帶入 GAT-05；其餘在 Feature 2 |
| GAT-05 的 G2 判定、verdict 規則、PR identity 之後才派正式 review | Feature 4 |
| GAT-08「真實驗收 SHALL 包含至少一次 finding → fix → re-review…」 | Feature 4 與 M1 驗收 |
| AC-D04 的停止判定 | 「process-info 確認、idle／done 不算證據」帶入 DUR-09 的停止；writer 結束的判定在 Feature 2 |

## 不做

- 實際派 task、assignment、結果匯入、外部寫入的登記與讀回、卡住偵測、orchestrate skill：Feature 2。
- 派 Reviewer 做審查、G2：Feature 4。
- OpenCode 的 profile（AC-D24）：Feature 2b。
- 改使用者 Orca 的全域設定：預設不改（待決 1）。
- 參考實作 `fcefecc` 的 `preflight.py` 只作參考，照 TDD 重做；舊的 preflight 紀錄不算證據（D75）。

## 待決與依賴

| # | 項目 | 是否阻擋 Design | 負責 |
| --- | --- | --- | --- |
| 1 | 權限設定怎麼帶到 worker。預設每次自己開 terminal，帶 CLI 自己的 `--settings`、`--session-id` 或 sandbox 參數，不改使用者的 Orca 全域設定；代價是 Orca 不能幫忙停 worker，停止要以 process-info 確認探測 agent 的程序已不存在。只有 live probe 證明這條走不通時，才回來問要不要改全域設定。**照預設（2026-10-03）** | 否（design 依此做；若要改全域設定則回到 Project Lead） | Engineer；改全域設定由 Project Lead 決定 |
| 2 | worker 繼承的使用者設定。**已定（2026-10-03）**：跟 Feature 1 效果一樣。保留本機 gateway、superpowers 與 Orca 的 hook；關掉 ponytail、ralph-wiggum，以及 caveman 與 Herdr 的 hook。receipt 記下實際載入的 gateway、plugin 與 hook | 否 | Project Lead（回答「跟 Feature 1 效果一樣」） |
| 3 | R1 何時重跑。**已定（2026-10-03）**：Orca 或 agent CLI（Claude Code、Codex CLI）的版本和 receipt 不同就重跑；重跑不需要人工決策，沒過才停下交人。記為 D81(2)，補充 D76(5) | 否 | Project Lead（回答「Orca 或 agent CLI 換版都重跑」） |
| 4 | D38 的讀法。**已定（2026-10-03，D81）**：部署層級。每個部署在 profiles 選接法；M1 選 Orca＋Claude Code＋Codex。DUR-09 照此寫，Orca 專有欄位不進共用契約 | 否 | Project Lead（回答「A：部署層級」） |
| 5 | effort 的判定：讀回的 effort 與要求不符或讀不到，都算 `unverified`（D76(2) 要求 Reviewer 的 effort 由 native 紀錄讀回；兩種 runtime 都讀得到）。**照預設（2026-10-03）** | 否 | spec，Project Lead 同意 |
| 6 | 探測 worker 在哪裡跑：預設由人一次性在 Orca 以 git repo 註冊 loop-engineering，並建立探測用的工作區；preflight 只核對它們存在與位置。**照預設（2026-10-03）** | 否 | Project Lead（環境設定） |
| 7 | Reviewer 的放置要讓它改不到作者的 branch（DUR-02 的獨立 clone）。R1 依此設計負例 | 否 | Engineer（design） |
| 8 | spec-to-plan 的研究要在 Orca 實際派探測 worker（scratch Run），會改變 Orca 狀態。開始前要有授權 | 否（spec-to-plan 前） | Project Lead |
| 9 | 本 Feature 自己的 task 照 Feature 1 用 `claude -p` 派；Orca 在本 Feature 完成前還沒驗證過。**照預設（2026-10-03）** | 否 | Project Lead（預設照 Feature 1） |
| — | 依賴：Feature 1 已 merge；base 是 `main@458ab77`。D80 的 PR #45 merge 前，研究文件以本 branch 的副本為準 | 否 | — |
| — | Orca 1.4.218；Claude Code、Codex CLI 會自己更新（待決 3） | 否 | Engineer |
