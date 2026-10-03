## ADDED Requirements

### Requirement: GAT-05 獨立整合 review

Reviewer profile 的實際 model SHALL 從 runtime 的原生紀錄讀回。Reviewer 的隔離 SHALL 由所選 runtime 既有的權限能力提供，並以真實負例驗證；本系統不自建 OS sandbox。Reviewer SHALL 使用獨立的 clone 與 session，SHALL NOT 有修改作者 branch 的途徑。Reviewer 與 Implementer SHALL 是不同的實際模型（D52）；只換 effort、別名或 session 不算。無法驗證時，Reviewer profile 為 `unverified`。

#### Scenario: AC-G23 兩個角色是同一個 model
- **WHEN** `workflow.yaml` 中 `reviewer` 與 `implementer` 的 model 相同，即使 effort 不同
- **THEN** Reviewer profile 的 preflight 為 `unverified`，原因列出兩者的 model 相同

#### Scenario: AC-G24 Reviewer 的隔離無法證明
- **WHEN** Reviewer 的探測 worker 能修改作者的 branch（包括移動 ref）或作者 worktree 的檔案，或隔離沒有可核對的證據
- **THEN** Reviewer profile 為 `unverified`，顯示能力缺口；不默默放寬權限，也不因只禁用編輯工具就宣稱所有工具安全

### Requirement: GAT-08 驗收證據區分模擬與真實交付

驗收報告 SHALL 明確區分可控制測試、真實 adapter 能力與完整交付 E2E。能力證據矩陣 SHALL 依接法分欄，每項能力標 `fake`、`profile-probe`、`real-E2E` 或 `none`；沒有執行的格子標 `none`。測試 SHALL 驗可觀察的行為，不以 enum 或實作步驟的重述代替。舊 S1 實作的測試、CI、review、bootstrap 與 preflight 紀錄 SHALL NOT 作為新實作的證據（D46、D75）。

#### Scenario: AC-G19 模擬通過但 adapter 缺證據
- **WHEN** 可控制測試通過，但所選 Orca＋runtime profile 的原生讀回、Reviewer 的權限能力或工作目錄的位置還沒有以真實 preflight 驗證
- **THEN** 矩陣保留個別能力缺口並標 `none`，不宣稱完整 E2E 通過，也不以權限較寬的 workaround 補成成功
