# Orca Delivery

從 project 基礎與 feature 準備，經 feature 交付到 PR Pass，再到人工驗收與 Retro / Replanning 的交付協作領域。

## Language

**Delivery Harness**:
支援 Project 與 Feature 交付的整體協作系統，結合工作流程、技能方法、執行控制、工具接入及可恢復的狀態／證據；個別工作指引或 controller 是其組成部分。

**Project Lead Agent**:
負責專案分析與協調的 agent 角色，與使用者透過 research、SA、domain modeling、grill 與 high-level design 形成專案基準、roadmap／milestones，拆分 features 並準備 feature spec／AC。依明確授權協調優先順序與委派，與 Implementer 交接需求、設計邊界、依賴及成果，並協助裁決與驗收。
_Avoid_: Tech Lead、TL（指本角色時）

**Implementer Agent**:
負責功能交付的 agent 角色，承接使用者或獲授權 Project Lead 的 feature spec 與高層設計，繼續實作研究，負責 detailed design、最終可執行的 plan／tasks、TDD 實作、整合及修正。在已確認邊界內作實作決策，交回可核查成果及超出授權範圍的待決事項。
_Avoid_: Engineer 1

**Reviewer Agent**:
依適用規格與工程規範審查整合變更並覆核 findings 的獨立 agent 角色；不直接修改被審查分支。Project Lead 的協調授權或 runtime 的父子關係不取代其獨立判斷。
_Avoid_: Engineer 2

**Project Lead**:
帶專案的人：給目標與限制、回答需求問題，確認可進入 Design、專案基準與 roadmap，選 feature 並驗收結果。與 Project Lead Agent 協作，決策權在人。這是角色，不是職位，常由同一人兼任 Engineer（D59）。舊稱 Lead。
_Avoid_: 用 Project Lead 指 Project Lead Agent；只寫 Lead

**Engineer**:
承接 feature 交接包的人：帶 Implementer Agent 完成詳細設計與 plan，完成或轉交開工確認，並把 feature 推進到 PR Pass。這是角色，不是職位，可與 Project Lead 由同一人擔任。舊稱 Feature Builder、工程師。
_Avoid_: Implementer（指人時）；用 Engineer 指任何 agent

**Orchestrate**:
把一個 feature 從交接包跑到 PR Pass 或 Blocked 的 skill；由人或獲授權的 Project Lead 呼叫，使用 controller 核對狀態與 gates，不呼叫 Project Lead。
_Avoid_: 與 ADE 層的多 agent 溝通機制（例如 Herdr、Orca）混稱 Orchestrator

**交接包**:
Project Lead 交給 feature loop 的最小輸入：change ID 與檔案版本、SA 確認（同一人兼任時註明併入開工確認）、專案基準引用、依賴與 base branch、未決問題與決策者、開工與驗收的決策者。不含開工確認；design＋plan 在 feature loop 中產出後才由人確認。

**Model**:
Agent 執行推理所使用的模型；與負責工具、session 及執行生命週期的 runtime 分開。

**Agent runtime**:
承載 agent session、模型呼叫、工具權限與執行生命週期的執行環境。Runtime 名稱不代表實際使用的 model，也不自動保證 Reviewer 獨立性。

**Controller**:
依核准 plan 與 workflow 規則執行派工、版本及 gates 核查、持久化與結果發布的協調機制。它不是 agents 的主管，需求及品質的語意判斷由相應 agent 或使用者負責。

**SA（系統分析）**:
在 project 或 feature 範圍內，以研究與互動釐清問題、責任、情境、業務規則、限制及驗收的活動；其需求成果保存為 Spec，不另代表一份固定檔案。

**需求輸入**:
人或上游提供、尚未承諾要做的需求材料，例如對話、上游 spec 或外部需求。SA 記錄來源版本，feature SA 從中挑出本次要做的需求寫進 change（D58）。
_Avoid_: 把輸入稱為 spec

**Project spec**:
系統目前已實作並被接受的行為，位於 `openspec/specs/`，只由 feature 驗收並 merge 後的「併入規格」（`openspec archive`）寫入；新專案開始時為空。尚未實作的需求在需求輸入或 change 裡（D58）。
_Avoid_: 把目標需求或上游 spec 放進 project spec

**Feature spec**:
經 feature 研究與系統分析形成、引用 project baseline 的需求集合，定義單次交付的目的、可觀察行為、範圍、驗收條件、依賴與必要限制。依 D54 位於 OpenSpec change 的 proposal 與 spec delta；ticket 只保存摘要與引用，並連結適用的高層設計。

**Roadmap**:
專案的交付路徑，描述 milestones 的成果、優先順序與依賴，並逐步拆成可交付的 features。

**Milestone**:
Roadmap 上有時間條件（目標日期）的可驗證成果節點，由幾個 features 共同達成；不是單一 implementation task（D65）。

**Feature high-level design**:
Feature 的主要元件責任、對外契約、跨系統資料流與重要技術取捨，界定詳細設計必須遵守的邊界。

**Feature detailed design**:
在 feature spec 與高層設計邊界內，決定模組介面、資料結構、失敗恢復與測試策略的設計，作為拆 implementation tasks 的依據。

**Feature ticket**:
追蹤一個 feature（一個 change，每個受影響的 repo 一個 PR）的 issue：只寫目標、milestone、change 連結與驗收 ID、Blocked by 與狀態，不重寫需求（D57）。不改需求的小工作不開 change，ticket 本身就是規格。
_Avoid_: Task ticket（用於指稱 feature 時）

**Implementation task**:
Feature plan 中具有穩定 ID、scope、依賴、AC 對應與驗證條件的派工單位，一個 session 做得完，不開 ticket（D57）；由 Implementer 校準並維護最終計畫；Project Lead 也可提供初步拆分。多個 tasks 可共同交付一個 feature PR。

**Delivery run**:
針對一個已選定 feature ticket，從規劃、實作到 PR Pass 或需要人工裁決的持續交付紀錄。

**Attempt**:
同一 implementation、review 或診斷 task 的一次執行；重試產生新的 attempt，保留先前紀錄。

**Orca Dispatch**:
Orca 指派給 worker 的一次具有效執行權的 task attempt，與 delivery attempt 以識別碼對應。

**Gate evidence**:
可讀取、可追溯且適用於指定交付版本的驗證紀錄，是 gate 判定依據。

**Blocking finding**:
尚未經 reviewer 覆核解除或人工明確裁決、會阻止 review clean 的問題。

**Correction round**:
同一適用版本的 review / CI 結果整理成修正批次後，經修正、驗證與重新審查的一輪。

**Execution Retro**:
從 feature 執行、審查與驗收的證據中辨識重複失誤及流程摩擦，形成可驗證改善項目的回顧活動；與修復當前 finding 的 correction round 分開。

**Replanning**:
根據交付與驗收的新知，重新決定共用需求、架構或 roadmap 的專案活動；由 Project Lead Agent 協助使用者作跨 feature 取捨。

**PR Pass**:
目前交付版本同時滿足實作/TDD、獨立 review 與必要 CI 三個 gates 的品質結論。
_Avoid_: Agent done、CI green（用於指稱全部通過時）

**Blocked**:
交付需要人工決策或外部條件變更才能正確續行的狀態，包含具體原因、證據與待決事項。
