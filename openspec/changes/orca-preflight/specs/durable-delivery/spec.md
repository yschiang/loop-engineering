## MODIFIED Requirements

### Requirement: DUR-01 人可閱讀且單一的現行狀態

設定與執行狀態 SHALL 以人可閱讀的 JSON／YAML 保存，不以 SQLite 取代。同一 repo＋feature SHALL 只有一份現行狀態；歷史只是紀錄，不是另一份現行狀態。使用者 SHALL 可以從狀態檔或 `status` 直接讀到目前階段、owner、plan／spec／design 的版本、核准、三 gate 的狀態與理由、blockers 與下一個允許的動作。狀態檔中的下一個動作只依 run 狀態計算；可不可以派工另依 run 狀態之外的 preflight receipt 與目前的 transport、agent CLI 版本判定（DUR-09），`status` 與 `next` 每次都重新判定；狀態檔的下一個動作與 `next` 不同時，以 `next` 為準。狀態只能經 controller 的命令改變；手改 SHALL 可被偵測，而且永不當作決策。每筆人工 decision SHALL 保存決策者、來源、理由與影響。系統只有一套生效的狀態與 CLI 入口。

#### Scenario: AC-D01 直接檢視狀態
- **WHEN** 使用者打開 run 的狀態檔，或執行 `status`（含 `--human`）
- **THEN** 不讀歷史就能看到目前階段、owner、plan／spec／design 的版本、核准狀態、三 gate 的狀態與理由（尚未評估的 gate 標明未評估）、blockers 與依 run 狀態計算的下一步；`status` 另顯示依 receipt 與目前版本判定的結果，與 `next` 會回報的下一步一致

#### Scenario: AC-D02 手動修改不是決策
- **WHEN** 有人直接修改狀態檔（例如把 gate 改成 passed、改 phase 或刪除 decision），沒有經過 controller 的命令
- **THEN** 下一次讀取偵測到手改並回報，不把手改值當成批准或 gate 結果，也不覆寫原檔；合法的 decision 只能經 `decide` 產生，並保存決策者、來源、理由與影響

### Requirement: DUR-02 唯一派工權與安全重派

同一 repo＋feature SHALL 同時只有一個持有協調權的呼叫者；run ID、session 或 clone 不同，SHALL NOT 產生第二份協調權。協調權以 `claim` 取得的 token 表示，狀態只保存 token 的 digest；每個寫入命令 SHALL 核對 token。沒有協調權的呼叫者 SHALL 只能讀取狀態。

Worker SHALL 只能寫入授權的範圍與自己的結果位置，並由 runtime 的權限設定拒絕呼叫狀態寫入命令（例如 `loopctl decide`）。這個限制 SHALL 以真實 runtime 的負例驗證（DUR-09 的 preflight）；未驗證的 profile SHALL NOT 被默認可用。系統不承諾偵測或阻止同一 OS 帳號下繞過 runtime 權限的蓄意偽造（D48）。

#### Scenario: AC-D03 兩個 run 搶同一 feature
- **WHEN** 兩個呼叫者同時對同一 repo＋feature 執行 `claim`
- **THEN** 恰好一方取得協調權；另一方收到已被持有的結果與目前 owner，之後仍可讀取狀態，但任何寫入命令都因 token 不符被拒，狀態不變

#### Scenario: AC-D27 Worker 的權限負例
- **WHEN** preflight 讓探測 worker 逐一嘗試：寫入可寫範圍以外的位置、`git push`、`gh`、profile 允許清單以外的 `orca` 子命令（至少一個會改變 Orca 狀態的子命令）、`loopctl decide`
- **THEN** 一項只有在 native 紀錄顯示 worker 嘗試了該命令、該命令被 agent CLI 的權限設定或 sandbox 拒絕而沒有執行，**而且**資源沒有改變（檔案不存在、遠端 ref 未變、沒有新的 Orca 物件或 `gh` 寫入、狀態 revision 未變）時才成立；worker 沒有嘗試、只自述拒絕，或命令有執行而由 loopctl 自己的核對拒絕，該項都不成立。任一項不成立，profile 為 `unverified`，receipt 列出該項的命令、觀察到的結果與資源檢查

## ADDED Requirements

### Requirement: DUR-09 Adapter 與 runtime/model 解耦

核心 SHALL 依穩定的角色與能力契約執行；transport、runtime、provider、model 與 effort SHALL 分欄保存。每個部署 SHALL 在 `workflow.yaml` 的 `profiles` 從核准的接法中選用；「選配」指不是每個部署都必須有該工具（D38、D81）。Profile SHALL 經人工 `policy_change` 核准並綁定 digest。Transport 專有的識別（例如 Orca 的 Run、Task、Dispatch）SHALL NOT 成為共用契約的必填條件。未選用的接入 SHALL NOT 被呼叫，也 SHALL NOT 阻斷已選的路徑。接入工具的名稱 SHALL NOT 被當成已有可派工的能力；只有經 preflight 驗證的能力可以使用。

**Preflight**：派工之前，`loopctl preflight` SHALL 對 profile 執行受限的能力探測。Preflight 以一個 run（repo＋feature）為脈絡，依該 run 的政策核准判定：該 run 的 `workflow.yaml` 沒有綁定目前 digest 的人工 `policy_change` 時，SHALL 拒絕執行並說明原因。Preflight 不需要協調權，也不寫 feature 狀態。派出探測 worker 之前，SHALL 先持久記錄 marker 與 transport 的 handle。探測 SHALL 經所選 transport 派一個探測 worker 到探測工作區，任務帶一個唯一的 marker，並逐項判定：

- **讀回**：native 紀錄 SHALL 恰好有一份含這個 marker；model、effort 與實際工作目錄取自 marker 所在的 turn，再讀出該目錄的 repo 與 branch。model 與 effort 和 profile 比對（effort 是探測時要求的值），位置和探測工作區比對。找不到或有多於一份含 marker 的紀錄，該項不成立。SHALL NOT 以 shell cwd、`current`、角色名稱、transport 的啟動參數、時間先後或相同目錄推定。
- **權限**：做 DUR-02 的負例（AC-D27）；Reviewer 另做 GAT-05 的隔離負例與不同模型的核對。
- **任務與回報**：worker 把 transport 交付的任務當成任務，並以 transport 的回報管道交出完成（Orca 為 `worker_done`）。探測 worker 有 native turn，即視為 agent CLI 的認證可用。
- **停止**：停止 SHALL 以 process-info 確認探測 agent 的程序已不存在；transport 的 liveness、停止回應或 terminal 已關閉，SHALL NOT 單獨作為證據。
- **載入的設定**：profile 列出 worker 要保留與排除的設定來源（Claude：gateway、plugin、hook；Codex：設定檔與它載入的擴充）；觀察到被排除的項目已載入，該項不成立。

每一項各自判定，任一項不成立，profile SHALL 為 `unverified` 並列出原因；能力不足 SHALL 具體 Blocked，SHALL NOT 自動換用未核准的工具或放寬隔離。研究報告或舊實作的紀錄 SHALL NOT 作為 preflight 的成功證據。

**Receipt**：結果 SHALL 寫成 receipt，記錄 role、脈絡 run、profile 與該 run 已核准 `workflow.yaml` 的 digest、transport（Orca）與 agent CLI 的版本、marker、native session ID、讀回的值、從 native 紀錄讀到的實際權限模式或 sandbox、worker 的執行模式、權限設定的來源、任務的送達方式、每個負例的結果、載入的設定來源，以及判定所依據的 native 紀錄摘錄（遮蔽後）與其 digest。Receipt、能力證據矩陣與提交到 repo 的證據 SHALL NOT 含 credentials 或 dispatch capabilities；未清理的 runtime 紀錄 SHALL NOT 自動進 Git。中斷的 preflight SHALL NOT 產生 `verified` 的 receipt。殘留探測 worker 的清理不受政策核准狀態影響，清理結果記在 marker 與 handle 的持久紀錄與 preflight 的輸出；殘留的 worker 無法確認停止時，SHALL NOT 派新的探測 worker。Receipt 存在 run 狀態之外，帶自身內容的 digest；內容與 digest 不符的 receipt 不適用。

**適用的 receipt**：每個 profile 以最新的一份 receipt 為準，較新的 `unverified` 取代較早的 `verified`。Receipt 對一個 run 只有在 verdict 為 `verified`、綁定的 digest 等於該 run 已核准的 `workflow.yaml` digest，而且 transport 與 agent CLI 的版本等於目前值時才適用（D76(5)、D81）；目前的版本讀不到時不適用，原因為版本未知；同一份 receipt 可被任何已核准同一 digest 的 run 採用。

**派工管制**：已核准的 run 中，`next` SHALL 只在政策已核准、而且 Implementer 的 profile 有適用的 receipt 時才回報可以派工。政策未核准時，回報需要人工 `policy_change`；沒有適用的 receipt 時，回報 `preflight` 動作，附 profile 與原因。重跑 preflight 不需要人工決策。`status` SHALL 顯示每個 profile 的驗證狀態、版本與原因。

#### Scenario: AC-D29 探測全部成立
- **WHEN** 政策已核准，探測 worker 在探測工作區完成：恰好一份 native 紀錄含 marker、讀回值相符、每個負例都被 runtime 拒絕且資源未變、交出完成回報、停止經 process-info 確認、沒有載入被排除的設定
- **THEN** receipt 的 verdict 為 `verified`，含上述全部欄位且不含 credentials；`status` 顯示該 profile 為 verified 與版本；若該 profile 是 Implementer，已核准同一 digest 的 run 的 `next` 回報可以派工

#### Scenario: AC-D18 正確 workspace 與設定
- **WHEN** preflight 讀回的 model、effort、工作目錄、repo 或 branch 與要求不符；或只有 input accepted 而沒有 native turn；或含 marker 的 native 紀錄找不到或多於一份；或讀不到 effort 或工作目錄、只有 shell cwd 相符
- **THEN** profile 為 `unverified`，receipt 保存要求值、實際值、marker 與 native session ID；不宣稱 profile 可用，也不從 shell cwd、`current`、角色名稱、啟動參數、時間先後或相同目錄推定

#### Scenario: AC-D19 能力缺口與替換
- **WHEN** profile 缺少 model 等必要設定；或探測工作區、transport 上的 repo 註冊不存在；或探測 worker 沒有把任務當成任務、交不出完成回報；或停止後 process-info 仍顯示探測 agent
- **THEN** profile 為 `unverified`，preflight 的輸出與 `status` 顯示具體 Blocked 與最小能力需求，保留已取得的證據；不自動改用未核准的 runtime 或 model，不放寬權限，也不以研究報告當成成功證據

#### Scenario: AC-D22 兩種接法分別驗證
- **WHEN** 一個 profile 為 `verified`，另一個 profile 的 model、隔離或 lifecycle 尚未驗證
- **THEN** receipt 與能力證據矩陣按接法分欄保存證據類型與 verdict，不共用成功標記，不宣稱完整 E2E 已完成，也不因更換 runtime 而放寬 Reviewer 的獨立性要求

#### Scenario: AC-D23 未選用的接入故障
- **WHEN** 已選的 profile 可用，而未選用的接入（Herdr、OpenCode）不存在、未登入或連線失敗；或已選 profile 本身的工具不存在或無法使用
- **THEN** 前者不影響已選的 profile，preflight 不呼叫未選用的接入；後者該 profile 為 `unverified` 並 Blocked，不自動改用其他 runtime 或 model

#### Scenario: AC-D26 沒有適用的 R1 就不派工
- **WHEN** run 已核准，而 Implementer 的 profile 沒有適用的 receipt：從未執行、最新一份是 `unverified`，或綁定的 digest 不等於該 run 已核准的 digest，或 transport 或 agent CLI 的版本和目前不同或讀不到
- **THEN** `next` 不回報派工，改回報 `preflight` 動作與 profile、原因；`status` 顯示每個 profile 的驗證狀態與原因；重跑 preflight 得到適用的 `verified` 之後，`next` 才回報可以派工

#### Scenario: AC-D28 Worker 載入的設定與憑證
- **WHEN** preflight 寫出 receipt
- **THEN** receipt 記錄 worker 實際載入的設定來源、實際權限模式、執行模式與任務的送達方式；profile 排除的設定被觀察到已載入時 profile 為 `unverified`；receipt、能力證據矩陣與提交到 repo 的證據都不含 dispatch capability 或其他 credentials

#### Scenario: AC-D30 政策未核准時不探測
- **WHEN** 某個 run 的 `workflow.yaml` 沒有綁定目前 digest 的人工 `policy_change`，有人以這個 run 為脈絡執行 preflight；或這個 run 已核准 plan、在這個狀態下查詢 `next`
- **THEN** preflight 拒絕執行，不派新的探測 worker，也不寫 receipt（殘留探測 worker 照 AC-D31 清理，結果記在持久紀錄與輸出）；`next` 不回報派工，改回報需要人工 `policy_change`；兩者都說明原因

#### Scenario: AC-D31 Preflight 中斷
- **WHEN** preflight 派出探測 worker 之後被中斷，之後再次執行
- **THEN** 中斷的那次沒有 `verified` 的 receipt；下一次 preflight 依先前持久記錄的 marker 與 handle 找出殘留的探測 worker 並停止它（以 process-info 確認），清理結果記在持久紀錄與 preflight 的輸出，若這次有執行探測，也記進新的 receipt；政策是否核准不影響這個清理。殘留的 worker 無法確認停止時，不派新的探測 worker；政策已核准時，這次的 receipt 為 `unverified`，原因列出殘留的 marker 與 handle
