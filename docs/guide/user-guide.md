# Loop Engineering 使用指南

> 草案：流程已定，自動化還在做，現在可以照著人工演練。見[目前進度](../README.md)。

**先決定要什麼，再切成能單獨驗收的 Feature 交付，沒有依賴的可以同時進行；每交付一個，就回頭調整計畫。**

> 手冊有兩份：這份講流程，照著做就好；每一步的細節（需求怎麼問、spec 怎麼寫、交接要看什麼、gates 要哪些證據、常見問題）在 **[參考手冊](reference.md)**，順序跟流程相同。每張卡片最後的「**細節**」連到對應的小節。

就是熟悉的 SDLC，只是大部分工作由 Agent 做，人負責做決定。**Feature** 是能單獨驗收的一次交付；**Milestone** 是幾個 Feature 合起來、可以展示的成果。縮寫：SA 是需求分析，AC 是驗收條件，ADR 是架構決策紀錄，ADE 是讓 Agent 工作的開發環境，TDD 是先寫會失敗的測試、再實作到通過。

## 大圈包小圈

```mermaid
flowchart LR
  subgraph Project["外圈 Project：決定要做什麼"]
    direction LR
    A1["Analyze<br/>釐清目的與需求"] --> A2["Architect<br/>設計方案"] --> A3["Roadmap<br/>安排交付"] --> A4["Specify<br/>開 Feature"]
    A4 -->|交接| F((("Feature ↻<br/>Implement → Validate")))
    F -->|接受| A5["Retro<br/>併入規格與回顧"]
    A5 -->|Replan| A3
  end
  style Project fill:#eff6ff,stroke:#2563eb,color:#172554
  style F fill:#fff7ed,stroke:#c2410c,color:#431407
```

外圈 Project 決定要做什麼：**Analyze**（釐清目的與需求）→ **Architect**（設計方案）→ **Roadmap**（安排交付，選接下來要做的 Feature）→ **Specify**（開 Feature：寫成可驗收的 spec，交接出去）。每個 Feature 各走自己的內圈，沒有依賴的可以同時進行；內圈把它做出來並證明是對的：**Implement**（寫實作 plan、交給 agent 執行）→ **Validate**（Review 與 CI、驗收）。接受後進 **Retro**（併入規格與回顧），把經驗帶回 Roadmap，再選下一個。Agent 做大部分工作，人在關鍵點確認。

## 誰做什麼

Agent 做大部分工作；人在六個 ◆ 確認點做決定：

| 誰 | 做什麼（◆ 是他要確認的點） |
| --- | --- |
| Project Lead | • [釐清目的與需求](#a1-analyze釐清目的與需求)（先研究 codebase）◆確認目的與需求<br>• [設計方案](#a2-architect設計方案) ◆確認設計方案<br>• [安排交付](#a3-roadmap安排交付)：排 roadmap、選接下來要做的 Feature ◆確認 roadmap<br>• [開 Feature](#a4-specify開-feature)：寫 Feature spec、交接 ◆確認 spec<br>• [併入規格與回顧](#a5-retro併入規格與回顧) |
| Engineer | • [寫實作 plan](#b1-design寫實作-plan) ◆確認開工<br>• [交給 agent 執行](#b2-build交給-agent-執行)<br>• [Review 與 CI](#b3-verifyreview-與-ci)<br>• 中小型 Feature 也常自己[開 Feature](#a4-specify開-feature) |
| 驗收人：預設是 Project Lead；需求由別人提出時，是提出的人 | • [驗收](#b4-accept驗收)：看每條 AC 的證據與 demo ◆驗收：接受或退回 |
| Agent：Project Lead Agent、Implementer、Reviewer | • 研究、寫文件、實作、審查<br>• 不做確認 |

- **角色是工作，不是職位**：中小型 Feature 的外圈很薄，同一人兼任 Project Lead 與 Engineer 是常態，這時 ◆確認 spec 併入 ◆確認開工。交接時寫明誰確認開工、誰驗收；確認開工的人通常是 Engineer。
- **Project Lead 和 Project Lead Agent 不同**：Project Lead 做決定，Agent 做分析與建議。驗收人也不是審查程式的 Reviewer Agent。

## 人、Agent 與工具的分層

```text
┌─ Human ──────────────────────────────────┐
│ Project Lead / Engineer                  │  做決定：目的與需求、設計方案、roadmap、spec、開工、驗收
└────────────────────┬─────────────────────┘
                     │ 用自然語言交代、確認
┌─ ADE ──────────────▼─────────────────────┐
│ Herdr / OpenCode / Claude Code           │  開 session 與 worktree，讓多個 Agent 並排工作
│ Orca (optional)                          │
└────────────────────┬─────────────────────┘
                     │
┌─ Harnessing ───────▼─────────────────────┐
│ Skills: project-lead / feature-to-spec / │  約束 Agent 怎麼做：
│         spec-to-plan / plan-to-code /    │  照哪個方法、用哪個模型、先寫什麼
│         to-pr / research-codebase        │
│ Model: chosen per role                   │  例如 Reviewer 和 Implementer 用不同模型
│ TDD, spec-driven (OpenSpec)              │  先寫測試再實作；先寫 spec 再設計
└────────────────────┬─────────────────────┘
                     │
┌─ Agents ───────────▼─────────────────────┐
│ Project Lead Agent <-> Implementer       │  做實際的分析、實作與審查
│ <-> Reviewer                             │
└────────────────────┬─────────────────────┘
                     │ 讀寫
┌─ Records & checks ─▼─────────────────────┐
│ Git branch / worktree, OpenSpec files,   │  共用的狀態：人和 Agent 靠它交接，不靠聊天
│ GitHub Issue / PR / CI                   │
│ controller                               │  核對版本、證據與三個 gates（第一片實作中）
└──────────────────────────────────────────┘
```

**Workflow** 是 Project、Feature 兩層的步驟與規則，貫穿所有層；**Harnessing** 是套在 Agent 身上的做法：skills、模型選擇、TDD、spec-driven，讓 Agent 照規則做。其中 OpenSpec 管文件放哪、長什麼樣，Superpowers 管做事的紀律，每種文件只有 OpenSpec 那一份，見參考手冊的 [OpenSpec 和 Superpowers 怎麼分工](reference.md#openspec-和-superpowers-怎麼分工)。

## 活動卡怎麼讀

每個活動一張卡：一句**目的**，一張表，表下再逐步寫**怎麼做**，**完成**寫成勾選清單。表照做事的順序排：

- **Step**：第幾步。
- **Who**：誰做，每一列一個角色：Project Lead、Engineer、驗收人或 Agent。**同一個 Step 編號出現好幾列，代表同一件事由人和 Agent 來回做**，每列寫各自做的部分和用的東西；◆ 是要人確認的點，只由人做，見[誰做什麼](#誰做什麼)。
- **Do**：做什麼。
- **How**：用什麼。skill 會連到 repo 裡它的 `SKILL.md`；指令連到說明文件。**每個活動只貼一次 prompt**，寫在人啟動的那一列：貼上後，同一個 Agent session 由那個 skill 接著做完表上 Agent 的各列，那些列的 How 寫「同一個 session」或這一步另外用到的指令與工具；人只在自己那幾列回答或確認。prompt 開頭的 `/skill 名稱` 會直接叫用那個 skill，只寫「請用某某 skill」不保證會叫用：Claude Code 照寫 `/project-lead`；Codex 改成 `$project-lead`；OpenCode 沒有直接叫用的寫法，改成「請用 project-lead skill」，再看 Agent 有沒有說已載入。第一次使用前，在 loop-engineering 執行 `./setup.sh` 安裝這些 skills；產品的 root repo 若已用 `./setup.sh --project` 帶著 skills，從 root 開 session 就能直接用。
- **Output**：產出什麼。示範專案已經有的，附上範例連結；示範還沒走到的步驟先不放，示範專案推上 GitHub 之前，部分連結會打不開。

Agent 寫 ticket 或 PR 留言之前，會先問人，或照人事先給的授權。controller 可用之前，交付紀錄都放在 ticket 留言；只有確認目的與需求、設計方案、roadmap 記在決策紀錄，確認 spec 記在 proposal。

## 外圈：Project

大圈放大後：**Analyze** 是 A1，**Architect** 是 A2，**Roadmap** 是 A3，**Specify** 是 A4；每個 Feature 接受後的 **Retro** 是 A5，做完回到 A3。

```mermaid
flowchart LR
  A1["A1 Analyze<br/>釐清目的與需求"] -->|◆確認目的與需求| A2["A2 Architect<br/>設計方案"]
  A2 -->|◆確認設計方案| A3["A3 Roadmap<br/>安排交付"]
  A3 -->|◆確認 roadmap<br/>選接下來的 Feature| A4["A4 Specify<br/>開 Feature"]
  A4 -->|◆確認 spec<br/>兼任時併入 ◆確認開工<br/>交接包| IN[["內圈：Implement → Validate"]]
  IN -->|◆驗收：接受| A5["A5 Retro<br/>併入規格與回顧"]
  A5 -->|Replan| A3
  style IN fill:#fff7ed,stroke:#c2410c,color:#431407
```

### A1 Analyze：釐清目的與需求

**目的**：確定為什麼做、做到哪裡算完成。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Project Lead | 說明要解決的問題和限制 | skill [project-lead](../../skills/project-lead/SKILL.md)：開一個 Agent session，貼上：`/project-lead 做 project 的 SA。Repo 在〈路徑〉，既有資料在〈位置〉。我想解決的問題是〈一兩句〉。` | — |
| 2 | Project Lead | 給要查的問題；讀報告，有疑問就追問 | — | — |
| 2 | Agent | Research：分清現況的<br>• Facts<br>• Assumptions<br>• Unknown | • skill [research-codebase](../../skills/research-codebase/SKILL.md)<br>• codebase 大或第一次接手：先用 skill graphify（[說明](https://github.com/Graphify-Labs/graphify)） 建知識圖，`/graphify <路徑>` | • 研究報告：`docs/research/<日期>-<主題>.md`（[範例](../research/2026-09-25/integration-gaps.md)）<br>• 用了 graphify：`graphify-out/GRAPH_REPORT.md` |
| 3 | Project Lead | （選用）把參考資料（客戶規格、上游 spec、會議紀錄）放進資料夾；確認分組 | — | — |
| 3 | Agent | 解析參考資料：依能力分組、註明來源版本 | 同一個 session | 需求輸入：`docs/research/<日期>-import/`（[範例](https://github.com/yschiang/cross-node-root/blob/main/docs/research/2026-09-28-import/README.md)） |
| 4 | Agent | 由上往下問，每輪 1–3 題：<br>• 目標<br>• 範圍<br>• 情境<br>• 規則<br>• 例外<br>• 驗收 | 同一個 session | • project intent（[範例](https://github.com/yschiang/cross-node-root/blob/main/docs/project-intent.md)）<br>• 共同詞彙 `CONTEXT.md`（[範例](https://github.com/yschiang/cross-node-root/blob/main/CONTEXT.md)） |
| 4 | Project Lead | 回答、修正；想被追問得更深，自己輸入 `/grill-with-docs`（[說明](../../skills/third-party/mattpocock/engineering/grill-with-docs/SKILL.md)；只能由人啟動） | — | — |
| 5 | Project Lead | 看一頁摘要，◆確認目的與需求：可以進入設計方案 | — | 決策紀錄（[範例](https://github.com/yschiang/cross-node-root/blob/main/docs/decisions.md)） |

**每一步怎麼做、怎樣算完成**

1. **說明問題和限制**
   - 怎麼做：填上 repo、既有資料的位置，用一兩句說要解決的問題；講不清楚也可以，Agent 會問。
   - 完成：
     - [ ] Agent 回報已載入 project-lead skill
     - [ ] Agent 用自己的話複述了問題、範圍與已知限制，Project Lead 認可
2. **Research**
   - 怎麼做：
     - Project Lead 給要查的問題
     - Agent 查 codebase 與既有資料；用了 graphify 時，先讀 `GRAPH_REPORT.md` 找核心模組，再用 `/graphify query "<問題>"` 查關係
     - Project Lead 讀報告，有疑問就追問
   - 完成：
     - [ ] 報告存進 `docs/research/`
     - [ ] Facts、Assumptions、Unknown 分開列
     - [ ] 每條 Fact 都附路徑、行號或出處
3. **解析參考資料（選用）**
   - 怎麼做：
     - Project Lead 把參考資料放進 `docs/research/<日期>-import/`
     - Agent 先列「來源段落 → 能力」對照表
     - Project Lead 同意後，Agent 照表整理；沒有參考資料就跳過
   - 完成：
     - [ ] 每段來源都對到一個能力
     - [ ] 記下來源版本
     - [ ] 沒有放進 `openspec/specs/`
4. **由上往下問**
   - 怎麼做：
     - Agent 先把骨架七項寫成草稿，每項標「假設」
     - 從目標問起，上一層確認了才問下一層
     - 每題附選項、影響與建議；答案當場寫進文件
   - 完成：下面都寫好，沒有一項還標「假設」
     - [ ] `docs/project-intent.md` 寫齊骨架七項，其中 3–6 項寫摘要、連到需求輸入：
       - [ ] 問題與目標
       - [ ] 範圍與不做
       - [ ] 角色與主要情境
       - [ ] 能力清單與主要規則
       - [ ] 共用限制：每個 Feature 都要守的
       - [ ] 驗收方向
       - [ ] 待決：每條寫明影響與誰決定，沒有一條擋住設計
     - [ ] `CONTEXT.md` 收錄用到的領域詞彙，每個一句定義
     - [ ] 需求原文在需求輸入，記下來源版本；有參考資料時，每一段都對到一個能力
5. **◆確認目的與需求**
   - 怎麼做：看一頁摘要（目標、不做、能力、限制、待決、版本），不必讀檔案；有疑問就回到第 4 步。
   - 完成：
     - [ ] 決策紀錄寫下誰、何時、原話和確認的版本

**細節**：參考手冊的[需求是怎麼問出來的](reference.md#需求是怎麼問出來的)、[外圈產出哪些文件](reference.md#外圈產出哪些文件)。

### A2 Architect：設計方案

**目的**：定下元件責任與技術，roadmap 才切得出能單獨驗收的 Feature。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Agent | 提出設計：<br>• 有既有設計：沿用，標出要改的地方<br>• 沒有：提出 2–3 個方案與比較 | 同一個 session | 高層設計：`docs/design/`（[範例資料夾](https://github.com/yschiang/cross-node-root/tree/main/docs/design)），先看：<br>• [網頁版](https://yschiang.github.io/cross-node-root/)<br>• [system-design.md](https://github.com/yschiang/cross-node-root/blob/main/docs/design/system-design.md)<br>• [design-decisions.md](https://github.com/yschiang/cross-node-root/blob/main/docs/design/design-decisions.md) |
| 1 | Project Lead | 補充限制與偏好 | — | — |
| 2 | Project Lead | 在方案之間做選擇 | — | — |
| 2 | Agent | 把選擇與取捨寫成 ADR | 同一個 session | ADR：`docs/adr/`（[範例](https://github.com/yschiang/cross-node-root/blob/main/docs/adr/0002-target-pull-over-http.md)） |
| 3 | Project Lead | 看設計摘要，◆確認設計方案 | — | 決策紀錄 |

**每一步怎麼做、怎樣算完成**

1. **提出設計**
   - 怎麼做：Agent 提出，Project Lead 補充限制與偏好。有既有設計時，把它複製進 `docs/design/` 與 `docs/adr/`，記下來源與版本，只標出要改的地方；沒有時，比較每個方案的優缺點並給建議。
   - 完成：`docs/design/` 的高層設計寫齊
     - [ ] 元件與責任：每個能力寫明由哪些元件負責、邊界在哪
     - [ ] 主要資料流
     - [ ] 對外介面
     - [ ] 技術選擇；還沒決定的，列成要選的方案
2. **選方案**
   - 怎麼做：
     - Project Lead 照比較選一個，或要 Agent 補比較
     - Agent 把每個選擇寫成一份 ADR：背景、選項、決定、後果
   - 完成：
     - [ ] 每個選擇都有一份 ADR，寫明誰選的
     - [ ] 高層設計連得到每份 ADR
3. **◆確認設計方案**
   - 怎麼做：看設計摘要：元件責任、技術、重要取捨。
   - 完成：
     - [ ] 決策紀錄寫下誰、何時、原話和確認的版本

**細節**：參考手冊的[外圈產出哪些文件](reference.md#外圈產出哪些文件)、[多個 repo 的專案](reference.md#多個-repo-的專案)。

### A3 Roadmap：安排交付

**目的**：決定先做什麼、什麼時候交：切成能單獨交付、單獨驗收的 Feature，沒有依賴的可以同時進行。

切法是一個循環：切 Feature → 分組成 Milestone、加上時間 → 時間放不下就回頭重切。每個 Feature 收尾後（A5）也回到這裡再切一次。

- **Feature**：一個自成一體的 use case，或一個被多個 use case 共用的元件；能用自己的 AC 驗收。
- **Milestone**：幾個 Feature 加上時間條件（目標日期），合起來是一個可以展示的成果。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Agent | 提出切法：<br>• 一個 use case，或一個共用元件，切成一個 Feature<br>• 切法有依據：把能力清單整批切<br>• 沒有依據：先列交付能力，但至少切出下一個能單獨驗收的 Feature | 同一個 session | roadmap 的 Feature 表 |
| 1 | Project Lead | 調整切法 | — | — |
| 2 | Agent | 把 Feature 分組成 Milestone，提出目標日期 | 同一個 session | roadmap（[範例](https://github.com/yschiang/cross-node-root/blob/main/docs/roadmap.md)） |
| 2 | Project Lead | 定日期；放不下就回第 1 步拆小或延後 | — | — |
| 3 | Agent | 依依賴與風險提出順序 | 同一個 session | — |
| 3 | Project Lead | 決定範圍與先後，標出接下來要做的 Feature | — | 決策紀錄 |
| 4 | Project Lead | ◆確認 roadmap：<br>• 選定接下來要做的 Feature；沒有依賴的可以同時選幾個<br>• 指定誰做 Feature spec、誰是 Engineer | — | 決策紀錄 |

**每一步怎麼做、怎樣算完成**

1. **切 Feature**
   - 怎麼做：
     - Agent 提出切法，Project Lead 調整
     - 從能力清單與情境找出自成一體的 use case，每個切成一個 Feature，垂直切：一個看得到的行為，從操作一路走到資料與驗收測試；不要照技術層（資料庫、後端、API、前端）切
     - 多個 use case 都要用到的元件，切成自己的 Feature，排在用到它的 Feature 前面
     - 切法有依據（已經有實作、設計穩定）就整批切；沒有依據就先列交付能力，但至少切出下一個
   - 完成：Feature 表每一列都有
     - [ ] 名稱與一句範圍：哪個 use case，或哪個共用元件；名稱寫出做完後能做什麼，例如「loopctl：登記 run、記錄人工決策、查詢狀態與下一步」，不寫「人工決策與下一步」這種主題詞
     - [ ] 依賴
     - [ ] 對應的需求
     - [ ] 「近期」或「暫定」
     - [ ] 能用自己的 AC 驗收
2. **排 Milestone**
   - 怎麼做：
     - 把 Feature 分組，每組加上目標日期
     - 時間放不下，就回第 1 步把 Feature 拆小，或延到下一個 Milestone
   - 完成：`docs/roadmap.md` 每個 Milestone 都有
     - [ ] 目標日期
     - [ ] 可以展示的成果
     - [ ] 完成條件
     - [ ] 已切出的 Feature；還沒切的部分列交付能力
3. **排順序**
   - 怎麼做：Agent 依依賴與風險提出順序，Project Lead 決定範圍與先後。
   - 完成：
     - [ ] 接下來要做的 Feature 已標出
     - [ ] 順序與範圍的決定記進決策紀錄
4. **◆確認 roadmap、選接下來的 Feature**
   - 怎麼做：從「近期」選；彼此沒有依賴的可以同時選幾個，各走自己的內圈、各開自己的 worktree。每個選中的 Feature，決定 spec 由 Project Lead 或 Engineer 做。
   - 完成：
     - [ ] 決策紀錄寫下確認、選中的 Feature 與負責的人

每個 Feature 收尾後都回到這裡：只看變動的部分，重切必要的 Feature、調整 Milestone 的日期，再 ◆確認 roadmap、選接下來的 Feature。

**細節**：參考手冊的[Roadmap 要切多細](reference.md#roadmap-要切多細)、[工作層級](reference.md#工作層級milestonefeaturetask)。

### A4 Specify：開 Feature

**目的**：把選中的 Feature 寫成可以驗收的 spec，交給 Engineer 不必回頭問就能開始設計。

- **誰做**：Project Lead 或 Engineer 帶著 Agent 做；中小型 Feature 常由 Engineer 自己寫。用的 skill 是 `feature-to-spec`（不是 Matt Pocock 的 `/to-spec`）。
- **誰確認**：◆確認 spec 仍由 Project Lead 做；兩個角色是同一人時，併入 B1 的 ◆確認開工。
- **branch**：每個 Feature 在 root 開一條 `feature/<id>` 與自己的 worktree，spec 從第 1 步就寫在這條 branch 上；之後的 design、tasks、程式也在同一條，B3 開 PR，merge 後才進 main。
- **ticket**：開在 root repo 的 Issues（服務 repo 只開 PR），是薄的追蹤票，第 1 步就開。只放 Milestone、狀態、下一步、目標、Spec 連結、驗收 ID、Blocked by；範圍、不做與 AC 條文只在 spec。交接、開工、驗收紀錄都用留言貼在同一張 ticket。狀態依序是準備中 → 就緒（可設計）→ 開發中 → 待驗收 → 已接受 → 已完成，卡住時標 Blocked 並寫原因；每一步寫紀錄的人順手更新狀態和「下一步」。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Project Lead 或 Engineer | 交代要準備的 Feature；授權 Agent push branch、開 ticket | skill [feature-to-spec](../../skills/feature-to-spec/SKILL.md)：開一個 Agent session，貼上：`/feature-to-spec 準備〈Feature〉：補足 spec、AC、必要高層設計與依賴，引用 project intent、高層設計與 roadmap 的版本。` | — |
| 1 | Agent | 開 Feature：<br>• 專案第一次用時，先在更新過的 main 執行 `openspec init --tools claude,codex`，commit、push<br>• 在 root 從 `origin/main` 開 branch `feature/<id>` 與 worktree<br>• 在上面建立 change，commit、push<br>• 在 root repo 開 ticket，或把既有的 ticket 改成下方的格式 | • 指令 `git fetch origin`、`git worktree add ../<root>-<id> -b feature/<id> origin/main`<br>• 指令 `openspec new change <id>`（[說明](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)） | • Feature 資料夾（[範例](https://github.com/yschiang/cross-node-root/tree/main/openspec/changes/project-skeleton)）<br>• ticket，狀態「準備中」（[範例](https://github.com/yschiang/cross-node-root/issues/1)） |
| 2 | Agent | Research：讀<br>• roadmap 上這個 Feature 那一列<br>• 需求輸入與共用限制<br>• 現況 spec、設計與 ADR<br>• 這次會碰到的程式 | • skill [research-codebase](../../skills/research-codebase/SKILL.md)<br>• 有 `graphify-out/` 時，先用 `/graphify query` 查 | 研究報告：`docs/research/<日期>-<主題>.md`（[範例](../research/2026-09-25/integration-gaps.md)） |
| 2 | Project Lead 或 Engineer | 讀報告，有疑問就追問 | — | — |
| 3 | Agent | 寫 proposal：<br>• 為什麼做<br>• 做什麼、不做什麼<br>• 待決與依賴 | 同一個 session | proposal（[範例](https://github.com/yschiang/cross-node-root/blob/main/openspec/changes/project-skeleton/proposal.md)） |
| 3 | Project Lead 或 Engineer | 確認範圍：目標、做／不做 | — | — |
| 4 | Agent | 寫 spec：<br>• 從需求輸入帶入需求（ADDED／MODIFIED）<br>• 由上往下問：流程 → 規則 → 例外 → 驗收，每輪 1–3 題<br>• 每條寫成帶 ID 的 Scenario | 指令 `openspec validate <id>`（[說明](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)） | spec（[範例](https://github.com/yschiang/cross-node-root/blob/main/openspec/changes/project-skeleton/specs/engineering-baseline/spec.md)） |
| 4 | Project Lead 或 Engineer | 回答、修正；需求本來就模糊時，自己輸入 `/grill-me` 深問（要同時寫 ADR 與詞彙表就用 `/grill-with-docs`）；只有某一條 AC 不確定時，要 Agent 只針對那條追問 | — | — |
| 5 | Project Lead | 看一頁摘要，◆確認 spec；同時是 Engineer 時，改到 B1 一起確認 | — | proposal 裡的確認紀錄 |
| 6 | Project Lead | 指定：<br>• 誰確認開工<br>• 誰驗收 | — | — |
| 6 | Agent | 交接：<br>• 組交接包，貼成 ticket 留言<br>• ticket 補上 AC ID，狀態改「就緒」 | 同一個 session | • 交接包<br>• ticket 狀態「就緒」 |
| 6 | Engineer | 核對交接包：能開始就開始，不行就退回具體問題 | — | — |

**每一步怎麼做、怎樣算完成**

1. **開 Feature**
   - 怎麼做：
     - 填上 Feature 名稱；已知的限制或疑慮一起講
     - change id 用簡短的英文，例如 `finalize-protocol`；branch 就叫 `feature/<id>`
     - ticket 照下方的格式：標題就是 Feature 名稱，不加前綴，貼上 label `feature`（每個 repo 建一次）
   - 完成：
     - [ ] Agent 回報已載入 feature-to-spec skill
     - [ ] branch `feature/<id>` 從最新的 `origin/main` 開出、已 push，上面有 `openspec/changes/<id>/`；記下起點 commit
     - [ ] ticket 的 Spec 連到這條 branch 上的 change，寫明 Blocked by，狀態「準備中」
2. **Research**
   - 怎麼做：只查這個 Feature 會碰到的流程。
   - 完成：
     - [ ] 報告存進 feature branch 的 `docs/research/`，已 commit
     - [ ] Facts、Assumptions、Unknown 分開列
3. **寫 proposal、確認範圍**
   - 怎麼做：先談目標與範圍，範圍談定才寫需求；新的高層邊界寫進設計文件或 ADR，由 proposal 引用。
   - 完成：
     - [ ] `proposal.md` 已 commit，有為什麼做、改了什麼、不做什麼
     - [ ] 待決與依賴：每條寫明是否擋住設計與 owner
     - [ ] Project Lead 或 Engineer 同意了範圍
4. **寫 spec**
   - 怎麼做：
     - 從 Project 情境裡跟這個 Feature 有關的那一步搭骨架，再往下問
     - 需求從需求輸入帶進來：`openspec/specs/` 還沒有的用 ADDED，已經有的用 MODIFIED
     - 檢查這次碰到哪些共用限制
   - 完成：`specs/<能力>/spec.md` 寫好，沒有一項還標「假設」
     - [ ] 每條需求都有 ID，至少一個帶 ID 的 Scenario（也就是 AC）
     - [ ] 主流程與每個例外都有 Scenario
     - [ ] 沒有一條待決會改變範圍、行為或驗收
     - [ ] `openspec validate <id>` 通過
5. **◆確認 spec**
   - 怎麼做：看下方的一頁摘要，不必讀檔案。
   - 完成：
     - [ ] proposal 記下誰、何時、原話和確認的 commit；兼任時記「併入確認開工」
6. **交接**
   - 怎麼做：
     - Project Lead 指定開工確認人（通常是 Engineer）與驗收人（預設是 Project Lead；需求由別人提出時，指定那個人）
     - Agent 照參考手冊的[交接](reference.md#交接)清單組交接包
     - Engineer 對照 spec 與 AC，看能不能開始設計
   - 完成：
     - [ ] 交接包貼成 ticket 留言，內容有：
       - [ ] change ID 與 spec 的檔案版本
       - [ ] ◆確認 spec 的紀錄，或「併入確認開工」的註記
       - [ ] 引用的 project intent、高層設計、roadmap 版本
       - [ ] spec／AC 與設計邊界
       - [ ] 每個受影響 repo 的 base branch、commit 與預定要開的 PR
       - [ ] 依賴：上游的版本與狀態
       - [ ] 待決、決策者與下一位 owner
       - [ ] 開工確認人與驗收人
     - [ ] ticket 本文連到交接包留言，寫明 spec 確認（已確認的 commit，或併入開工確認）
     - [ ] 「驗收」列出每個 AC ID，名稱照抄 spec 的 Scenario 標題（未勾選）；標題漏了會改變判定的條件，就改 spec 的標題
     - [ ] 狀態「就緒（可設計）」，下一步是 Engineer 核對交接包
     - [ ] Engineer 在 ticket 回覆可以開始，或列出具體問題退回
     - [ ] Agent 最後在對話裡給一份摘要：change id、branch 與 worktree、推上去的 commit 與 proposal／spec 連結、ticket 連結與狀態、交接包留言連結、AC ID、spec 確認、開工確認人與驗收人、待決事項，以及 Engineer 下一步要貼的 `/spec-to-plan` prompt

ticket 長這樣（交接完成時）：

```markdown
**Milestone：** M1 跨 Node 檔案讀取　**狀態：** 就緒（可設計）
**下一步：** Engineer 核對交接包

## 目標
App 寫完檔案後，能拿到明確的發布結果：只有內容已發布才回成功。

## Spec
- [change](…)：範圍、不做、需求與驗收都以這裡為準（branch `feature/finalize-protocol`，開 PR 後改連 PR）
- 交接包：[留言](…)
- spec 確認：已確認 `a1b2c3d`

## 驗收
勾選＝驗收人已確認這一條；證據看驗收包與驗收紀錄的留言。
- [ ] AC-F01 內容已發布才回 SUCCESS
- [ ] AC-F02 同內容重試不重複發布

## Blocked by
- #1 專案骨架：接受並 merge 後解除；Project Lead
```

一頁摘要長這樣：

```text
目標：……                          → proposal.md#why
不做：……                          → proposal.md
規則：ING-01 ……、ING-02 ……        → specs/<能力>/spec.md
例外：AC-I03 重複寫入、AC-I04 逾時
待決：Q1 容量上限（阻擋設計，確認前要先決定）
版本：<commit 或檔案 hash>
```

**細節**：參考手冊的[需求放在哪](reference.md#需求放在哪)、[Spec 怎麼寫、放哪](reference.md#spec-怎麼寫放哪)、[交接](reference.md#交接)。

### A5 Retro：併入規格與回顧

**目的**：把做完的需求變成系統現況，並用這次的經驗調整後面的計畫。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Agent | 接受後，整理 1–3 個有證據的改善建議 | 同一個 session | Retro 候選（ticket 留言） |
| 2 | Agent | 更新 roadmap，提出接下來的 Feature 候選 | 同一個 session | roadmap |
| 3 | Agent | 所有 PR 都 merge 後，在 root 更新過的 main 上併入規格（archive），commit、push，再移除 feature worktree | 指令 `openspec archive <id> --yes`（[說明](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)） | • `openspec/specs/` 更新<br>• Feature 資料夾移到 `openspec/changes/archive/` |

**每一步怎麼做、怎樣算完成**

1. **整理 Retro 候選**
   - 怎麼做：從這次的 review、CI 與退回紀錄找改善。
   - 完成：
     - [ ] 每個候選都有來源、原因、改善、owner、驗法
     - [ ] 貼成 ticket 留言；沒有證據就不寫
2. **更新 roadmap**
   - 怎麼做：重看切法、依賴與順序。
   - 完成：
     - [ ] roadmap 草稿已更新，下一個候選標為「近期」
     - [ ] A5 做完後回到 A3 ◆確認 roadmap
3. **併入規格**（archive）
   - 怎麼做：先確認每個受影響 repo 的 PR 都已 merge；在 root 的主要 checkout（不是 feature worktree）切到 main 並 pull，確認 merge 已在上面，再執行。
   - 完成：
     - [ ] `openspec/specs/` 和已 merge 的實作一致
     - [ ] Feature 資料夾移到 `openspec/changes/archive/`
     - [ ] ticket 補上 `changes/archive/` 位置的固定 commit 連結，狀態「已完成」；關票由人決定

有依賴的 Feature 要等上游接受並 merge 後才開始實作。

**細節**：參考手冊的[驗收之後：收尾](reference.md#驗收之後收尾)。

## 內圈：一個 Feature

上圖的 Feature 圈放大後分兩段：**Implement**（B1–B2，設計並做出來）→ **Validate**（B3–B4，用審查、CI 與人工驗收證明是對的）。內圈是 Engineer 和驗收人的工作，只帶專案的人可以直接看 B4。

```mermaid
flowchart LR
  A4["A4 Specify"] -->|交接包| B1
  subgraph SIMP["Implement"]
    direction TB
    B1["B1 Design<br/>寫實作 plan"] -->|◆確認開工| B2["B2 Build<br/>交給 agent 執行"]
  end
  subgraph SVAL["Validate"]
    direction TB
    B3["B3 Verify<br/>Review 與 CI"] -->|PR Pass 驗收包| B4(["B4 Accept<br/>◆驗收：驗收人"])
  end
  B2 --> B3
  B4 -->|退回修正| B2
  B4 -->|需求要改| A4
  B4 -->|接受| A5["A5 Retro"]
  classDef gate fill:#fdf0ea,stroke:#eb6c36,color:#2d3142
  classDef outer fill:#eff6ff,stroke:#2563eb,color:#172554
  class B4 gate
  class A4,A5 outer
  style SIMP fill:#fafafa,stroke:#b8bfcc
  style SVAL fill:#fafafa,stroke:#b8bfcc
```

Project Lead 同時擔任 Engineer 時，◆確認 spec 併入 ◆確認開工：spec、設計、計畫一起確認一次。不同人擔任時分開，Project Lead 先確認 spec，Engineer 才開始設計。

內圈在 feature 的 worktree 依序跑四個指令。人要決定的只有兩處：spec-to-plan 停下時的 ◆確認開工，和 to-pr 停下後的 ◆驗收；plan-to-code 做完直接接 to-pr。

| 順序 | 指令 | 停在哪 | ticket 狀態 |
| --- | --- | --- | --- |
| 1 | [`/spec-to-plan`](../../skills/spec-to-plan/SKILL.md) | ◆確認開工 | 就緒（可設計）→ 開發中 |
| 2 | [`/plan-to-code`](../../skills/plan-to-code/SKILL.md) | 每個 task 都審過、沒有未解的 blocking，接著直接跑 to-pr | 開發中 |
| 3 | [`/to-pr`](../../skills/to-pr/SKILL.md) | PR Pass，等 ◆驗收 | 開發中 → 待驗收 |
| 4 | [`/project-lead`](../../skills/project-lead/SKILL.md) | 記下驗收結果 | 待驗收 → 已接受，或退回開發中 |

中途卡住的 skill 會把狀態標成 Blocked，寫明原因與下一步找誰。

### B1 Design：寫實作 plan

**目的**：決定怎麼做、拆成哪些 task。

先把 Feature 垂直切成 tasks，再替每個 task 選一種計畫：

| | 預設 | 加一層程式碼計畫 |
| --- | --- | --- |
| 什麼時候用 | 一般 task | Engineer 指定，例如 legacy 上 PBI 大小的 task |
| 計畫寫到哪 | `tasks.md`：要證明什麼（測試、Red 應失敗的斷言），不寫程式碼 | 另外用 Superpowers `writing-plans` 寫 `task-plans/<task>.md`，寫到程式碼 |
| 怎麼做 | Implementer 用 TDD，自己決定實作 | Implementer 照程式碼計畫用 TDD |
| 之後 | 逐 task 審查、`to-pr`，兩種相同 | 同左 |

**legacy 先補特性測試**：要改的 legacy 路徑沒有測試保護時，不論哪種計畫，第一個 task 都是補特性測試（characterization test）：實際執行程式，把現有行為記錄成測試，之後改錯才抓得到。這類 task 的 Implementer 用強模型（D72，見參考手冊的[模型怎麼選](reference.md#模型怎麼選)）。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Engineer | 開始寫設計與計畫 | skill [spec-to-plan](../../skills/spec-to-plan/SKILL.md)：開一個 Agent session，貼上：`/spec-to-plan 準備〈Feature〉的設計與計畫：讀交接包，寫 design.md 與 tasks.md，交另一個模型審到 clean，停在確認開工。` | — |
| 2 | Agent | 寫詳細設計 | 指令 `openspec instructions design --change <id>` | design |
| 3 | Agent | • 垂直切 tasks：每個 task 走完一條完整路徑、能單獨驗證、一個 session 做得完<br>• 先做讓後面好做的整理；需要共用的測試骨架時，排成第一個 task；legacy 路徑沒有測試保護時，第一個 task 補特性測試<br>• 每個 task 選計畫：預設，或 Engineer 指定的加一層程式碼計畫<br>• 每個 task 寫明依賴哪些 task、從它們拿到的介面與不變式<br>• 每個 task 列出要寫的測試，寫明 Red 應該失敗在哪個斷言<br>• 每個 task 標出 Implementer 與 Reviewer 的 effort<br>• 寫每條 AC 的驗法<br>• 交另一個模型審計畫到 clean | • 指令 `openspec instructions tasks --change <id>`<br>• 切法參考 skill [to-tickets](../../skills/third-party/mattpocock/engineering/to-tickets/SKILL.md)（Matt Pocock）的垂直切片規則，不放實作碼 | • tasks<br>• AC 驗法：寫在 validation 文件或 tasks 的明確段落 |
| 4 | Agent | 帶確認開工的人走過計畫：切法、高風險 task 的測試、AC 對照、計畫自己做的決定、風險 | 同一個 session，一次一段 | — |
| 5 | 交接時指定的人 | ◆確認開工（兼任時連 spec 一起確認） | 同一個 session，停在這裡；確認記成 ticket 留言 | 開工確認紀錄 |

**每一步怎麼做、怎樣算完成**

1. **開始寫設計與計畫**
   - 怎麼做：在 feature 的 worktree 貼上 prompt，把〈Feature〉換成 change 的 id。要替某個 task 加一層程式碼計畫時，在 prompt 後面加一句「〈task〉加一層程式碼計畫」；也可以等 Agent 切好 tasks 後再指定。接下來依[內圈的四個指令](#內圈一個-feature)往下跑；誰可以代為啟動，見參考手冊的[控制方向與自主程度](reference.md#控制方向與自主程度)。
   - 完成：
     - [ ] Agent 回報已載入 spec-to-plan skill
     - [ ] Agent 讀完交接包，沒有要退回的問題；研究報告已 commit
     - [ ] 改到 legacy 時，研究報告寫明要改的路徑有沒有測試保護
2. **寫詳細設計**
   - 怎麼做：在 A2 定的邊界內，決定模組、介面與資料流。
   - 完成：
     - [ ] `design.md` 寫明怎麼滿足每條需求
     - [ ] 超出邊界的問題已回報 Project Lead
3. **拆 tasks、寫 AC 驗法**
   - 怎麼做：
     - 垂直切：每個 task 從公開入口走完一條完整路徑，能單獨驗證；不切只做一層的 task
     - 每個 task 一個 session 做得完，註明改哪個 repo；太小、無法單獨審查的就合併
     - 每個 task 只列真正要先完成的 task，並寫出從它們拿到的介面：簽名、不變式、順序限制與錯誤情況
     - 一次牽動所有呼叫端的大範圍改動（例如改名），改用先加新的、分批遷移、再刪舊的順序
     - 計畫寫死要證明什麼，怎麼寫程式留給 Implementer：不放實作碼，但每個 task 列出要寫的測試：名稱、斷言的可觀察行為、Red 應該失敗在哪個斷言、Green 的預期結果、執行指令（為什麼這樣分，見參考手冊的[為什麼計畫不寫程式碼](reference.md#為什麼計畫不寫程式碼)）
     - 好幾個 task 都要用到的 fixture、setup、指令入口或回傳合理值的 stub，排成第一個 task 先做，後面每個 Red 才走得到要測的行為
     - 每條 AC 寫：怎麼驗、在哪驗、何謂通過、證據放哪
     - 需要時，替某個 task 多一層程式碼層級的計畫（例如 legacy 上 PBI 大小的 task）：用 writing-plans 寫進 change 的 `task-plans/<task>.md`，從 tasks.md 連過去；其他都不變
   - 完成：
     - [ ] tasks 有 ID、交付什麼、依賴與介面，每個 task 註明改哪個 repo、對到哪些 AC
     - [ ] 每個 task 都能單獨驗證，沒有只做一層的 task
     - [ ] 每個 task 列出要寫的測試，每個測試寫明斷言、Red 應失敗的位置、Green 預期與指令
     - [ ] 共用的測試骨架排在第一個 task；不需要時寫明理由
     - [ ] 要改的 legacy 路徑沒有測試保護時，第一個 task 是補特性測試
     - [ ] 每個 task 標明用哪種計畫；加一層程式碼計畫的，`task-plans/<task>.md` 已寫好並一起審過
     - [ ] 每條 AC 都有驗法
     - [ ] 每個 task 標出模式、Implementer 的模型，以及 Implementer 與 Reviewer 的 effort（預設強模型；見參考手冊的[模型怎麼選](reference.md#模型怎麼選)）
     - [ ] scope、必要環境、風險與執行限制都寫明
     - [ ] 另一個模型審過計畫，結果 clean，紀錄在 change 裡
4. **走過計畫**
   - 怎麼做：Agent 先給一頁摘要，再一次帶你看一段；每段先給幾行白話重點（做什麼、可能出什麼錯、要你決定什麼），細節等你問了再展開：
     1. 切法：task 表、依賴、effort，最可能超出一個 session 的 task
     2. 高風險 task（xhigh，或對到最多 AC 的）的測試：每個測試斷言什麼行為、Red 證明什麼、Green 的預期；用來判斷做出來的會不會是你要的
     3. AC 對照：每條 AC 由哪些測試證明，哪些留給後面的 Feature 或人工驗收
     4. 計畫自己做的決定：交接包留給 Implementer 的待決項，以及和高層設計不同的地方與理由
     5. 風險、限制與已接受的風險，包括測試證明不了的部分
   - 每段看完可以提問、提出要改的地方；看夠了才進下一步。要跳過也可以，確認紀錄會寫明。
   - 完成：
     - [ ] 五段都走過，或確認紀錄寫明跳過
     - [ ] 要改的地方都已記下
5. **◆確認開工**
   - 怎麼做：選一個：批准、只調 effort、改計畫、再多看一些。只調 effort 就更新 `tasks.md` 後直接記錄；改到測試、task、owned paths 或 design，就回到計畫審查，審到 clean 再確認；兼任時連 spec 一起確認。
   - 完成：
     - [ ] ticket 留言記下誰、何時、原話和確認的版本
     - [ ] ticket 狀態「開發中」

**細節**：參考手冊的[做出來：Engineer 的細節](reference.md#做出來engineer-的細節)。

### B2 Build：交給 agent 執行

**目的**：一個 task 一個 task 把行為做出來，每一步都能驗證。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Implementer | TDD：<br>• 照計畫先寫會失敗的測試<br>• 確認 Red 失敗在要測的斷言上<br>• 再實作到通過 | • skill [plan-to-code](../../skills/plan-to-code/SKILL.md)：`/plan-to-code 實作〈Feature〉`，照每個 task 標的 effort 派工、收件檢查<br>• skill [test-driven-development](../../skills/third-party/superpowers/test-driven-development/SKILL.md)（Superpowers） | • commits<br>• Red → Green 紀錄 |
| 2 | Reviewer（另一個模型，最好是另一家） | 審這個 task 的 commit，finding 分成現在修、PR 前修、開 ticket | 獨立 Reviewer，例如 `codex exec` | 局部 review 紀錄（ticket 留言） |
| 2 | Implementer | 修掉 blocking，Reviewer 覆核；修正另開 commit，不改寫審過的 commit；每個 task 最多 3 次 | — | 修正的 commits |

**每一步怎麼做、怎樣算完成**

1. **TDD**
   - 怎麼做：一次一個 task：照計畫列的測試先寫、跑出 Red，確認它失敗在計畫寫的斷言上，再實作到 Green。Red 停在 setup、import 或 stub，代表骨架還沒好，先補骨架再重跑，不算數。
   - 完成：
     - [ ] 每個行為 task 都有 Red 與 Green
     - [ ] 每個 Red 都失敗在對應的斷言上，不是停在 setup、import 或 stub
     - [ ] 協調的人收件時檢查過 Red 的失敗位置，不對就退回
     - [ ] 純文件的 task 寫明理由，由 Reviewer 確認
2. **局部 review 與修正**
   - 怎麼做：
     - 局部 review：只審這個 task 的 commit，對照 spec 與 design。
     - 修正：修掉 blocking 後交 Reviewer 覆核；不同意的 finding，附證據交 Reviewer 再看一次。
   - 完成：
     - [ ] Reviewer 是另一個模型、新開的 session
     - [ ] review 結果貼成 ticket 留言
     - [ ] 每個 blocking 的修正都經 Reviewer 覆核
     - [ ] 局部 review 沒有未解的 blocking

**細節**：參考手冊的[做出來：Engineer 的細節](reference.md#做出來engineer-的細節)。

### B3 Verify：Review 與 CI

**目的**：用獨立審查和 CI 證明整個 Feature 符合 spec。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | Agent | G1：在全新 clone、要送出的版本跑完整測試，通過才送審 | • skill [to-pr](../../skills/to-pr/SKILL.md)：`/to-pr 送出〈Feature〉`<br>• skill [verification-before-completion](../../skills/third-party/superpowers/verification-before-completion/SKILL.md)（Superpowers） | 測試結果 |
| 2 | Implementer | 每個受影響的 repo 開一個 PR，連到同一張 ticket；root 的 PR 就是 `feature/<id>` | GitHub | PR |
| 3 | Reviewer＋CI | • G2：Reviewer 審整組 PR<br>• G3：CI 跑必要 checks | • 建議用 skill [review-panel](../../skills/review-panel/SKILL.md)：兩家以上的 Reviewer 從不同角度審，finding 互相驗證；也可以只用一個 Reviewer<br>• GitHub Actions | review 與 CI 結果 |
| 3 | Implementer | 修正，最多 3 輪，超過就標 Blocked 交給人，人可以追加輪數（D70）；每次 push 都重新評估 | 同一個 session：to-pr 把修正交給 [plan-to-code](../../skills/plan-to-code/SKILL.md)，再重跑 gates | 新的 commits |
| 4 | Agent | 三個 gates 都在目前版本通過後，整理驗收包 | • 同一個 session；欄位列在 [to-pr](../../skills/to-pr/SKILL.md) 裡<br>• 核對每個 gate 的證據都對應目前版本<br>• controller 可用後由它核對 | PR Pass 驗收包（ticket 留言） |

**每一步怎麼做、怎樣算完成**

1. **G1：完整測試**
   - 怎麼做：在整合後的版本跑全部測試。
   - 完成：
     - [ ] 全部通過才開 PR
2. **開 PR**
   - 怎麼做：每個受影響的 repo 一個 PR，互相連結；root 的 PR 從 `feature/<id>` 開。
   - 完成：
     - [ ] PR 都開好，都連到同一張 ticket
     - [ ] ticket 的 Spec 改連 root 的 PR
     - [ ] 描述連到 spec
3. **G2 審查、G3 CI 與修正**
   - 怎麼做：
     - G2 審查、G3 CI：Reviewer 對照 spec 與 design 審整組 PR；CI 同時跑。建議用 review-panel：單一 Reviewer 判定 clean 的版本，在 A/B/C 重跑的盲測裡仍留著 2 到 5 個 major，多一家不同角度的 Reviewer 補得最多（D73）。
     - 修正：
       - 一次修完一批 findings
       - 每次 push 後 G1–G3 都重新評估
       - 3 輪還沒過就轉 Blocked，交人決定
   - 完成：
     - [ ] 同一組版本的 review 與 CI 結果都收齊
     - [ ] 沒有未解的 blocking
4. **整理驗收包**
   - 怎麼做：逐一確認三個 gates 的證據都對應目前版本，再照交接契約的欄位寫。
   - 完成：
     - [ ] 三個 gates 都在目前版本通過
     - [ ] 每條 AC 都有結果與證據
     - [ ] 每個受影響 repo 的 PR、base／head commit、CI 與 review 連結
     - [ ] 風險與已知限制
     - [ ] run ID，或手動執行的人
     - [ ] 已用的修正輪數
     - [ ] 驗收包貼成 ticket 留言，本文「驗收」連到這則留言，狀態「待驗收」

**細節**：參考手冊的[做出來：Engineer 的細節](reference.md#做出來engineer-的細節)：gates 的證據與 review-fix loop。

### B4 Accept：驗收

**目的**：由人判斷結果是不是真的是要的。

| Step | Who | Do | How | Output |
| --- | --- | --- | --- | --- |
| 1 | 驗收人 | 看驗收包和 demo，逐條對照 AC | — | — |
| 2 | 驗收人 | ◆驗收：<br>• AC 沒達成：退回修正<br>• 需求要改：回 A4 | skill [project-lead](../../skills/project-lead/SKILL.md)：開一個 Agent session，貼上：`/project-lead 記錄〈Feature〉的驗收：〈驗收人〉〈接受／退回〉，原話〈…〉。` | 接受或退回紀錄（ticket 留言） |
| 3 | 人 | merge：<br>• 接受、而且版本仍適用時才 merge<br>• 多個 PR 照依賴順序，提供方先<br>• 每個 PR 單獨 merge 都要安全（向後相容） | GitHub | merge |

**每一步怎麼做、怎樣算完成**

1. **對照 AC**
   - 怎麼做：看驗收包和 demo，一條一條對。
   - 完成：
     - [ ] 每條 AC 都看過證據
2. **◆驗收**
   - 怎麼做：AC 沒達成就退回 B2 修正；需求要改就回 A4，用 `feature-to-spec` 修改這個既有的 Feature（沿用原本的 branch 與 ticket）。
   - 完成：
     - [ ] 接受或退回記成 ticket 留言：誰、何時、原話、版本
     - [ ] 接受：ticket 只勾驗收人確認過的 AC，狀態「已接受」
     - [ ] 退回寫明判定的版本與沒過的 AC，舊的 PR Pass 作廢
     - [ ] 既有 AC 沒過：修正和 B3 共用修正額度（三輪，人可以追加）；還有額度就回到「開發中」，修正後重跑 to-pr，用完就轉 Blocked
     - [ ] 需求要改：回 A4，不算修正輪數，ticket 狀態改回「準備中」
3. **merge**
   - 怎麼做：多個 PR 照依賴順序，提供方先；每個 PR merge 前確認它單獨 merge 也安全（向後相容）。
   - 完成：
     - [ ] 每個 PR 都確認過單獨 merge 是安全的
     - [ ] PR Pass、接受、merge 分開記錄
     - [ ] 接著到 A5

**細節**：參考手冊的[交接](reference.md#交接)（驗收包要看什麼）、[驗收之後：收尾](reference.md#驗收之後收尾)。

## Milestone 驗收
待定：跨 Feature 的整合驗證怎麼控還在討論。Milestone 驗收不能把一串 PR 綠燈直接加總成完成。

## 想知道為什麼

本手冊只說怎麼做。規則本身、設計理由與取捨在內部設計文件：[決策紀錄](../decisions.md)、[交接契約](../workflow/contracts.md)、[流程設計](../workflow/overview.md)、[SA 階段契約](../workflow/project-lead-sa.md)；手冊和它們有出入時，以它們為準。各主題對應哪條決策，見參考的[想知道為什麼](reference.md#想知道為什麼)。repo 結構與範例演練路線在[參考](reference.md)。
