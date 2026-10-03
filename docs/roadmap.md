# Roadmap：薄 controller（loopctl）

> 2026-09-30 經 Project Lead 確認（D75）；2026-10-03 Feature 1 收尾後重切（D79），同日把 R1 從 Feature 2 切成 Feature 2a（D80）。審查紀錄：GPT-6 Astra xhigh 三輪到 clean，見 [`reviews/2026-09-30-roadmap/`](reviews/2026-09-30-roadmap/README.md)。

來源（皆為 `main@a1d8906`，另註明者除外）：

- 需求輸入：[`docs/requirements/delivery-controller/`](requirements/delivery-controller/README.md)，四個 capability、36 條 requirement、88 條 AC；D53 採用，組成方式見同目錄的 `adoption/source-map.md`。原本放在 `openspec/changes/implement-delivery-loop/specs/`，依 D75 原樣搬移（見下方「退役」一節）。
- 高層設計：D45-04 revision-17（[`docs/design-candidate/d45-04/`](design-candidate/d45-04/)，D53 核准），以及[勘誤](design-candidate/d45-04-errata.md) E-1～E-3。驗法以其中的 `validation.md` 為準。
- 既有實作：branch `delivery/thin-controller@fcefecc`，唯讀參考（D75），不 merge。6,054 行程式、8,825 行測試、549 個測試；完成 T1.1～T3.1、T6.1、T7.1，T4.x、T5.1、T6.2 沒做。
- 行數、依賴與 AC 對照：[重切研究](research/2026-09-30/controller-recut.md)。

**為什麼重切**：D53 把整個薄 controller 當成一個 change、17 個 task。目前完成的部分已有約 14,900 行（含測試），還少 review 迴圈與 PR Pass；全部做完會是一個跨四個 capability 的 PR。之後 D57 定為一個 Feature 一個 change、一個 PR 做得完，太大就拆；D74 要求 Feature 垂直切。所以改成四個 Feature，每個都是從 orchestrate 或 CLI 操作到持久狀態與驗收測試的一條完整路徑，能單獨驗收，各走 feature-to-spec → spec-to-plan → plan-to-code → to-pr。

**原則**：roadmap 只有 Milestone 與 Feature 兩層（D57、D65）。task 寫在各 Feature change 的 `tasks.md`，不上 roadmap。M1 的切法有既有實作與已核准的設計當依據，所以整批列出；M2 先只寫交付能力。每個 Feature 驗收後回來重切。

## Milestones

| Milestone | 目標日期 | 可以展示的成果 | 完成條件 | 交付能力 |
| --- | --- | --- | --- | --- |
| **M1：薄 controller 可用** | 未定（D75、D79） | 一個真實 Feature 由 orchestrate 透過 loopctl，從交接包走到 PR Pass 或 Blocked。過程包含派工、三 gates、finding → fix → re-review，中途中斷一次後接續；狀態與證據都可查。 | 1. M1 的全部 Feature（1、2a、2、2b、3、4、5，D77、D80）都已接受、merge 並 archive。<br>2. 「M1 驗收」四項都完成（見下）。 | 人工決策與可追溯狀態；派工與結果回收；三 gates；finding 迴圈與 PR Pass |
| **M2：example 與延後能力**（暫不切） | M1 完成後定 | cross-node-file-transfer 由 orchestrate＋loopctl 從 Project 跑到多個 Feature（D43、D56） | M1 完成後定 | 見下方「延後到 M2」 |

目標日期依 D75 暫不設；Feature 1 接受後（D79）仍暫不定，Feature 2 完成後再看。原先的估法（約 7 個工作日加一週緩衝）見[重切研究](research/2026-09-30/controller-recut.md#時間估計的依據)。

## M1 的 Feature

「近期」是接下來要開 change 寫 spec 的；「暫定」只有名稱、範圍與依賴，排進近期時才寫 spec，也可能重切。orchestrate skill 在 Feature 2 建立，之後每個 Feature 延伸它，讓自己的行為能從 orchestrate 走到。

| # | Feature | 狀態 | 看得到的行為 | 可參考的既有實作（`fcefecc`） | 依賴 | 相關需求輸入 | 勘誤與 issue |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | loopctl：登記 run、記錄人工決策、查詢狀態與下一步 | 已完成（#29、PR #37，併入規格 PR #38） | Engineer 登記一個 Feature run，含 spec、design 與 plan 的版本。人用 `decide` 記錄開工確認等決策。`status` 與 `next` 顯示持久狀態，以及唯一允許的下一步；中斷後從檔案接續。包含專案骨架，以及 CI `unit-linux`（D53）。 | T2.1、T2.2；T1.1 的 CLI、測試政策、CI、`workflow.yaml` | — | ORC-01、02、03、07、11、12；GAT-06；DUR-01、02、05、08（範圍見 change `run-decisions`） | #6 |
| 2a | loopctl preflight：確認 Orca 的 Claude、Codex worker 能安全派工 | 近期（D80，#44） | Engineer 在 `workflow.yaml` 登記兩個 profile（Implementer：Orca 的 Claude agent＋`claude-opus-5-5`；Reviewer：Orca 的 Codex agent＋`gpt-6-astra` xhigh），以 `policy_change` 核准（D76）。`loopctl preflight` 對每個 profile 經 Orca 派一個探測 worker：model、effort、cwd 由 native 紀錄讀回；權限負例（寫出擁有範圍、push、`gh`、派工以外的 `orca` 子命令、`loopctl decide`）都被拒；worker 接受 Orca 的 preamble 並交出 `worker_done`。結果寫成 receipt，記下 Orca 與 agent CLI 的版本；`status` 顯示每個 profile 是否驗證過與理由；profile 沒驗證過、政策沒核准或 Orca 版本變了，`next` 就不給派工。建立各接法分開的能力證據矩陣。 | T1.1 的 profiles 與 preflight | 1 | GAT-05、08；DUR-02（worker 的權限限制）、09（範圍見 change `orca-preflight`） | E-5 |
| 2 | orchestrate 經 Orca 派 Implementer、收回結果，卡住時交給人 | 近期（D79）；spec 等 2a 的 R1 結果再寫（D80，#43） | orchestrate 從交接包開始：叫 spec-to-plan，把 design 與 plan 登記到 loopctl，停在 ◆確認開工（D55、D69）。人確認後，依 `next` 用 R1 驗證過的 profile，經 Orca 把 Implementer 派進 `engineer` 工作區（D76）。外部寫入先登記、再讀回，沒有回應轉成 unknown，由人用 `decide` 處理。結果先保存，再去重匯入。察覺卡住（session 結束卻沒交結果、API 或 infra 錯誤、長時間沒有新輸出）就停止派工交人（D79）。每次派工把實際結果補進 2a 的能力證據矩陣；engineer 工作區 clear 時機的實驗。 | T1.2、T2.3；T7.1 的 worker 預算部分 | 2a | ORC-01、03、08；DUR-02、03、04、06、08、09（含從 Feature 1 移過來的 AC-D13、D16、O02、D17；D17 照 E-6 讀） | E-1（#9）、E-2（#11）、#7 |
| 3 | TDD 證據、PR 與 CI | 暫定 | Implementer 的結果匯入後，orchestrate 依 `next` 讓 loopctl 核對 G1：原始 Red 的資格、乾淨 checkout 的 Green、N/A 紀錄、整合 attempt，以及證據命令的時限。接著 push，建立或更新 PR，等待 CI（30 分鐘），只認 PR head 上 `unit-linux` 的 success 判定 G3。R2：orchestrate 在 probe branch 用 fixture 真實跑到 G1。 | T3.1、T6.1；T7.1 的證據與 CI 預算部分 | 2 | ORC-03；GAT-01、02、03、04、06、07、08；DUR-03、06、07、08、09（含從 Feature 1 移過來的 AC-G13） | #15 |
| 4 | 獨立審查與 PR Pass | 暫定 | orchestrate 依 `next` 派獨立 Reviewer：不同模型、新 session，review 時限 30 分鐘。G2 綁定 head、base 與文件版本。finding 流程包含登記、合併成修正批次、覆核、一次爭議覆核、反覆 finding 提前升級，上限三輪。最後發布 review 與 PR Pass 驗收包。 | 無（T4.1、T5.1、T6.2 沒有實作） | 3 | ORC-01、05；GAT-01、03、05、06、07、08；DUR-04、06、07、08、09；FIN-01～07（含從 Feature 1 移過來的 AC-F07、F11、O11） | E-3（#12） |

**D77 新增的 Feature**（排序見「依賴」；與上表合起來是 M1 的全部 Feature）：

| # | Feature | 狀態 | 看得到的行為 | 依賴 | 相關需求輸入 |
| --- | --- | --- | --- | --- | --- |
| 2b | 只有 OpenCode 的環境也能派工 | 暫定 | 在只有 OpenCode 的環境（同樣有 Orca），Orca 把 Implementer 與 Reviewer 都開成 OpenCode worker；兩者以 OpenCode 設定檔指定不同的實際模型（D52）；兩個 profile 各跑 R1，effort 讀不回時記為未驗證。 | 2 | DUR-09（AC-D24，原排 M2；AC-D20 要求環境沒有 Orca，仍在 M2） |
| 5 | 本日目標：互不依賴的多個 Feature 同時跑到 PR Pass | 暫定 | 人在的時候寫一份本日目標（幾個互不依賴的 Feature），協調者先把每個 Feature 的計畫寫好、審到 clean，人一次走過並確認開工；之後無人看守，各 Feature 同時（設上限）跑到 PR Pass，預算、逾時、卡住自動停下交人。merge 一律由人；merge 一個後，其他 PR 自動更新 base 並重跑檢查，衝突才停。不做 stacked。 | 4（與 2b） | ORC-01、DUR-02、DUR-08，以及 D11、D27 |

**時間上限（D79）**：不設主動時間與各角色的時間上限，改為察覺卡住就停下交人；修正 3 輪與 infra 重試上限不變。表中「預算」「時限」「review 時限 30 分鐘」「CI（30 分鐘）」的字樣照 D79 讀。

**Runtime（D76）**：Feature 2 起，派工從 Herdr 改為 Orca。Implementer（Claude＋`claude-opus-5-5`）與 Reviewer（Codex＋`gpt-6-astra` xhigh）分別派進固定名稱的 Orca 工作區 `engineer`、`reviewer`；表中寫 Herdr 的地方照 D76 讀。Orca 版本改變時先重跑 R1；Orca 回 `consumer_fenced` 時停下交人；協調權與人工決策仍在 loopctl。engineer 工作區的 clear 時機在 Feature 2 實驗。

**依賴**：上表五個 Feature 是一條鏈（1 → 2a → 2 → 3 → 4），依 D27 依序開工；2b、5 的位置見「D77 新增的 Feature」：上游接受並 merge 後，下游才開始實作。等上游時，可以先準備下游的 spec。

**跨 Feature 的 AC**：29 條 AC 的驗證跨兩個以上的階段，清單與各自的完成點見[重切研究](research/2026-09-30/controller-recut.md#跨階段的-ac)。

- 每個 Feature 的 spec delta 只寫這個 Feature 結束時已經成立的部分。
- 原 AC 由最後一個 Feature 補齊。對前面已經 archive 的 requirement，後面的 Feature 用 MODIFIED。
- 例如 AC-F07「三輪已用完」：Feature 1 只記錄延長輪次的人工決策，轉 Blocked 要到 Feature 4 才成立。
- 需要 R3 或 workflow 樣本的部分，在「M1 驗收」補齊。Feature archive 時不宣稱這部分已成立。

**既有實作怎麼用**：`delivery/thin-controller` 保留為唯讀參考，不 merge，也不再加 commit。

- 每個 Feature 從 `origin/main` 開 `feature/<change-id>` 與自己的 worktree（D67）。
- 要沿用舊程式時照 TDD：先寫計畫列的測試，存下原始 Red，再移植或重寫實作。
- 舊的測試結果、逐 task 審查與 preflight 紀錄，都不算新 Feature 的證據。profile 已經改過，preflight 要重跑。
- 舊實作審查留下的已知問題，已列在上表最後一欄。

## M1 驗收

M1 的全部 Feature 都 merge 後進行。它不是 Feature，而是 M1 的完成條件；紀錄放在 `validation.md` §3–§5 指定的位置，用一個 docs PR 交付。

| 項目 | 內容 | AC | Owner | 審查 |
| --- | --- | --- | --- | --- |
| R3 | 用 cross-node-file-transfer 的第一個 Feature（D75）。登記 baseline 後，經它自己的 D11 確認，由 orchestrate＋loopctl 跑完。三 gates 在目前版本都通過；改變行為的修正有綁定 finding 與 batch 的原始 Red；中斷一次後成功接續。Blocked 或沒有 finding 時 R3 維持 open，M1 不算完成（`validation.md` R3、AC-G20）。 | G01、G20、D14 的真實交付部分 | Project Lead 選 Feature；Engineer 執行 | G2 照常 |
| Workflow 樣本 | 照 `validation.md` §3 的 W-A～W-F，每組一個正例與一個負例。正例盡量取自 M1 的真實紀錄（本 roadmap、交接包、◆確認開工、D27 的依序開工、orchestrate 的結果匯入）；「模板存在」不算通過。 | 只由樣本驗證的 11 條（F12、O04、O12、O13、O17、O20、O21、O24、O25、O27、O28）；O16（Feature 2 另有 orchestrate 的文件清單）；另 6 條的樣本部分（O01、O15、O19、O22、O23、O26） | 照 §3 各組的 owner | 獨立 Reviewer 依 rubric 審查，結果記在 `proof.md` |
| 本日目標實跑 | 一份本日目標，至少兩個互不依賴的 Feature；計畫一次確認後無人看守跑完，各自到 PR Pass 或 Blocked，紀錄可查。 | 跑完後依 Feature 驗收 | Project Lead 寫目標與確認；Engineer 執行 | G2 照常 |
| 能力證據矩陣 | Feature 2a 建立；Feature 2、3、4 與 R3 各自補上證據。每項能力分列 `fake`、`profile-probe`、`real-E2E`，依接法分開，未執行的格子標 `none`（§4）。 | G19、D22 | Engineer | 同上 |

## 延後到 M2

- **整條延後的 5 條 AC**（D45-04 tasks「延後」一節；AC-D24 依 D77 提前到 M1 的 Feature 2b）：
  - adopt（O08、O09）；
  - Project Lead 委派（O18）：依 D55 縮為「授權啟動 run」的紀錄；
  - Retro（O14）：依 D55 改由 project-lead skill 承接，不做 controller 的 Retro op；
  - OpenCode-only 部署（D20，環境沒有 Orca）；
  - OpenCode-only 部署指的是沒有 Orca 的環境（AC-D20）；有 Orca 的 OpenCode 環境由 M1 的 Feature 2b 承接。
- **M1 只成立一部分的 AC**：
  - O23：M1 在 scope 變更時停下整個 run；只停受影響的工作、其餘繼續，延到 M2。
  - G15：M1 只驗整合 SHA 無法映射時轉 unknown；映射能力延到 M2。
  - D23：M1 只驗未選用的接入不阻斷已選路徑；OpenCode-only 的變體延到 M2。
- **其他能力**：
  - 唯讀的專案進度視圖（D55（7））；
  - 跨 Feature 依賴自動化、平行 worktree 與整合規則；
  - Q-STACK；
  - 是否由 controller 強制逐 task 的獨立 review（D57（4）留給 S2，待決；Feature 4 的 G2 審整個 PR，不等於逐 task review）；
  - 多人交接（Q-DEMO-PEOPLE）。

## `implement-delivery-loop` 退役

這個 change 把整個薄 controller 當成一個交付（D53），和 D57「一個 Feature 一個 change」不符；內容也還寫著 D55、D56 之前的規則（#5）。依 D75，和本 roadmap 同一個 docs PR 做這些事：

1. 把 `specs/` 的四份 capability 與 `adoption/source-map.md`，原樣搬到 `docs/requirements/delivery-controller/` 當需求輸入，不改寫內容。搬移前後核對每個檔案的 sha256 相同；D53 的核准快照（`d11-approval.json`）不受影響。
2. 清查引用。目前約 40 個檔案提到這個 change 的路徑：
   - 現行入口改寫：`README.md` 的「接續狀態」，以及 `docs/README.md` 的目前進度與「先讀哪份」第 4 點。改指本 roadmap 與新的需求輸入；接續依據從 handoff 改成本 roadmap。
   - 受 hash 保護的檔案不改：D53 核准的 `docs/design-candidate/d45-04/` 候選原檔（`d11-approval.json` 綁定）。它們提到的舊路徑，在勘誤新增一項轉接到新位置，照「原檔＋勘誤」判讀。
   - 決策紀錄的既有列不改內容：`docs/decisions.md` 的 D40、D53 等列是當時的紀錄；退役本身記成新的一列（D75）。
   - 導覽會帶到的文件（`docs/decisions.md` 的 D40 列、`docs/harness/scope-reconciliation.md`、`docs/handoffs/2026-09-27-controller-design.md`）中指向已刪檔案的連結，改成 `a1d8906` 的固定連結，其他文字不改。
   - 審查與實驗紀錄（reviews、experiments、manifest）是當時版本的證據，不改。需求輸入的 README 寫明舊路徑與最後存在的 commit（`a1d8906`）。
3. 刪除 change 目錄，不 archive。這個 change 沒有交付；archive 會把還沒實作的行為寫進 `openspec/specs/`，違反 D58。`proposal.md`、`design.md`、`tasks.md`、`approval.json` 與 adoption 審查紀錄，以 `a1d8906` 的固定連結保存。
4. D53 的核准保留為歷史紀錄。D45-04 design 改作高層設計的參考；每個 Feature 的 `design.md` 由 Implementer 依它的章節寫（D69）。
5. 相關 issue：
   - #5 隨退役關閉。
   - #1（S1 epic）改為追蹤 M1，或關閉。
   - #8 隨重做失效：新的 commit 各自綠燈。

## 已確認（D75）

以下是 2026-09-30 確認時的內容；之後 D76（runtime 改為 Orca）與 D77（新增 Feature 2b、5 與本日目標實跑）修訂了 Feature 清單與 M1 完成條件，以上方的表格為準。

1. **切法與順序**：四個 Feature，照 1 → 2 → 3 → 4 依序做，四個都 merge 後做 M1 驗收。
2. **M1 目標日期**：暫不設；Feature 1 接受後依實際速度定。
3. **`implement-delivery-loop` 退役**：照上一節，在本 PR 執行。
4. **workflow AC**：在 M1 驗收用 W-A～W-F 樣本與 rubric 驗證，不當 controller 的 Feature。
5. **D61 的解讀**：D61 的「不當任何產品的 root」指不當其他產品的 root；loopctl 是單一 repo 的產品，roadmap、需求輸入與 change 都放在本 repo，不需要 `repos.yaml`。
6. **既有實作**：`delivery/thin-controller@fcefecc` push 成唯讀參考 branch，不開 PR、不 merge、不再加 commit。
7. **R3**：用 cross-node-file-transfer 的第一個 Feature；它的 D11 在 Feature 4 收尾後進行。
8. **Feature 1 的分工**：spec 由 Claude（Opus 5.5）用 feature-to-spec 準備，Project Lead 確認；Engineer 與驗收人是 Project Lead（D62）；G2 用單一 Reviewer（GPT-6 Astra xhigh），不用 review-panel。
