## MODIFIED Requirements

### Requirement: ORC-01 共同入口、角色責任與授權

Controller SHALL 是 feature 狀態與人工決策紀錄的唯一寫入入口；每次被呼叫時完成核對或狀態更新後即返回，SHALL NOT 常駐，也 SHALL NOT 執行呼叫者或 worker 提供的命令。Controller SHALL NOT 啟動 agents，只有一個例外：`preflight` 可以依已核准的政策檔，以 controller 自己固定的命令經所選 transport 派出探測 worker、讀回它的狀態與 native 紀錄，並停止它（DUR-09）。`preflight`、`status` 與 `next` 可以以固定的命令讀取 transport 與 agent CLI 的版本。可執行的動作 SHALL 只依協調權（claim token）與人工 decision 判定，SHALL NOT 由共同入口、session 名稱或 runtime 父子關係推定決策權。使用者 SHALL 可直接把 feature 交給 Implementer，不必經 Project Lead 轉達。未支援的入口（`adopt`、`delegate`）SHALL 明確回 `unsupported`，狀態不變。

#### Scenario: AC-O01 直接與 Implementer 協作
- **WHEN** 使用者直接把已選定的 feature 交給 Implementer，Implementer 以 `init` 建立 run
- **THEN** run 進入 design／plan 準備階段，保存協調者 identity；不需要 Project Lead 的交接紀錄，也不因此產生開工確認或 scope 變更的權限

#### Scenario: AC-O19 入口與 runtime 關係不授予決策權
- **WHEN** agent 使用與人相同的入口呼叫 `decide`，或自稱由 Project Lead 或使用者的 session 派出
- **THEN** 只有 actor 為 `human:<name>` 的 decision 被接受；其他 actor 一律拒絕且狀態不變，不從入口或父子關係新增委派權或 scope 變更權

#### Scenario: AC-O30 未支援的入口
- **WHEN** 呼叫 `adopt` 或 `delegate`
- **THEN** 回 `unsupported`，狀態的 revision 不變，也不略過任何開工確認或協調權的核對
