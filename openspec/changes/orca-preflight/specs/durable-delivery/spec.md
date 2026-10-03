## MODIFIED Requirements

### Requirement: DUR-02 唯一派工權與安全重派

同一 repo＋feature SHALL 同時只有一個持有協調權的呼叫者；run ID、session 或 clone 不同，SHALL NOT 產生第二份協調權。協調權以 `claim` 取得的 token 表示，狀態只保存 token 的 digest；每個寫入命令 SHALL 核對 token。沒有協調權的呼叫者 SHALL 只能讀取狀態。

Worker SHALL 只能寫入授權的範圍與自己的結果位置，並由 runtime 的權限設定拒絕呼叫狀態寫入命令（例如 `loopctl decide`）。這個限制 SHALL 以真實 runtime 的負例驗證（DUR-09 的 preflight）；未驗證的 profile SHALL NOT 被默認可用。系統不承諾偵測或阻止同一 OS 帳號下繞過 runtime 權限的蓄意偽造（D48）。

#### Scenario: AC-D03 兩個 run 搶同一 feature
- **WHEN** 兩個呼叫者同時對同一 repo＋feature 執行 `claim`
- **THEN** 恰好一方取得協調權；另一方收到已被持有的結果與目前 owner，之後仍可讀取狀態，但任何寫入命令都因 token 不符被拒，狀態不變

#### Scenario: AC-D27 Worker 的權限負例
- **WHEN** preflight 讓探測 worker 逐一嘗試：寫入可寫範圍以外的位置、`git push`、`gh`、回報結果以外的 `orca` 子命令、`loopctl decide`
- **THEN** 每一項都要觀察到被拒，**而且**資源沒有改變（檔案不存在、遠端 ref 未變、呼叫紀錄沒有新增、狀態 revision 未變），該項才通過；任一項沒有被拒或資源改變，profile 為 `unverified`，receipt 列出該項的命令、觀察到的結果與資源檢查

## ADDED Requirements

### Requirement: DUR-09 Adapter 與 runtime/model 解耦

核心 SHALL 依穩定的角色與能力契約執行；transport、runtime、provider、model 與 effort SHALL 分欄保存。每個部署 SHALL 在 `workflow.yaml` 的 `profiles` 從核准的接法中選用，profile 經人工 `policy_change` 核准並綁定 digest；「選配」指不是每個部署都必須有該工具（D38、D81）。本部署選用 Orca：Implementer 是 Orca 的 Claude agent 與 `claude-opus-5-5`，Reviewer 是 Orca 的 Codex agent 與 `gpt-6-astra`、effort xhigh（D76）。Orca 專有的 Run、Task、Dispatch 欄位 SHALL NOT 成為共用契約的必填條件。未選用的接入 SHALL NOT 被呼叫，也 SHALL NOT 阻斷已選的路徑。

派工之前，`loopctl preflight` SHALL 對每個要用的 profile 執行受限的能力探測：經 Orca 派一個探測 worker，由 native 紀錄讀回 model、effort 與實際工作目錄，再以 git 讀該目錄的 repo 與 branch，逐項和 profile 比對；做 DUR-02 的權限負例；確認 worker 把 Orca 交付的任務當成任務並交出 `worker_done`；確認停止。每一項各自判定，任一項不成立 SHALL 為 `unverified` 並列出原因；SHALL NOT 以 shell cwd、`current`、角色名稱或 Orca 的啟動參數推定實際的 model 或位置。結果 SHALL 寫成 receipt，記錄 role、profile 與 `workflow.yaml` 的 digest、Orca 與 agent CLI 的版本、native session ID、讀回的值、每個負例的結果，以及 worker 實際載入的 gateway、plugin 與 hook。Receipt、能力證據與交接文件 SHALL NOT 含 credentials 或 dispatch capabilities。

已核准的 run 中，`next` SHALL 只在要派的角色有一份 `verified` receipt，而且它對應目前的政策 digest、Orca 版本與 agent CLI 版本時，才回報可以派工（D76(5)、D81）。能力不足 SHALL 具體 Blocked，SHALL NOT 自動換用未核准的工具或放寬隔離。

#### Scenario: AC-D18 正確 workspace 與設定
- **WHEN** preflight 讀回的 model、effort、工作目錄、repo 或 branch 與 profile 不符，或只有 input accepted 而沒有 native turn，或 native 紀錄讀不到 effort 或工作目錄、只有 shell cwd 相符
- **THEN** profile 為 `unverified`，receipt 保存要求值、實際值與 native session ID；不宣稱 profile 可用，也不從 shell cwd、`current`、角色名稱或 Orca 的啟動參數推定

#### Scenario: AC-D19 能力缺口與替換
- **WHEN** profile 缺少 model 等必要設定，或探測 worker 沒有把 Orca 交付的任務當成任務、交不出 `worker_done`，或停止無法確認
- **THEN** profile 為 `unverified`，顯示具體 Blocked 與最小能力需求，保留已取得的證據；不自動改用未核准的 runtime 或 model，也不放寬權限

#### Scenario: AC-D22 兩種接法分別驗證
- **WHEN** 一個 profile 為 `verified`，另一個 profile 的 model、隔離或 lifecycle 尚未驗證
- **THEN** receipt 與能力證據矩陣按接法分欄保存可用能力與缺口，不共用成功標記，也不宣稱完整 E2E 已完成

#### Scenario: AC-D23 未選用的接入故障
- **WHEN** 已選的兩個 profile 都可用，而未選用的接入（Herdr、OpenCode）不存在、未登入或連線失敗；或已選 profile 本身的工具（Orca、Claude Code、Codex CLI）不存在或無法使用
- **THEN** 前者不影響已選的 profile，preflight 不呼叫未選用的接入；後者該 profile 為 `unverified` 並 Blocked，不自動改用其他 runtime 或 model

#### Scenario: AC-D26 沒有適用的 R1 就不派工
- **WHEN** run 已核准，而要派的角色沒有 `verified` receipt，或 receipt 對應的政策 digest、Orca 版本或 agent CLI 版本和目前不同
- **THEN** `next` 不回報派工，改回報要先執行 preflight 的 profile 與原因；`status` 顯示每個 profile 的驗證狀態與原因；重新執行 preflight 得到 `verified` 之後，`next` 才回報可以派工

#### Scenario: AC-D28 Worker 載入的設定與憑證
- **WHEN** preflight 寫出 receipt
- **THEN** receipt 記錄 worker 實際載入的 gateway、plugin 與 hook；profile 排除的 plugin 或 hook 被觀察到載入時，profile 為 `unverified`；receipt、能力證據矩陣與提交到 repo 的證據都不含 dispatch capability 或其他 credentials
