## MODIFIED Requirements

### Requirement: DUR-02 唯一派工權與安全重派

同一 repo＋feature SHALL 同時只有一個持有協調權的呼叫者；run ID、session 或 clone 不同，SHALL NOT 產生第二份協調權。協調權以 `claim` 取得的 token 表示，狀態只保存 token 的 digest；每個寫入命令 SHALL 核對 token。沒有協調權的呼叫者 SHALL 只能讀取狀態。

Worker SHALL 只能寫入授權的範圍與自己的結果位置，並由 runtime 的權限設定拒絕呼叫狀態寫入命令（例如 `loopctl decide`）。這個限制 SHALL 以真實 runtime 的負例驗證（DUR-09 的 preflight）；未驗證的 profile SHALL NOT 被默認可用。系統不承諾偵測或阻止同一 OS 帳號下繞過 runtime 權限的蓄意偽造（D48）。

#### Scenario: AC-D03 兩個 run 搶同一 feature
- **WHEN** 兩個呼叫者同時對同一 repo＋feature 執行 `claim`
- **THEN** 恰好一方取得協調權；另一方收到已被持有的結果與目前 owner，之後仍可讀取狀態，但任何寫入命令都因 token 不符被拒，狀態不變

#### Scenario: AC-D27 Worker 的權限負例
- **WHEN** preflight 讓探測 worker 逐一嘗試：寫入可寫範圍以外的位置、`git push`、`gh`、profile 允許清單以外的 `orca` 子命令（至少一個會改變 Orca 狀態的子命令）、`loopctl decide`
- **THEN** 一項只有在 native 紀錄顯示 worker 嘗試了該命令、該命令被 runtime 的權限或 sandbox 拒絕而沒有執行，**而且**資源沒有改變（檔案不存在、遠端 ref 未變、沒有新的 Orca 物件或 `gh` 寫入、狀態 revision 未變）時才成立；worker 沒有嘗試、只自述拒絕，或命令有執行而由 loopctl 自己的核對拒絕，該項都不成立。任一項不成立，profile 為 `unverified`，receipt 列出該項的命令、觀察到的結果與資源檢查

## ADDED Requirements

### Requirement: DUR-09 Adapter 與 runtime/model 解耦

核心 SHALL 依穩定的角色與能力契約執行；transport、runtime、provider、model 與 effort SHALL 分欄保存。每個部署 SHALL 在 `workflow.yaml` 的 `profiles` 從核准的接法中選用；「選配」指不是每個部署都必須有該工具（D38、D81）。Profile SHALL 經人工 `policy_change` 核准並綁定 digest。Runtime 專有的識別（例如 Orca 的 Run、Task、Dispatch）SHALL NOT 成為共用契約的必填條件。未選用的接入 SHALL NOT 被呼叫，也 SHALL NOT 阻斷已選的路徑。接入工具的名稱 SHALL NOT 被當成已有可派工的能力；只有經 preflight 驗證的能力可以使用。

**Preflight**：派工之前，`loopctl preflight` SHALL 對 profile 執行受限的能力探測。`workflow.yaml` 沒有綁定目前 digest 的人工 `policy_change` 時，SHALL 拒絕執行並說明原因。探測 SHALL 經所選 runtime 派一個探測 worker 到 preflight 指定的探測工作區，任務帶一個唯一的 marker，並逐項判定：

- **讀回**：native 紀錄 SHALL 恰好有一份含這個 marker；model、effort 與實際工作目錄取自 marker 所在的 turn，再讀出該目錄的 repo 與 branch。model 與 effort 和 profile 比對（effort 是探測時要求的值），位置和探測工作區比對。找不到或有多於一份含 marker 的紀錄，該項不成立。SHALL NOT 以 shell cwd、`current`、角色名稱、runtime 的啟動參數、時間先後或相同目錄推定。
- **權限**：做 DUR-02 的負例（AC-D27）；Reviewer 另做 GAT-05 的隔離負例。
- **任務與回報**：worker 把 runtime 交付的任務當成任務，並以 runtime 的回報管道交出完成（Orca 為 `worker_done`）。探測 worker 有 native turn，即視為 runtime 的認證可用。
- **停止**：停止 SHALL 以 process-info 確認探測 agent 的程序已不存在；runtime 的 liveness、停止回應或 terminal 已關閉，SHALL NOT 單獨作為證據。
- **載入的設定**：profile 列出 worker 要保留與排除的設定來源（Claude：gateway、plugin、hook；Codex：設定檔與它載入的擴充）；觀察到被排除的項目已載入，該項不成立。

每一項各自判定，任一項不成立，profile SHALL 為 `unverified` 並列出原因；能力不足 SHALL 具體 Blocked，SHALL NOT 自動換用未核准的工具或放寬隔離。研究報告或舊實作的紀錄 SHALL NOT 作為 preflight 的成功證據。

**Receipt**：結果 SHALL 寫成 receipt，記錄 role、profile 與已核准 `workflow.yaml` 的 digest、runtime 與 agent CLI 的版本、marker、native session ID、讀回的值、從 native 紀錄讀到的實際權限模式或 sandbox、worker 的執行模式、權限設定的來源、任務的送達方式、每個負例的結果、載入的設定來源，以及判定所依據的 native 紀錄摘錄（遮蔽後）與其 digest。Receipt、能力證據矩陣與提交到 repo 的證據 SHALL NOT 含 credentials 或 dispatch capabilities；未清理的 runtime 紀錄 SHALL NOT 自動進 Git。中斷的 preflight SHALL NOT 產生 `verified` 的 receipt。

**適用的 receipt**：每個 profile 以最新的一份 receipt 為準，較新的 `unverified` 取代較早的 `verified`。Receipt 只有在 verdict 為 `verified`、綁定目前已核准的 `workflow.yaml` digest，而且 runtime 與 agent CLI 的版本等於目前值時才適用（D76(5)、D81）。

**派工管制**：已核准的 run 中，`next` SHALL 只在政策已核准、而且 Implementer 的 profile 有適用的 receipt 時才回報可以派工。政策未核准時，回報需要人工 `policy_change`；沒有適用的 receipt 時，回報 `preflight` 動作，附 profile 與原因。重跑 preflight 不需要人工決策。`status` SHALL 顯示每個 profile 的驗證狀態、版本與原因。

#### Scenario: AC-D29 探測全部成立
- **WHEN** 政策已核准，探測 worker 在探測工作區完成：恰好一份 native 紀錄含 marker、讀回值相符、每個負例都被 runtime 拒絕且資源未變、交出完成回報、停止經 process-info 確認、沒有載入被排除的設定
- **THEN** receipt 的 verdict 為 `verified`，含上述全部欄位且不含 credentials；`status` 顯示該 profile 為 verified 與版本；已核准的 run 的 `next` 回報可以派工

#### Scenario: AC-D18 正確 workspace 與設定
- **WHEN** preflight 讀回的 model、effort、工作目錄、repo 或 branch 與要求不符；或只有 input accepted 而沒有 native turn；或含 marker 的 native 紀錄找不到或多於一份；或讀不到 effort 或工作目錄、只有 shell cwd 相符
- **THEN** profile 為 `unverified`，receipt 保存要求值、實際值、marker 與 native session ID；不宣稱 profile 可用，也不從 shell cwd、`current`、角色名稱、啟動參數、時間先後或相同目錄推定

#### Scenario: AC-D19 能力缺口與替換
- **WHEN** profile 缺少 model 等必要設定；或探測工作區、runtime 的 repo 註冊不存在；或探測 worker 沒有把任務當成任務、交不出完成回報；或停止後 process-info 仍顯示探測 agent
- **THEN** profile 為 `unverified`，preflight 的輸出與 `status` 顯示具體 Blocked 與最小能力需求，保留已取得的證據；不自動改用未核准的 runtime 或 model，不放寬權限，也不以研究報告當成成功證據

#### Scenario: AC-D22 兩種接法分別驗證
- **WHEN** 一個 profile 為 `verified`，另一個 profile 的 model、隔離或 lifecycle 尚未驗證
- **THEN** receipt 與能力證據矩陣按接法分欄保存證據類型與 verdict，不共用成功標記，不宣稱完整 E2E 已完成，也不因更換 runtime 而放寬 Reviewer 的獨立性要求

#### Scenario: AC-D23 未選用的接入故障
- **WHEN** 已選的 profile 可用，而未選用的接入（Herdr、OpenCode）不存在、未登入或連線失敗；或已選 profile 本身的工具不存在或無法使用
- **THEN** 前者不影響已選的 profile，preflight 不呼叫未選用的接入；後者該 profile 為 `unverified` 並 Blocked，不自動改用其他 runtime 或 model

#### Scenario: AC-D26 沒有適用的 R1 就不派工
- **WHEN** run 已核准，而 Implementer 的 profile 沒有適用的 receipt：從未執行、最新一份是 `unverified`，或綁定的 digest、runtime 或 agent CLI 的版本和目前不同
- **THEN** `next` 不回報派工，改回報 `preflight` 動作與 profile、原因；`status` 顯示每個 profile 的驗證狀態與原因；重跑 preflight 得到適用的 `verified` 之後，`next` 才回報可以派工

#### Scenario: AC-D28 Worker 載入的設定與憑證
- **WHEN** preflight 寫出 receipt
- **THEN** receipt 記錄 worker 實際載入的設定來源、實際權限模式、執行模式與任務的送達方式；profile 排除的設定被觀察到已載入時 profile 為 `unverified`；receipt、能力證據矩陣與提交到 repo 的證據都不含 dispatch capability 或其他 credentials

#### Scenario: AC-D30 政策未核准時不探測
- **WHEN** `workflow.yaml` 沒有綁定目前 digest 的人工 `policy_change`，有人執行 preflight；或已核准的 run 在這個狀態下查詢 `next`
- **THEN** preflight 拒絕執行，不派探測 worker，也不寫 receipt；`next` 不回報派工，改回報需要人工 `policy_change`；兩者都說明原因

#### Scenario: AC-D31 Preflight 中斷
- **WHEN** preflight 派出探測 worker 之後被中斷，之後再次執行
- **THEN** 中斷的那次沒有 `verified` 的 receipt；下一次 preflight 先找出殘留的探測 worker 並停止它（以 process-info 確認），把處理結果記進新的 receipt
