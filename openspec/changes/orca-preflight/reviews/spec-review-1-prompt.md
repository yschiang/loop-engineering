你是獨立的 spec 審查者（Claude Fable 5.1），在全新 session、唯讀。不要修改任何檔案。輸出用繁體中文。

目前目錄是 loop-engineering 的全新 clone，checkout 在 `79bdb45`（branch `feature/orca-preflight`）。這是 Feature 2a「loopctl preflight：確認 Orca 的 Claude、Codex worker 能安全派工」（change `orca-preflight`，ticket #44）的 spec。spec 作者是 Claude Opus 5.5。Project Lead 準備確認這份 spec；確認之後才進 spec-to-plan（design 與 tasks）。你的工作是在確認前找出 spec 的問題。只審 spec，不審 design 或程式（還沒有）。

## 讀這些

- 受審文件：`openspec/changes/orca-preflight/proposal.md`、`openspec/changes/orca-preflight/specs/durable-delivery/spec.md`、`openspec/changes/orca-preflight/specs/delivery-gates/spec.md`。
- 需求輸入（原文，D53 採用）：`docs/requirements/delivery-controller/specs/durable-delivery/spec.md` 的 DUR-02、DUR-09；`docs/requirements/delivery-controller/specs/delivery-gates/spec.md` 的 GAT-05、GAT-08。勘誤 `docs/design-candidate/d45-04-errata.md`（E-5）。驗法 `docs/design-candidate/d45-04/validation.md` 的 M-PRE（f1–f6）與 §5 的 R1；設計 `docs/design-candidate/d45-04/design.md` §6。
- 現行產品 spec（Feature 1 併入）：`openspec/specs/*/spec.md`；Feature 1 的 change：`openspec/changes/archive/2026-10-03-run-decisions/`（看它的 proposal 怎麼處理「觸發情境不存在時改用新 ID」）。
- 決策：`docs/decisions.md`（D38、D46、D48、D52、D53、D75、D76、D79）。D80、D81 還在 PR 裡，用 `git show origin/docs/split-orca-preflight:docs/decisions.md` 讀；roadmap 的 2a 列用 `git show origin/docs/split-orca-preflight:docs/roadmap.md`。
- 研究：`docs/research/2026-10-03/orca-dispatch/research.md` 與 `verification.md`（衝突時以 verification 為準）。

## 檢查

1. **忠實度**：需求輸入 DUR-02、DUR-09、GAT-05、GAT-08 的每一句 SHALL，在 2a 的 spec 裡是被帶入、被明確延後（proposal 的「不做」或「和 roadmap 不同的地方」有寫）、還是被某個決策改掉（要能引到 D 編號或勘誤）？列出被默默拿掉或改變意思的句子。
2. **可驗證性**：每個 scenario 的 WHEN 與 THEN 是否能在公開入口（CLI、receipt、`status`、`next`）觀察與測試？有沒有含糊的字（例如「被拒」要怎麼觀察、「確認停止」以什麼為準）？有沒有在 CI（沒有 Orca）與真實 R1 之間說不清由誰驗證的？
3. **一致性**：與 D38／D81、D52、D76、D79、D80、E-5 是否矛盾？MODIFIED DUR-02 是否完整保留現行 requirement 的內容（MODIFIED 會整條取代）？proposal 與 spec 之間有沒有不一致（範圍、AC 清單、新 ID 的理由）？
4. **AC ID**：新 ID（D26、D27、D28、G23、G24）是否和需求輸入或 `openspec/specs/` 的既有 ID 衝突？G11、G12 改用新 ID 是否符合 Feature 1 的先例？原 ID 有沒有被改寫或重用？
5. **完整性**：主要流程與每個例外是否都有 scenario？例如 Orca 不可用、政策沒核准或 digest 不符時跑 preflight、receipt 屬於另一個 profile digest、同一個 profile 有多份 receipt、preflight 中途中斷、探測 worker 留下的資源。缺的請列出，並說它會不會改變範圍、行為或驗收。
6. **範圍**：有沒有寫進屬於 Feature 2 或之後的東西（每次派工的核對、assignment、結果匯入、卡住偵測），或寫進了 design 的決定（具體參數、檔案格式、實作方式）？

## 輸出

逐條列 finding：ID（S-1、S-2…）、`blocking` 或 `non-blocking`、位置（檔案與行或 scenario ID）、問題、證據（引原文與行號）、建議的改法。`blocking` 只用在會改變範圍、行為或驗收，或使某個 scenario 無法驗證的問題。最後一行寫 `VERDICT: clean`（沒有 blocking）或 `VERDICT: changes_required`。
