# Proposal：loopctl preflight：確認 Orca 的 Claude、Codex worker 能安全派工（orca-preflight）

> 由 Feature 2 切出（D80）；範圍照 roadmap 的 Feature 2a 列。Project Lead 2026-10-03 同意範圍與預設（「照這份」）。

## Why

Feature 2 要經 Orca 派 Implementer，但派工前必須先知道派出去的 worker 是不是我們要的：實際跑的 model 與 effort、在哪個目錄、能不能做不該做的事。目前沒有任何東西核對這些，而 Orca 1.4.218 在本機預設以 `--dangerously-skip-permissions`（Claude）與 `--dangerously-bypass-approvals-and-sandbox`（Codex）啟動 worker（verification §一第 1 點）。DUR-02 規定「未驗證的 profile SHALL NOT 被默認可用」。本 Feature 交付 R1：在派工之前，對兩個 profile 各派一個探測 worker，用 native 紀錄與權限負例證明它們可用；沒驗證過就不給派工。實測結果也回答 Feature 2 的 spec 需要的事實（D80(3)）。

需求輸入：[`docs/requirements/delivery-controller/`](../../../docs/requirements/delivery-controller/README.md)，依勘誤 E-5（Orca）讀。研究：[research.md](../../../docs/research/2026-10-03/orca-dispatch/research.md) §4、§6、§7，以及 [verification.md](../../../docs/research/2026-10-03/orca-dispatch/verification.md)。

## What Changes

- **政策檔 `workflow.yaml` 的 `profiles`**：
  - `implementer`：Orca 的 Claude agent、`claude-opus-5-5`；
  - `reviewer`：Orca 的 Codex agent、`gpt-6-astra`、effort xhigh（D76(2)）。
  - 每個 profile 寫明 transport、runtime、model、effort、權限設定與可寫範圍，以人工 `policy_change` 核准並綁定 digest（D53）。
- **`loopctl preflight --role <role>`**：經 Orca 派一個探測 worker，核對下列各項。每項各自判定，任一項不成立就是 `unverified`，並寫明原因：
  - model、effort 由 native 紀錄讀回，與 profile 相符；
  - 實際工作目錄、repo、branch 由 native 紀錄讀回，與要求相符；不以 shell cwd 推定；
  - 權限負例：寫出可寫範圍、`git push`、`gh`、回報結果以外的 `orca` 子命令、`loopctl decide`。每一項都要觀察到被拒**而且**資源沒有改變；Reviewer 另加「不能改作者的 branch」；
  - worker 把 Orca 的 preamble 當成任務，並交出 `worker_done`；
  - 停止有確認；
  - 兩個 profile 的 model 相同就是 `unverified`（D52）。
- **Receipt**：記錄以下內容；不含 dispatch capability 等憑證（DUR-09）：
  - role、profile 與 `workflow.yaml` 的 digest；
  - Orca 與 agent CLI 的版本；
  - native session ID 與讀回值；
  - 每個負例的命令、拒絕與資源檢查；
  - worker 實際載入的設定（待決 2）；
  - verdict 與逐項原因。
- **`status`／`next`**：`status` 顯示每個 profile 是否驗證過與原因。下列任一情況，核准後 `next` 不給派工，改回報需要先跑 preflight：
  - profile 沒有對應目前政策 digest 的 verified receipt；
  - Orca 或 agent CLI 的版本與 receipt 不同（D76(5)，延伸到 agent CLI，見待決 3）。
- **未選用的接入**：Herdr、OpenCode 不存在或故障時，不影響已選的兩個 profile，也不會被呼叫（AC-D23）。
- **能力證據矩陣**：依接法分欄（Orca＋claude、Orca＋codex），每項能力標 `fake`、`profile-probe`、`real-E2E` 或 `none`。本 Feature 填 `fake` 與 `profile-probe`（AC-G19、D22）。
- **兩個 profile 的真實 R1 各跑一次**，receipt 存進 repo，作為驗收證據。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `delivery-gates`：ADDED GAT-05（只有 Reviewer profile 的部分：model 讀回、不同模型、隔離負例；G2 判定在 Feature 4）、GAT-08（能力證據矩陣；真實驗收的 finding 迴圈部分在後面的 Feature）。
- `durable-delivery`：MODIFIED DUR-02（worker 只能寫授權範圍、不能呼叫狀態寫入命令，以真實負例驗證，未驗證的 profile 不可用）；ADDED DUR-09（profile、preflight 與未選用接入）。

AC（10 條）：D18、D19、D22、D23、D26、D27、D28、G19、G23、G24。其中 D26、D27、D28、G23、G24 是新 ID，依據見下一節。D18、D19、D22、D23、G19 都只成立 R1 與矩陣的部分：每次派工的核對在 Feature 2，`real-E2E` 欄由 Feature 2～4 與 R3 補上，D23 的 OpenCode-only 變體在 M2。

## 和 roadmap 不同的地方

依 Feature 1 的做法（原 AC 的觸發情境在本 Feature 不存在時，成立的部分改用新 ID，原 ID 不改寫、不重用）：

| 原 AC | 觸發情境 | 首先驗證 | 本 Feature 成立的部分 |
| --- | --- | --- | --- |
| AC-G11 有效獨立 review | 派 Reviewer 做 G2 | Feature 4 | 兩個角色同一 model 時 Reviewer profile 不可用：新增 AC-G23 |
| AC-G12 局部 review 或隔離無法證明 | 判定 G2 | Feature 4 | Reviewer 的隔離負例：新增 AC-G24 |

另外三個新 ID 來自 requirement 本文與已確認的範圍：AC-D26（沒有適用的 R1 就不派工，D76(5)、D81）、AC-D27（worker 的權限負例，DUR-02）、AC-D28（worker 載入的設定與憑證，DUR-09 與待決 2）。

## 不做

- 實際派 task、assignment、結果匯入、外部寫入的登記與讀回、卡住偵測、orchestrate skill：Feature 2。
- 派 Reviewer 做審查、G2：Feature 4。
- OpenCode 的 profile（AC-D24）：Feature 2b。
- 改使用者 Orca 的全域設定：預設不改（待決 1）。
- 參考實作 `fcefecc` 的 `preflight.py` 只作參考，照 TDD 重做；舊的 preflight 紀錄不算證據（D75）。

## 待決與依賴

| # | 項目 | 是否阻擋 Design | 負責 |
| --- | --- | --- | --- |
| 1 | 權限設定怎麼帶到 worker。預設每次自己開 terminal，帶 CLI 自己的 `--settings`、`--session-id` 或 sandbox 參數，不改使用者的 Orca 全域設定；代價是 Orca 不能幫忙停 worker，要由 loopctl 關掉 terminal 作為停止證據。只有 live probe 證明這條走不通時，才回來問要不要改全域設定。**照預設（2026-10-03）** | 否（design 依此做；若要改全域設定則回到 Project Lead） | Engineer；改全域設定由 Project Lead 決定 |
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
