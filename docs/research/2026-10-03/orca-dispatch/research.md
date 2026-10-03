---
date: 2026-10-03T08:39:10+0800
researcher: Claude Agent SDK subagent（claude-opus-5-5），research-codebase 方法
repository: yschiang/loop-engineering
topic: Feature 2（orca-dispatch）現況研究：AC 歸屬、Feature 1 基準、Orca 能力、卡住偵測、R1 與參考實作
tags: [research, loopctl, orca, feature-2, orca-dispatch, stuck-detection, preflight]
git_commit: 7fea8d4417ab3f823274c35a12fe83411c2f0a40
branch: feature/orca-dispatch
base: main@458ab7777b5cae15a34e265e55710da893303d9c
working_tree: clean（寫入本報告前）
status: complete
last_updated: 2026-10-03
last_updated_by: Claude Agent SDK subagent（claude-opus-5-5）
---

# Feature 2（orca-dispatch）現況研究

## 研究問題

Feature 2「orchestrate 經 Orca 派 Implementer、收回結果，卡住時交給人」（change `orca-dispatch`，#43）開 spec 之前，盤點：要承接的 AC 與其中哪些能在 Feature 2 端到端成立；Feature 1 已實作的基準與延伸點；Orca 實際提供什麼、loopctl 還要負責什麼；D79 的三種卡住訊號能否觀察；兩個 profile 的 R1；參考實作能沿用多少；規模。本文只描述現況與證據，不寫 spec、design 或 plan。

## 摘要

- **AC**：Feature 2 首先驗證 19 條（含從 Feature 1 移來的 D13、D16、O02、D17）。其中 7 條可在 Feature 2 完成（D04、D05、D08、D18、D19、D21、D23 的 M1 部分）；其餘 12 條只成立一部分，完成點在 Feature 3（D06、D13、D16、O06）、Feature 4（D12、D17、G11、G12、O02）或 M1 驗收（G19、D22、O16）。另外 D07（原排 Feature 4 首先驗證）有一部分可在 Feature 2 成立。AC-D17 依 E-6 改成「察覺卡住」，原 b0～b7 案例不再適用，要由 Feature 2 的 spec 重寫。
- **Feature 1 基準**：`next` 核准後回 `{action: dispatch, plan, approval}`（[`next.py:69-73`](../../../../src/loopctl/next.py)），envelope 的 `safety`／`blocked` 永遠是 null，`decide` 不收 `resolve_read`／`resolve_operation`，`workflow.yaml` 只有 `g3`，產品程式零依賴、不讀 YAML。這些都是 Feature 2 的延伸點。
- **Orca（1.4.218）**：`worker-start` 一次完成 Task、Dispatch、placement 與 prompt；有 `--retry-request`／`request-show` 冪等；有 `worker-list` 的 liveness 判定、`worker-read` 的 transcript（每則訊息帶 timestamp）、`worker-stop`／`abandon`。沒有權限旗標（「there is no flag for it」），`--terminal`（重用 session）不能同時帶 `--model`／`--effort`，沒有 native session ID 欄位，沒有「卡住」或 API 錯誤的分類，而且明文規定「absence never authorizes stop」。
- **卡住偵測**：訊號 1（結束卻沒交結果）有 Orca 承認的正面證據；訊號 2（API／infra 錯誤）Orca 不分類，但 Claude 的 native transcript 以結構化欄位記錄 API 錯誤，要區分「自行恢復的重試」與「重試用完、以錯誤結束」；訊號 3（N 分鐘沒有新輸出）可由 transcript 最後一則訊息的 timestamp 量到，但 Orca 把「tail 沒變」定義成 absence，不授權 stop，所以這個訊號只能支持「停止派工並交人」。Feature 1 的 B1（502）同時符合訊號 1、2，當時因 `dispatch.sh` 的 `set -e` 沒寫 `exit_code` 而約 10 分鐘沒人發現；2.1「沒有網路」其實是權限 allow 清單的缺口，不屬於三種訊號；4.1 的 26 分鐘停滯最後自行恢復，低於 30 分鐘門檻。
- **R1**：本機的 Claude 與 Codex native 紀錄確實含 model、effort、cwd；但 Orca 不提供 native session ID 或 transcript 路徑，能否從 Orca 派出的 worker 找到它的 native 紀錄要 live probe。另有兩個舊實測風險：2026-09-25 的 Claude worker 把 Orca preamble 當成注入而拒絕；Codex sandbox 內呼叫 Orca 回 `runtime_unavailable`。
- **參考實作**：`writes`、`assignments`、`observe` 的狀態機與去重大多與 transport 無關；Herdr 綁定集中在 `tools/herdr.py`（227 行）與少數 argv、handle 欄位。但它的 store 介面、plan 格式（`loopctl-plan` YAML 區塊）與 pyyaml 依賴都和 main 不同，不能直接搬。
- **規模**：估計程式約 2,400～2,900 行，是 Feature 1（1,715 行）的 1.4～1.7 倍；測試依比例約 3,600～6,700 行（參考實作約 1.5 倍、Feature 1 約 2.3 倍），含測試合計約為 Feature 1（5,699 行）的 1.1～1.7 倍。D79 的回答紀錄是卡住偵測「放進 Feature 2，不再拆」；若 design 認為一個 PR 太大，D57(2) 允許在 design 時提議拆分。

## 1. 來源與版本

| 來源 | 位置 | 版本 |
| --- | --- | --- |
| Feature worktree | `/Users/johnson.chiang/workspace/loop-engineering-orca-dispatch` | `feature/orca-dispatch@7fea8d4`（只加了 `openspec/changes/orca-dispatch/.openspec.yaml`），base `main@458ab77` |
| Roadmap | [`docs/roadmap.md`](../../../roadmap.md) | 同上；Feature 2 列 L32，時間上限 L43，Runtime L45，跨 Feature AC L49-54 |
| 決策 | [`docs/decisions.md`](../../../decisions.md) | D13 L23、D52 L64、D53 L65、D55 L67、D57 L69、D69 L81、D76 L88、D77 L89、D78 L90、D79 L91 |
| 需求輸入 | [`docs/requirements/delivery-controller/specs/`](../../../requirements/delivery-controller/specs/) | delivery-orchestration、delivery-gates、durable-delivery（sha256 依 D75 不變） |
| 勘誤 | [`docs/design-candidate/d45-04-errata.md`](../../../design-candidate/d45-04-errata.md) | E-1～E-6（E-5 L37-42、E-6 L44-49） |
| 高層設計 | [`docs/design-candidate/d45-04/`](../../../design-candidate/d45-04/) | revision-17：`design.md`、`validation.md`、`coverage.md`、`tasks.md` |
| 現行產品 spec | [`openspec/specs/`](../../../../openspec/specs/) | Feature 1 archive 後的 delivery-orchestration、delivery-gates、durable-delivery |
| Feature 1 change | [`openspec/changes/archive/2026-10-03-run-decisions/`](../../../../openspec/changes/archive/2026-10-03-run-decisions/) | proposal、design（D1–D14）、tasks |
| 已實作程式 | [`src/loopctl/`](../../../../src/loopctl/)、[`tests/`](../../../../tests/)、[`workflow.yaml`](../../../../workflow.yaml) | `src` 1,715 行、`tests` 3,984 行、69 個 `test_` 函式 |
| 重切研究 | [`docs/research/2026-09-30/controller-recut.md`](../../2026-09-30/controller-recut.md) | AC 階段對照與跨階段 AC |
| Orca 研究 | [`orca-runtime.md`](../../2026-10-01/orca-runtime.md)、[`reanalysis-answers.md`](../../2026-10-01/reanalysis-answers.md)、[`runtime-probe.md`](../../2026-09-25/runtime-probe.md) | 1.4.215（10-01）、1.4.209（09-25） |
| Orca 本機 | `/usr/local/bin/orca` | **1.4.218**（`orca --version`、`orca status --json` 的 `runtime.appVersion`）；`orca skills get orchestration --full` 795 行，sha256 `708b665f49a6d928dda414780eb36544799564bd4d3f9de0a77e8e8ee40b23d7`（存於本 session scratchpad，未提交） |
| 參考實作（不是證據） | `/Users/johnson.chiang/workspace/loop-engineering-thin` | `fcefeccf2a5e`（working tree 乾淨） |
| Feature 1 的人工派工工具 | `/Users/johnson.chiang/workspace/loop-engineering-run-decisions/.delivery/run-decisions/loop/`（`dispatch.sh`、`verify.sh`、`review.sh`、`impl-prompt.py`、`settings.template.json`、`goal.md`、`ledger.md`）與 `tasks/<t>/attempt-<n>/` | worktree `02f1498`；`.delivery/` 不受 git 追蹤 |
| Native 紀錄（唯讀抽樣） | `~/.claude/projects/…/<session>.jsonl`（本 session 與 Feature 1 的 B1、4.1）、`~/.codex/sessions/2026/10/03/rollout-*.jsonl`（最新一份） | 只讀欄位名稱與 model、effort、API 錯誤紀錄，不引用內容 |

Orca 的探測只用唯讀命令：`--version`、`status --json`、各命令 `--help`、`skills get`、`agent-context --json`、`run-list`、`run-current`、`worktree list`、`repo list`，以及對 2026-09-25 舊 Run（`run_95da348b16c4`）的 `worker-list`、`worker-show`、`worker-read`、`task-list`。沒有建立、綁定或改變任何 Orca 物件。

## 2. Feature 2 的 AC 清單

### 2.1 逐條歸屬

「首先驗證／完成」沿用重切研究的對照（[controller-recut.md](../../2026-09-30/controller-recut.md) L61-132）。「F2 端到端」指 Feature 2 結束時，從 orchestrate 或 CLI 操作到持久狀態與測試都能成立的部分。

| AC | 情境（原文節錄） | coverage 驗證 | F2 端到端 | 其餘歸屬與理由 |
| --- | --- | --- | --- | --- |
| **ORC-01** |  |  |  |  |
| O01 | 「使用者直接交付已選定的 feature 給 Implementer」→「允許進入 design/plan 準備…不要求經 Project Lead 轉達」 | d1；W-C | 已在 F1 成立（`openspec/specs/delivery-orchestration` L12-14）；F2 的 orchestrate 從交接包起步時沿用 | V：W-C 樣本 |
| O02 | 「系統只接受經 controller 許可、由持有該 feature 協調權的 orchestrate 派出的 assignment。沒有協調權的 session 只能讀取狀態；局部 review 不能更新 G2」 | s4；r1 | 部分：派工 op 需要 owner token；沒登記的 attempt 結果不能匯入 | F4：「局部 review 不能更新 G2」要有 G2（r1）。從 F1 移來。Orca 讀法：其他 session 仍能直接 `worker-start`，D76(3) 不加鎖，所以「只接受」只能落在 loopctl 拒絕匯入沒登記的 Dispatch |
| O18 | 授權 Project Lead 協調與委派 | d8（只驗拒絕） | 否 | M2（roadmap L78） |
| O19 | 「不從入口／父子標記新增委派權或 scope 變更權」 | d5；W-E | 已在 F1 成立；F2 的 R1 負例（worker 呼叫 `loopctl decide` 被拒）從 runtime 這一層補強 | V：W-E 樣本 |
| **ORC-03** |  |  |  |  |
| O05 | 「沒有適用版本的明確使用者確認」→「不派 implementation worker」 | d1、d2 | 已在 F1 成立 | — |
| O06 | 「controller 依序發出 task 許可，由 orchestrate 派出；交接帶每項 AC ID 與驗法。正常的 finding 修正不需逐 task 再批准」 | d3；R2 | 部分：d3（第一個 assignment 帶 AC ID 與驗法，需要解析 plan，F1 proposal L67 列為 F2）、依序派 task | F3：R2 真實跑到 G1。F4：finding 修正不需再批准 |
| O07 | 「修正需要改 AC、spec 或已核准設計」→「取得適用確認後才依新契約派工」 | d4 | 已在 F1 成立。F2 新增的情境（attempt 進行中收到 `scope_change`）不在 coverage 中 | — |
| **ORC-08** |  |  |  |  |
| O16 | 「結果與 evidence 交 controller 核對並記錄，不由 skill 自訂 feature Pass 或另啟排程」 | W-E；T4.1 DOC | 部分：orchestrate skill 只依 `next` 詞彙行動，結果只經 `result import` 生效 | V：W-E 樣本；roadmap L70 寫明「O16（Feature 2 另有 orchestrate 的文件清單）」 |
| **GAT-05** |  |  |  |  |
| G11 | 「由 orchestrate 派出符合核准 runtime/model 與隔離限制的 Reviewer…只有適用目前版本的 clean verdict 可使 G2 通過」 | r1；f4；R1 | 部分：f4（兩個 profile 的 model 相同 → unverified）與 Codex profile 的 R1 | F4：G2 判定（r1）。Reviewer 派工在 F4 |
| G12 | 「Reviewer 的工具可改作者 branch，或獨立性／隔離尚無可核對證據」→「不採為 G2」 | r1；f5；R1 | 部分：f5 與 R1 的權限負例 | F4：r1 |
| **GAT-08** |  |  |  |  |
| G19 | 「所選 Herdr＋runtime profile 的原生完成讀回、Reviewer 權限能力或正確 workspace placement 尚未驗證」→「保留個別能力缺口，不聲稱 V4 或完整 E2E 通過」 | `proof.md` rubric（validation §4） | 部分：建立能力證據矩陣，依接法分欄（roadmap L72） | F3、F4、R3 補證據；V 完成 |
| G20 | 真實 review 沒有 finding | r1；R3 | 否 | F4、V |
| **DUR-02** |  |  |  |  |
| D03 | 兩個 run 搶同一 feature | s4 | 已在 F1 成立 | — |
| D04 | 「worker 超時且 runtime／接入服務無法查詢，或只見 terminal idle／缺少 status」→「保存 unknown…不派競爭 writer…已知 active 的 worker 到期時，可以對它發停止並讀回」 | w5、w8、b2；R1 | 是：writer 結束的判定（result 匯入＋native turn 完成，或 stop 經確認）| 「超時」「到期」照 E-6 讀成卡住（§2.2） |
| **DUR-03** |  |  |  |  |
| D05 | 「result 的 repo/workspace、attempt、snapshot 或 scope 與 assignment 不符」→「保留原件並拒絕」 | w6 | 是 | — |
| D06 | 「runtime 完成輸出只能由 runtime 讀回工具 讀 native messages，且 notification 未到」→「保存原文與來源 identity…不捏造 Orca worker_done」 | w8、o2；R2 | 部分：w8、o2 | F3：R2 的真實 native-only 讀回 |
| **DUR-04** |  |  |  |  |
| D07 | 「result 已完整保存但 worker 通知遺失，或 controller 在匯入前 crash」→「匯入一次，保留原 attempt，不因漏通知重派」 | u1 | 部分：Implementer attempt 的 `worker_done` 遺失、結果檔已存在，可在 F2 成立，但 coverage 只有 u1 | F4：u1 含 review 已保存與 `publish_issue` pending |
| D08 | 「同一 result 重複到達，或同一 attempt 帶不同 bytes」→「不同內容保留雙方證據並 Blocked」 | w7 | 是 | — |
| **DUR-06** |  |  |  |  |
| D12 | 「已接受發文，協調者未收到回應即中斷」→「依原 marker 查回…不再貼一份」 | w2、p5、w10、h10 | 部分：w2、w10（派工與 prompt 的讀回；Orca 對應 `request-show`） | F3：h10（PR）。F4：p5（發布） |
| D13 | 「外部請求結果 unknown，查不到 marker 且無法證明未執行或可去重」→「保留 outcome unknown 與查詢證據並 Blocked」 | w1、w3、w10、w11、d9、h10、h11 | 部分：w1、w3、w10、w11、d9（`resolve_operation`） | F3：h10、h11（GitHub 寫入）。從 F1 移來 |
| **DUR-08** |  |  |  |  |
| D16 | 「同一 infra operation 初次失敗及兩次額外重試均無法完成」→「保存三次 attempts 與 evidence 並 Blocked；不把診斷出的程式／測試缺陷繼續包裝成 infra retry」 | w4、o1、o3、h8、d9 | 部分：w4、o1、o3、d9（`resolve_read`） | F3：h8（CI 讀取）。從 F1 移來 |
| D17 | 原文：「累計主動時間達 4h…」→「不再派新工作…停止無法確認時維持 active／unknown」 | b0～b7、g15、d10；R1 | 部分：依 E-6 改讀為「察覺卡住並停下交人」；Implementer 的卡住在 F2 | F3：CI 等待與證據命令。F4：review。原 b 系列以時間上限為前提，要重寫。從 F1 移來 |
| D25 | 預算調整只記錄人工裁決（F1 新 ID） | `test_scope_policy` 等 | 已在 F1 成立 | D79 拿掉時間上限後，`active:<分>`、`ci_wait:<H>` 兩種目標失去作用對象（`decisions.py:46-51`）；是否以 MODIFIED 改 DUR-08 由 spec 決定 |
| **DUR-09** |  |  |  |  |
| D18 | 「requested workspace/model 與回傳 identity 或實際執行設定不一致，或只有 input_accepted」→「不宣稱派工／工作成功…不能從 shell cwd、`current` 或角色名稱推定」 | f3、f6、w6；R1 | 是（若 R1 能讀到 native 紀錄，§6） | — |
| D19 | 「目前 adapter 不能在核准隔離條件下取得可信結果／lifecycle」→「具體 Blocked 與最小能力需求」 | f1、f4、f5；R1 | 是 | — |
| D20 | 環境沒有 Orca 的 OpenCode-only 部署 | 未覆蓋 | 否 | M2（D77(4)、roadmap L80） |
| D21 | 「分別接收 Herdr handles、Orca dispatch 或 OpenCode session/message 的原生識別」→「結果可對回自己的 run/task/attempt…不為 OpenCode 補造 Orca ID」 | w9 | 是：Orca Run／Task／Dispatch ID 加 native ID | — |
| D22 | 「任一接法已驗證通過，而另一接法…尚未驗證」→「按接法保存可用能力與缺口，不共用成功標記」 | `proof.md` rubric | 部分：矩陣建立，Orca＋claude、Orca＋codex 分欄 | V |
| D23 | 「run 選用已核准且可用的 profiles…未選用的接入…不存在、未登入或連線失敗」→「SHALL NOT 以未選用接入的失敗阻斷已選路徑」 | f2 | 是（M1 部分） | M2：OpenCode-only 變體（roadmap L85） |
| D24 | 兩個角色都經 OpenCode | R1 不能證明 | 否 | Feature 2b（D77(4)） |

**F2 結束時可宣稱完成的**：D04、D05、D08、D18、D19、D21、D23（M1 部分）。其餘依 roadmap L51-54 的規則，F2 的 spec delta 只寫結束時成立的部分，原 AC 由後面的 Feature 以 MODIFIED 補齊。

### 2.2 原文假設 Herdr 或時間上限的地方

| 位置 | 原文 | 依 E-5／E-6 的讀法 |
| --- | --- | --- |
| 三份需求 spec 開頭（L6） | 「第一條實作路徑是 Herdr 原生 sessions／panes／worktrees」 | Orca（E-5） |
| GAT-05 第 3 段（delivery-gates L104） | 「OpenCode 仍是預設 runtime（D38）；本機第一條路徑經 Herdr 啟動 OpenCode（OpenAI models）或 Claude Code」 | Orca 的 `claude`（Implementer）與 `codex`（Reviewer，`gpt-6-astra` xhigh）；D76(2) 修訂 D53 的 reviewer profile |
| AC-G19 | 「所選 Herdr＋runtime profile」 | Orca＋claude、Orca＋codex |
| DUR-03 第 2 段（durable-delivery L54） | 「外部 handles（Herdr session／workspace／pane／agent name、runtime native session ID）」 | Orca 的 Run、Task、Dispatch ID 加 native session ID，具體欄位由 F2 design 定（E-5 L41） |
| DUR-09 本文（durable-delivery L146） | 「第一條本機實作路徑 SHALL 由 Herdr…Orca…SHALL 為選配…Orca 專有 Run/Dispatch/terminal 欄位不能成為共用契約的必填條件」 | E-5 把 transport 改成 Orca，但沒有改寫「Orca 選配」這句；`docs/project-intent.md` L77、L84 也仍寫 OpenCode 預設、Orca 選配。只要 Orca 欄位放在 transport handle、不進共用契約，兩者仍可並存；這個衝突需要 spec 處理，本文不判定 |
| AC-D23 | 「第一片：Herdr＋Claude Code 的 Implementer、Herdr＋OpenCode 的 Reviewer…未選用的接入（Orca、Codex CLI…）」 | 已選：Orca＋claude、Orca＋codex；未選：Herdr、OpenCode。f2 案例要改寫，而且 Codex CLI 變成已選 profile 的一部分 |
| AC-D04 | 「worker 超時」「已知 active 的 worker 到期時」 | 照 E-6 讀成察覺卡住 |
| DUR-08 本文（L130-134）、AC-D17 | 「4h 主動執行」「workflow.yaml 的 `timeouts`」「Active budget 到限」 | E-6：不設時間上限；卡住門檻（預設 30 分鐘）寫在 `workflow.yaml`；修正 3 輪、infra 額外重試 2 次、停止與讀回的有界規則不變 |
| validation f5、R1 | 權限負例含 `herdr` | 改成 `orca`，但 worker 必須能呼叫 `orca orchestration send`／`check` 才能交 `worker_done`（§6） |
| validation b0～b7、design §10 | 4h、45／30／30 分 | E-6 L49：「以時間上限為前提的案例不再適用」 |
| design §5「輪詢」理由 | 「Herdr 與 native transcript 是本機讀取」 | 改為 Orca CLI 讀取（`worker-read`、`worker-list`） |

## 3. Feature 1 已提供的基準與延伸點

| 能力 | 位置 | Feature 2 要延伸的地方 |
| --- | --- | --- |
| CLI 派送與命令 | `cli.py:342-351` `HANDLERS`；`cli.py:403-454` `build_parser` | 加 `write`、`observe`、`result import`、`safety`、`preflight` 等子命令（高層設計 §2） |
| Envelope | `cli.py:27-43`：`safety` 永遠是 `None`；archived design L78「`blocked` 與 `safety` 在本 Feature 永遠是 `null`」 | 填入 `safety`（stop 與讀回優先）與 `blocked` |
| 持久狀態 | `store.py:155` `load`、`store.py:308-338` `commit(key, expected_revision, transition_id, payload, mutate, *, authorize, resolves)`、`store.py:506`／`527` `put_object`／`get_object` | 新的頂層欄位（`writes`、`attempts`、`assignments`、`observations`、`read_budget`…）；archived design L27、L135：「讀取時缺欄位視為空」，`schema_version` 只在不相容時遞增 |
| 衍生欄位 | `store.py:22` 匯入 `derive`；每次提交都重算 | `next` 目前只依狀態（archived design L467 的風險：「之後加入時間或外部輸入的 Feature 要在自己的 design 重新界定」）。卡住偵測依賴時間與外部讀取，正好落在這條 |
| `next` 動作 | `next.py:60-79` 的順序：未解衝突 → 未 claim → 已核准回 `dispatch`（L69-73）→ 未登記 plan → plan 阻擋 → 等 `approve_plan` | archived design D8（L279-288）：「Feature 2 以 MODIFIED 決定 `dispatch` 如何接到實際的派工動作」。高層設計 §2 的封閉詞彙（`wait`、`observe`、`write`、`import`、`human`…）還沒有實作 |
| 決策種類 | `decisions.py:18-26` `KINDS`（7 種）；其他 kind（含 `resolve_read`、`resolve_operation`）回 `unsupported`（archived design D10 末段） | 加 `resolve_read`、`resolve_operation`（F1 proposal L49） |
| 預算目標 | `decisions.py:46-51` `BUDGET_TARGET`：`active:<分>`、`rounds:+1`、`attempts:<unit>:+1`、`ci_wait:<40 hex>` | D79 後 `active`、`ci_wait` 沒有作用對象（§2.1 D25 列） |
| 狀態初值與視圖 | `state.py:26-47` `initial`；`state.py:64-84` `view`；gates 為 `not_evaluated` | `status` 顯示 attempt、op、卡住理由 |
| 時鐘 | `clock.py:8` `now()`，測試以 monkeypatch 替換（archived design D13） | 卡住偵測的時間來源 |
| 協調權 token | archived design L134：「明文 token 由呼叫者保存…Feature 2 的 orchestrate 負責這一步」 | orchestrate 保存與讀回 token |
| 政策檔 | `workflow.yaml` 只有 `g3.required_checks`（5 行）；F1 proposal L12：「profiles、timeouts、limits 由 Feature 2、3 各自用 `policy_change` 加入」 | 加 `profiles` 與卡住門檻；要新的 `policy_change` |
| 依賴 | `pyproject.toml:10` `dependencies = []`；pyyaml 只在 dev（L19）；archived design D1：「產品程式不讀 YAML」 | 讀 `workflow.yaml` 的 profiles 與門檻需要決定：加 pyyaml 為執行依賴，或改用其他格式 |
| plan 內容 | archived design L28：「不解析 plan 的內容，task→AC 的核對在 Feature 2」；F1 的 `tasks.md` 以 Markdown 表格列 task、依賴、effort、AC（archived tasks.md L44-52） | 從 `tasks.md` 取得 task 順序、AC、驗法、擁有路徑與 effort |
| 測試接縫 | `tests/conftest.py`：in-process `cli`、子程序 `cli_proc`／`cli_proc_many`、`LOOPCTL_HOME` 隔離、clock 替換（archived design D13） | 加 PATH 上的 fake `orca`（參考實作用 fake `herdr`，§7） |
| 既有 `dispatch` 測試 | `tests/test_approval.py:606-633`、`test_scope_policy.py:257` | `dispatch` 被 MODIFIED 時，這些斷言要跟著改 |

## 4. Orca 能力對照

版本 1.4.218。「help」指該命令的 `--help`；「skill」指 `orca skills get orchestration --full` 的行號（scratchpad 檔）。

| Feature 2 需要 | Orca 提供（證據） | loopctl 仍需負責 | 需要 live probe（R1） |
| --- | --- | --- | --- |
| 啟動 worker：agent、model、effort | `worker-start --agent claude\|codex --model <id> --effort <level>`；「`--model` supports Claude, Codex…；`--effort` requires `--model`. Neither can combine with `--terminal`」；只有 `ready` exit 0，`failed`／`outcome_unknown` exit 1 並附 `failedStage`、`residualResources`（help） | 先登記 op 再呼叫；把 profile 的 model、effort 轉成參數 | Orca 記錄的 `launch.effective` 是否等於 native 實際值（skill L246-247：「never claim a model or effort from requested arguments alone」） |
| 權限設定 | 沒有：「How the worker runs follows the user's own setting for new agent tabs; there is no flag for it」（help）。自訂 argv 只能 `terminal create --command` 加 `worker-start --terminal`，但這樣不能帶 `--model`／`--effort`（skill L362-387） | 權限設定改由 runtime 自己的設定承載，並以負例驗證 | Claude、Codex 在 Orca 下實際讀到哪一份設定 |
| Placement 與工作區 `engineer`／`reviewer` | `--worktree current\|name:<displayName>\|id:…\|new-child\|new-top-level`、`--repo`、`--base-branch`、`--setup`（help）。現況：`orca repo list` 只有 `cross-node-xfer`（gigaxfer 路徑，folder）；`orca worktree list` 沒有名為 `engineer` 或 `reviewer` 的工作區，也沒有 loop-engineering 的工作區 | 決定由誰、何時建立工作區（§9 Q5）；核對實際 cwd、repo、branch | `name:engineer` 的選擇是否穩定；新工作區的 setup 行為 |
| Task／Dispatch 身份 | Run `run_…`、Task `task_…`、Dispatch `ctx_…`；`worker-show` 的 `dispatch` 有 `assigneeHandle`、`processIncarnation`、`retryOfDispatchId`、`failureCount`、`lastFailure`、`terminationReason`、`lastHeartbeatAt`、`capabilityRevokedAt`（對 `ctx_6f0f35db294f` 實測） | attempt ↔ Dispatch 的對應；assignment 內容（版本、digest、scope、AC） | — |
| Native session ID | 沒有欄位。`worker-read` 回 `provider`、`sourceIdentity`（不透明字串）與每則訊息的 `id`（Claude 為 message uuid）；skill L626-627：「Never guess a provider session ID, transcript path」 | handle round-trip（D21）需要 native ID | 能否從 Orca 取得或可靠推得 native session ID（§6） |
| `worker_done` | `send --type worker_done --outcome succeeded\|failed [--task-id --dispatch-id --files-modified --report-path]`；「completes that task only from the dispatched pane」（help）。舊 Task 的 `result` 鍵：`body`、`completedAt`、`completedBy`、`filesModified`、`messageId`、`outcome`、`provenance`、`reportPath`、`reportedBy`、`subject`（`task-list` 實測） | 結果檔本身（envelope、版本、digest、scope）的保存、核對與去重；`worker_done` 只帶 outcome 與 report 路徑，不是 gate 證據 | Claude、Codex worker 在權限限制下能否送出 `worker_done` |
| Liveness | `worker-list` 的 `projection.liveness.verdict`：`live`／`unverifiable`／`exited`（附 `reason` 或 `source`），另有 `stage.activity`、`evidence.lastObservedAt`、`attention.categories`、`nextAction.argv`；`worker-show` 的 `observation.status` 只反映 PTY，`observation.agentWait` 指出停在只有人能回答的提示（help、skill L46-69、L572-603） | writer 結束的判定（result 匯入＋native turn 完成，或 stop 確認）；`unverifiable` 一律當 unknown | `stage.activity` 有哪些值（舊資料都是 `unknown`）；`agentWait` 的實際觸發 |
| Stop／abandon | `worker-stop`：fence 該 Dispatch，只關它擁有的 agent terminal，不刪 worktree；`worker-abandon`：只 fence，不動程序或檔案（help、skill L666-690）。capability `orchestration.worker-stop-verdict.v1`（`status --json`）。同一 Task 連續失敗 3 次 circuit-break（skill L676-678） | stop 的 op 登記與讀回上限；「process-info 確認」在 Orca 下以什麼為準 | stop verdict 的內容；stop 後 `worker-list` 是否轉 `exited` |
| 冪等與讀回 | 每個 orchestration mutation 都收 `--retry-request <uuid>`；`request-show` 回 `completed`／`pending`／`absent`，「Absent is not proof that nothing happened」（help）；receipt 會被清除（orca-runtime.md §A） | op registry 本身；receipt 清除後的判斷；GitHub 寫入不在 Orca 範圍 | receipt 保留多久 |
| 後續提示（`prompt` op） | `send --to dispatch:<id>`：持久排入，worker 在檢查點才讀，不會中斷（skill L420-424、L751-769） | 第一次的 prompt 由 `worker-start` 注入；後續提示是否算外部寫入 | — |
| Run binding 與 `consumer_fenced` | 一個 Run 一個 coordinator，最後綁定者勝出，以 `consumer_generation` 當 epoch（orca-runtime.md §B）；worker 的 `check` 回 `consumer_fenced` 表示它的 Dispatch 已被接走（skill L766-769）。本 terminal 目前仍綁在 10-01 的 scratch Run `run_b6098d2f6bed`（`run-current`） | D76(3)：只認 loopctl 的 claim token，不比對 Orca binding；收到 `consumer_fenced` 就停下交人 | orchestrate 跑在哪個 terminal、用哪個 Run（`run-create`／`run-use` 會解除其他綁定） |
| 版本 | `orca --version` 與 `status --json` 的 `runtime.appVersion` 都是 1.4.218；但本 terminal 的環境變數 `ORCA_APP_VERSION`、`TERM_PROGRAM_VERSION` 是 1.4.214（terminal 開啟時的值）。自動更新開啟（`remoteUpdateSupport.automatic: true`）。10-01 為 1.4.215，兩天後為 1.4.218 | 每次派工記錄版本，與上次 R1 通過的版本不同就先停（D76(5)）；版本要從 `status --json` 讀，不能用環境變數 | — |
| Clear（新 session 或重用） | 預設每次 `worker-start` 開新的 agent terminal；重用要 `worker-start --task <next> --terminal <handle>`（skill L249-261），而 `--terminal` 不能帶 `--model`／`--effort` | D76(6) 的實驗紀錄（壓縮次數、finding 數） | 重用時 effort 無法逐 task 調整（D69(4) 的 effort 依 task） |

## 5. 卡住偵測（D79）

D79(1)：「session 結束卻沒有交結果、API 或 infra 錯誤，或連續一段時間（預設 30 分鐘，寫在政策檔）沒有新輸出，都算卡住；停止與讀回仍照 DUR-08 的有界規則，unknown 不視為已停止」。E-6 L48 的動作是「停止派工、保存理由與證據並交人」。

### 5.1 三種訊號在 Orca 下的觀察方式

| 訊號 | 可觀察的證據 | 證據來源 | 限制 |
| --- | --- | --- | --- |
| 1. session 結束卻沒交結果 | (a) `worker-list` 的 liveness 為 `exited`，而 Task 沒有被接受的 `worker_done`、loopctl 也沒匯入結果；(b) transcript 的最後一個 agent turn 沒有送 `worker_done`；(c) `worker-start` exit 1 並附 `failedStage` | skill L608-612：「Leave the wait only on positive proof the agent stopped: `exited` liveness, the worker's own observation of process exit, or a transcript whose final agent turn sent no `worker_done`」；help（worker-start 最後一段） | (b) 需要判斷「turn 已結束」：Orca 正規化後的訊息只有 `id`、`role`、`blocks`、`timestamp`、`source`；參考實作以 Claude 的 `end_turn` 與沒有未回應的 `tool_use` 判定（`observe.py:333-431`） |
| 2. API 或 infra 錯誤 | Orca 不分類 provider 的錯誤。可用的只有：transcript 或 terminal 的錯誤（`worker-read`；Claude 的 native transcript 有結構化的 `api_error` 紀錄，見 §5.3）、`worker-start` 的拒絕碼（`task_not_found`、`task_not_startable`、`inject_rejected`、`runtime_error`，skill L652-664）、Dispatch 的 `lastFailure`／`terminationReason`、Orca CLI 自己的錯誤（例如 `runtime_unavailable`） | 參考實作 `src/` 對 `api error`、`stuck`、`heartbeat`、`no output` 都沒有命中，只分類工具呼叫本身的失敗（`tools/herdr.py:127-168`） | Orca 正規化後的訊息是否保留 `isApiErrorMessage` 與 `system`／`api_error`，沒有查到；若只能比對文字，可靠度未知。Claude Code 遇到 API 錯誤後 session 可能仍是 `live`、停在提示，這時看起來與訊號 1(b)、訊號 3 相同 |
| 3. N 分鐘沒有新輸出 | `worker-read` 的 cursor 之後沒有新訊息，或最後一則訊息的 `timestamp`（毫秒 epoch，實測）早於 now − N；另有 `dispatch.lastHeartbeatAt`（只在 preamble 要求 heartbeat 時有值） | `worker-read` 實測；skill L725-735「A heartbeat proves liveness, never completion」 | skill L614-618：「a null `agentWait` or an unchanged `worker-read` tail is that same absence…Absence never authorizes stop, abandon, retry, or release」。所以這個訊號只能支持「停止派工、交人」，不能單獨支持 `worker-stop`。長時間的工具呼叫（例如整個測試套件）在 tool result 回來前沒有新訊息，N 要大於最長的正常工具執行時間 |
| （補充）停在只有人能回答的提示 | `worker-show` 的 `observation.agentWait`（附 hook、prompt-text 或 title 證據） | help（worker-show）：「A waiting worker is healthy, not failed」 | Orca 視為健康；對無人看守的 loopctl 而言等於需要人。是否算卡住沒有決定（§9 Q3） |

### 5.2 已有的實例

- **Claude worker 把 Orca preamble 當成注入（Orca 1.4.209，2026-09-25）**：`worker-read --dispatch ctx_6f0f35db294f` 的 transcript 顯示，assistant 在 12:01:07 回覆「這段貼上的內容看起來是一段偽裝成『Orca 多代理 IDE 派工指令』的注入式文字」，12:03:18 再拒絕執行 `orca orchestration check`，直到 12:04:10 有人另外下指令才開始工作。這是「turn 結束、沒有交結果、terminal 仍活著」的實例，屬訊號 1(b)；[runtime-probe.md](../../2026-09-25/runtime-probe.md) L16 只記「完成」，沒有記這段。
- **Codex 啟動在 readiness 失敗（同日）**：`agent-update-prompt` 讓第一次 attempt 停在 readiness（runtime-probe.md L24；`worker-list` 該列 `stage.detail: agent_readiness`、`liveness: exited`）。屬訊號 2（infra），而且 `worker-start` 有 exit 1 與 `failedStage` 可以辨識。
- **Codex 在 sandbox 內送不出 `worker_done`（同日）**：`orca orchestration check/send` 回 `runtime_unavailable`（runtime-probe.md L27）。worker 做完了但交不出結果，從外面看是訊號 1。

### 5.3 Feature 1 的實例會怎麼被分類

Feature 1 沒有經 Orca：`dispatch.sh` 以 `claude -p --model claude-opus-5-5 --effort <e> --permission-mode dontAsk --settings … --session-id <uuid> --output-format stream-json` 在背景執行（`loop/dispatch.sh:11-12`），協調者用 `until [ -s exit_code ]; do sleep 30; done` 等待，沒有任何 watchdog。紀錄在 `.delivery/run-decisions/`，不受 git 追蹤（`.gitignore:12`）。以下由委派的唯讀子代理整理，本文抽查了 ledger、`dispatch.sh`、B1 與 4.1 的 stream 與 native transcript。

| 實例 | 實際經過 | 當時可觀察的訊號 | 依 D79 的分類 |
| --- | --- | --- | --- |
| B1 attempt 1（ledger L41） | 16 個 turn 後，API 回 502；Claude 自己重試 10 次後放棄，最後一則是合成的 assistant 訊息「API Error: 502 Upstream service error」，程序結束，沒有 `result.json`。`dispatch.sh:3` 的 `set -e` 讓背景子 shell 在 `claude` 非 0 結束時沒寫 `exit_code`，等待迴圈因此不會觸發；從 22:52:43 到人問「進度」的 23:02:41，約 10 分鐘沒人發現。協調者手寫 `exit=infra:api_502` 後改派 attempt 2 | stream 的 result 事件 `is_error: true`、`terminal_reason: api_error`、`api_error_status: 502`（`subtype` 卻是 `success`）；native transcript 有 10 筆 `system`／`api_error` 紀錄（22:49:41～22:52:07，最後一筆 `retryAttempt: 10`、`maxRetries: 10`），最後一則 assistant 帶 `isApiErrorMessage: true`、`model: <synthetic>`；程序已結束 | 訊號 1（結束卻沒交結果）與訊號 2（API 錯誤）同時成立 |
| 2.1 attempt 1（ledger L9） | 71 秒、14 個 turn 後正常結束，`exit=0`，`result.json` 的 `commits` 為空、`questions` 說「沒有網路」。實際原因是 `dontAsk` 模式拒絕了不在 allow 清單的 `git ls-remote`（stream 有 2 筆 `permission_denied`，`decision_reason_type: mode`）。ledger 記為 infra，並以 infra 重試派 attempt 2 | 正常結束、有結果檔、結果帶阻擋問題 | 三種訊號都不成立：這是「有結果、結果回報阻擋」，走結果匯入後交人。AC-D16 的「不把診斷出的程式／測試缺陷繼續包裝成 infra retry」正好適用：原因是權限清單，不是 infra |
| 4.1 attempt 1（ledger L19-20） | 77.3 分鐘、123 個 turn，最後正常完成並被接受。期間 native transcript 中 user／assistant 紀錄有兩段空白：00:00:31～00:26:44（1,574 秒）與 00:26:44～00:35:19（515 秒），其間有 `system`／`api_error`（`Request timed out.`、`No response from API`，`retryAttempt`／`maxRetries`）。協調者自己的 session 同時也遇到 API 無回應。ledger 沒有記錄這段停滯 | 程序活著、輸出停止成長、有 API 重試紀錄，但沒有結束 | 訊號 2 只有「暫時性重試」，最後自行恢復；訊號 3 的最長空白約 26 分鐘，低於 30 分鐘的預設門檻，所以不會觸發 |

由這三例得到的觀察（事實與推論分開）：

- **事實**：Claude 的 native transcript 以結構化欄位記錄 API 錯誤（`system`／`api_error` 帶 `retryAttempt`、`maxRetries`、`cause`；最終失敗的合成訊息帶 `isApiErrorMessage: true`）。Orca 正規化後的 `worker-read` 訊息是否保留這些欄位，沒有查到（§4）。
- **事實**：自行恢復的重試很常見：3.1 attempt 2 重試 9 次、5.1 attempt 1 重試 10 次後都成功；B1 是同樣 10 次後失敗。所以「出現 API 錯誤」不能直接等於卡住；可區分的是「重試用完、turn 以錯誤結束」。
- **事實**：18 次 Implementer 執行中，健康執行的最長空白是 504 秒（3.1 attempt 1），4.1 的停滯是 1,574 秒（子代理的統計，n=18）。
- **推論**：在 Orca 下，worker 是互動式 agent terminal（`worker-show` 的 `startOptions.mode.mode: terminal`），不是 `claude -p`；API 錯誤後 session 很可能停在提示而不結束（§9 假設 2）。B1 這種情況在 Orca 下會表現為「turn 以錯誤結束、沒有 `worker_done`、liveness 仍是 `live`」，要靠 transcript 判斷，而不是程序結束。
- **推論**：協調者自己也可能同時遇到 API 中斷（4.1 的例子）。D47 不設常駐 watchdog（DUR-08 L132），所以協調 session 離線或卡住時，卡住偵測同樣不會準時。

## 6. 兩個 profile 的 R1

| 項目 | validation／design 原案 | 在 Orca 下 | Claude（`claude`＋`claude-opus-5-5`） | Codex（`codex`＋`gpt-6-astra` xhigh） |
| --- | --- | --- | --- | --- |
| f1 profile 缺 model | unverified | 不變（profile 寫在 `workflow.yaml`） | 同 | 同 |
| f2 未選用的接入故障 | 未選的 Orca、Codex CLI 不影響 | 已選與未選對調：未選的是 Herdr、OpenCode；Codex CLI 是已選 profile 的底層 | — | Codex CLI 不在 PATH → 已選 profile 不可用，應 Blocked |
| f3 native model 讀回 | 由 native 紀錄讀回才算 verified（design §6） | Orca 只有 `launch.requested`／`launch.effective`（Orca 放進啟動的值）；native 讀回要自己找紀錄 | 本機 Claude transcript 的 assistant 紀錄有 `message.model`（本 session 實測：`claude-opus-5-5`） | 本機 Codex rollout 的 `turn_context` 有 `model`（實測：`gpt-6-astra`） |
| effort 讀回 | 讀不到記 `effort_verified=false`，不單獨 Blocked | 同 | Claude transcript 也有 `effort` 欄位（實測），可能可讀回 | `turn_context.effort`（實測：`xhigh`） |
| f4 兩個 profile 同 model | unverified | 不變 | — | — |
| f5 權限負例 | 寫出範圍、`git push`、`gh`、`herdr`、`loopctl decide` 都被拒且資源不變 | `herdr` 換成 `orca`，但 worker 必須能執行 `orca orchestration send`（`worker_done`、heartbeat）與 `check`；所以只能拒絕其他 `orca` 子命令（例如 `worker-start`、`run-use`、`gate-resolve`）。設定沒有 Orca 旗標可傳，只能用 runtime 自己的設定 | 參考實作用 `--settings profiles/implementer.claude-settings.json`（拒絕 `Bash(herdr *)`），經 Orca 啟動時無法帶 `--settings`，除非走 `--terminal` 自訂 argv。Feature 1 的 `loop/settings.template.json` 以 `dontAsk` 加 allow 清單，並整個拒絕 `Bash(orca *)`；照搬會擋掉 `worker_done`。2.1 的例子也顯示 allow 清單的缺口會被誤判成 infra（§5.3） | 2026-09-25 的 sandbox 擋住 Orca IPC（`runtime_unavailable`）：隔離與 `worker_done` 管道互相衝突，1.4.218 未重測 |
| f6 位置核對 | 由 native 紀錄讀回 cwd，再以 git 讀 repo、branch；只有 input accepted 或讀不到 → unverified | Orca 給的是自己解析的工作區（`worker.startOptions.resolvedWorktreeId`），不是 native cwd | transcript 每筆紀錄有 `cwd`、`gitBranch`、`sessionId`（實測） | `session_meta.cwd`、`turn_context.cwd`（實測） |
| 找到 native 紀錄 | Claude 以 uuid、OpenCode 以 `ses_…` | Orca 不提供 native session ID 或 transcript 路徑（§4） | 未知：Orca 啟動的 Claude session 的 uuid 怎麼取得 | 未知：rollout 檔名含 session id，但 Orca 不給 |
| stop 確認 | process-info 確認 | `worker-stop` 的 stop verdict 加 `worker-list` 轉 `exited`；`worker-show` 沒看到 pid | 同 | 同 |
| 接受 preamble 並交 `worker_done` | design §6「讀回 native model 與 marker」 | 新增的必要項：worker 要把 Orca preamble 當成任務並送出 `worker_done` | 2026-09-25 曾被當成注入（§5.2） | 2026-09-25 曾送不出（§5.2） |
| 版本 | receipt 記 Herdr／runtime 版本 | 記 Orca 版本（`status --json`）、agent CLI 版本；Orca 版本變就重跑（D76(5)） | 同 | 同 |
| D24 | R1 不涵蓋 | 不變，屬 2b | — | — |

讀法：model、effort、cwd 在兩個 runtime 的 native 紀錄裡都有，所以 R1 的 f3、f6 在原則上做得到；卡點是「從 Orca 的 Dispatch 找到它對應的 native 紀錄」，以及「在 Orca 不傳權限旗標的情況下，讓 worker 只能呼叫 `orca` 的兩個子命令」。這兩點只有 live probe 能回答。

## 7. 參考實作（`fcefecc`）可沿用的部分

參考實作只作參考（D75）；舊測試、審查與 preflight 紀錄都不算 Feature 2 的證據（roadmap L60）。行數與分類由委派的唯讀子代理讀出，本文抽查了 `writes.py:75-98`、`observe.py:261-282` 與各檔行數。

| 模組 | 行數 | 對應 Feature 2 | 與 transport 無關的部分 | Herdr 專屬、要換掉的部分 |
| --- | ---: | --- | --- | --- |
| `writes.py` | 578 | op 狀態機（含 E-1 `superseded`）、讀回上限、`resolve_operation`、`safety` | 幾乎全部 | `_herdr()` 與 `_op_call`／`_op_readback` 的工具選擇（L75-98）、`KINDS` 名稱（L52-53）、`prepared.session`（L301） |
| `assignments.py` | 528 | assignment 契約、`route`（派工步驟）、result 匯入與去重、native-only 結果 | 匯入與去重（L456-528）、身份差異比對（L392-453）、`tool_result`（L140-165） | plan 的 `herdr_session`（L92-93、108）、`op_spec` 的 argv（L317-335）、`_agent_start` 的 Herdr argv 與 handle（L359-361、373-374、385）、`_free_pane`（L198-208）；`route` 的步驟照 Herdr 的 worktree → agent → prompt 排 |
| `observe.py` | 620（其中約 130 行是 GitHub） | seq、版本水位、讀取失敗預算、`resolve_read`、writer 結束（`settle`） | 大部分；`_claude`／`_opencode` 讀 native 紀錄（L333-431），不依賴 Herdr | `_worker`（L288-301，`herdr agent get`） |
| `budget.py` | 215 | 4h 聯集、角色 timeout、到期 stop | `active_used` 等聯集（L63-111）若仍需要可留 | 依 D79，`deadline`、`timed_out`、`exhausted_units`、`due_stops`（L117-147、205-215）會被卡住偵測取代 |
| `preflight.py` | 440 | R1 判定與 receipt | native 讀回（L83-148）、位置核對（L151-168）、負例機制（L171-182）、判定理由（L335-373） | `HERDR_VERSION`、`herdr` 負例、`RUNTIMES` 的 ctrl+c 停止（L33-48）、`_probe` 的 Herdr 步驟、receipt 的 `herdr_session` |
| `tools/herdr.py` | 227 | transport adapter | 回傳形狀 `{outcome, reason, receipt, facts}` 與 `{result: confirmed\|pending\|absent\|mismatch\|transport_error}` 可沿用 | 全部 argv 與錯誤碼 |
| `tools/__init__.py` | 31 | 有時限的子程序 `run` | 全部 | — |
| `profiles/` | 50＋29 | 權限設定 | Claude 的 allow／deny 清單形狀 | `Bash(herdr *)`；reviewer 是 OpenCode 設定，D76 改為 Codex |
| 測試 | `test_writes` 1,332（28 個）、`test_observe` 183（6）、`test_public_path` 122（2）、`test_preflight` 704（36）、`test_budget` 720（29）、`test_active_time` 71（4）；fake `herdr` 97 行與 scenario JSON | w1～w11、o1～o3、d3、f1～f6、b0～b7 | `Harness`（`test_writes.py:93-281`）與 scenario fake 的做法 | fake 的工具換成 `orca`；b 系列依 E-6 重寫 |

不能直接搬的地方：

- **Store 介面不同**：參考實作以 feature id 為鍵（`store.load(feature)`），main 以 repo＋feature 為鍵並有 `authorize`、`resolves`（`store.py:308-338`）。
- **Plan 格式不同**：參考實作要求 plan 內有 `loopctl-plan` YAML 區塊（`assignments.py:70-112`，含 `workspace.herdr_session`、task 的 `acs[].verify` 與 `scope`）；main 的 `tasks.md` 是 Markdown 表格，沒有這個區塊。
- **依賴不同**：參考實作把 pyyaml 列為執行依賴（`pyproject.toml:6`），main 沒有。
- **`workflow.yaml`**：參考實作有 `budget`、`timeouts`、`limits`、`profiles`（`workflow.yaml:15-30`，`transport: herdr`）；main 只有 `g3`。

## 8. 規模估計

依據：參考實作的模組行數（§7）、main 的現況（`src` 1,715 行、`tests` 3,984 行）、重切研究對 Feature 2 的估計（程式約 2,300～2,500 行、含測試約 5,500 行，[controller-recut.md](../../2026-09-30/controller-recut.md) L41）。以下是推估，不是量測。

| 部分 | 程式（行） | 根據 |
| --- | ---: | --- |
| 外部寫入 registry 與 `resolve_operation` | 500～600 | `writes.py` 578 |
| assignment、result 匯入與去重、native-only 結果、從 `tasks.md` 取 task 與 AC | 500～650 | `assignments.py` 528，加上 Markdown 解析 |
| 觀察、讀取預算、`resolve_read`、writer 結束 | 400～500 | `observe.py` 去掉 GitHub 約 490 |
| Orca adapter（`tools/orca.py`、`tools/__init__.py`） | 250～350 | `herdr.py` 227＋31；Orca 的 JSON 較大 |
| 卡住偵測 | 100～200 | 取代 `budget.py` 的 timeout 部分 |
| preflight（R1 判定與 receipt） | 350～450 | `preflight.py` 440 |
| `next`／`safety`、CLI 子命令、decide 新種類 | 250～350 | 參考實作 `next.py` 110、`cli.py` 比 main 多約 70 行，加上新子命令 |
| **合計** | **約 2,400～2,900** | |
| 測試 | 約 3,600～6,700 | 以參考實作的比例（8,825／6,054 ≈ 1.5 倍）約 3,600～4,300；以 Feature 1 的比例（3,984／1,715 ≈ 2.3 倍）約 5,500～6,700。參考實作對應的測試約 3,100 行（`budget` 改寫後），另加 fake `orca` 與卡住案例 |
| 非程式 | orchestrate skill、`workflow.yaml` 的 profiles 與門檻、兩個 profile 的權限設定、R1 receipt、能力證據矩陣、clear 時機的實驗紀錄 | roadmap L32 |

- 程式約為 Feature 1 的 1.4～1.7 倍，含測試約 1.1～1.7 倍。Feature 1 以 7 個 task、一個 PR 交付（archived tasks.md L44-52、design D14 估 800～1,000 行程式，實際 1,715 行）。
- 是否拆分：D57(2) 要求一個 PR 做得完，太大就在 design 時提議拆。D79 的回答紀錄有「放進 Feature 2，不再拆」（指卡住偵測，decisions.md L91 的依據欄）。如果要拆，依資料相依，較自然的切點是：(a) 外部寫入、Orca 派工、結果匯入與 Claude 的 R1；(b) 卡住偵測、Codex 的 R1、clear 時機的實驗。這只是相依關係的觀察，要不要拆由 design 提議、Project Lead 決定。

## 9. 事實、假設、未知與待決問題

### 事實

1. Feature 2 首先驗證 19 條 AC，F2 結束時能完成 7 條（§2.1）。
2. Feature 1 的 `next` 在核准後回 `dispatch`，`safety`、`blocked` 永遠是 null；`decide` 不收 `resolve_read`、`resolve_operation`；產品程式零依賴、不讀 YAML（§3）。
3. Orca 1.4.218：`worker-start` 沒有權限旗標；`--terminal` 不能帶 `--model`／`--effort`；沒有 native session ID 欄位；`request-show` 的 `absent` 不證明沒發生；absence（含 tail 不變）不授權 stop（§4、§5）。
4. 本機沒有名為 `engineer`、`reviewer` 的 Orca 工作區，loop-engineering 也沒有註冊成 Orca repo（`repo list`、`worktree list`）。
5. Orca 兩天內從 1.4.215 升到 1.4.218，自動更新開啟；環境變數裡的版本會落後實際版本。
6. 本機 Claude transcript 與 Codex rollout 都含 model、effort、cwd（§6）。
7. 2026-09-25 的 Orca 實測中，Claude worker 曾把 preamble 當注入拒絕；Codex 曾卡在 readiness、在 sandbox 內送不出 `worker_done`（§5.2）。
8. 參考實作的 Herdr 綁定集中在 `tools/herdr.py` 與少數 argv、handle 欄位；它沒有任何卡住或 API 錯誤的分類（§7）。
9. Feature 1 的 B1（502）約 10 分鐘沒人發現，原因是 `dispatch.sh:3` 的 `set -e` 讓失敗時不寫 `exit_code`；Claude 的 native transcript 有結構化的 API 錯誤紀錄；自行恢復的 API 重試在 Feature 1 出現過至少兩次（§5.3）。

### 假設（未驗證）

1. Orca 1.4.218 啟動的 Claude、Codex worker 寫出的 native 紀錄格式，與本機互動 session 的格式相同。
2. Claude Code 遇到 API 錯誤時，session 不會自己結束，而是停在提示；所以 API 錯誤在 Orca 下常表現為「turn 結束沒有 `worker_done`、liveness 仍是 `live`」。
3. 30 分鐘的預設門檻大於正常工具呼叫（例如完整測試套件）的最長時間。Feature 1 的 18 次執行支持這點（健康執行最長空白 504 秒），但樣本小，而且只有一個 repo。
4. 依 D79 的文字，「停止派工並交人」不要求 loopctl 對 worker 發 `worker-stop`；發不發 stop 由 spec 決定。

### 未知（需要 live probe 或決定）

1. 從 Orca Dispatch 找到對應 native 紀錄（Claude uuid、Codex rollout）的可靠方法。
2. 在 Orca 下怎麼承載權限設定，才能拒絕寫出範圍、`git push`、`gh`、其他 `orca` 子命令、`loopctl decide`，同時允許 `orca orchestration send`／`check`。
3. 1.4.218 的 Codex sandbox 內能否呼叫 Orca IPC。
4. Claude worker 現在是否接受 Orca preamble。
5. `projection.stage.activity` 的取值、`agentWait` 的觸發條件、stop verdict 的內容。
6. Orca 的 `worker-read` 是否保留 Claude 的結構化 API 錯誤欄位；若只能比對文字，辨識的可靠度。
7. Orca receipt 的保留期限。
8. DUR-09 與 project-intent 的「Orca 選配」和 D76 的 Orca transport 怎麼在 spec 中並存（§2.2）。
9. D79 後 `budget_extension` 的 `active`、`ci_wait` 目標怎麼處理（§2.1 D25 列）。

### 給 Project Lead 的範圍問題

**Q1：Feature 2 是否包含 orchestrate skill 檔本身？**
- 選項：(a) 包含完整的 `skills/orchestrate/SKILL.md`：從交接包叫 `spec-to-plan`、登記 design 與 plan、停在 ◆確認開工，核准後只依 `next` 派工，並附 O16 的文件清單；(b) 只包含派工迴圈這一段，交接包到 ◆ 仍由人照 `spec-to-plan` 做；(c) Feature 2 只交付 loopctl，skill 延到 Feature 3。
- 證據：roadmap L27「orchestrate skill 在 Feature 2 建立」、L32 的可見行為從交接包開始；roadmap L70 把 O16 的文件清單歸 Feature 2；`skills/` 目前沒有 `orchestrate`；高層設計 T4.1（`tasks.md` L86）。
- 建議：(a)。roadmap 已把起點寫成交接包，O16 也要它。

**Q2：engineer 工作區 clear 時機的實驗算不算 Feature 2 的驗收條件？**
- 選項：(a) 算：兩種模式都要跑過，並記錄壓縮次數與 finding 數；(b) Feature 2 只交付兩種模式（每次新 terminal、`--terminal` 重用），實驗在 Feature 3 的真實 task 上跑，結果記在 Feature 3；(c) 實驗由人在 Feature 2 開發期間用 Orca 手動做，不算驗收。
- 證據：D76(6)「由 Feature 2 各用一半實驗」；Feature 2 自己的 task 無法用 Feature 2 尚未完成的派工來跑；Orca 的重用（`--terminal`）不能帶 `--model`／`--effort`，和 D69(4) 的「effort 依 task」衝突（§4）。Feature 1 的 18 次 Implementer 執行都是每次新 session，0 次 context 壓縮，context 峰值 93k～314k（上限 1M）；壓縮只發生在整個 Feature 共用一個 session 的協調者（峰值約 901k）。所以「壓縮次數」這個指標只有在重用模式下才可能出現差異。
- 建議：(b)，並在 spec 註明重用模式下 effort 固定。

**Q3：卡住的門檻與動作。**
- 選項：(a) 預設 30 分鐘；三種訊號都只「停止派工、保存證據、交人」，不對 worker 發 stop，`agentWait` 也算卡住；(b) 同 (a)，但訊號 1、2 有正面證據時自動 `worker-stop` 並讀回確認；(c) 門檻依 effort 不同（xhigh 較長）。
- 證據：D79(1) 預設 30 分鐘、「停止與讀回仍照 DUR-08 的有界規則」；E-6 L48 寫「停止派工」；Orca skill L614-618「Absence never authorizes stop」；`agentWait` 在 Orca 是「healthy, not failed」。Feature 1 的資料（n=18）：健康執行最長空白 504 秒，4.1 的停滯 1,574 秒後自行恢復；API 重試自行恢復至少兩次（§5.3）。
- 建議：(a)，並把訊號 2 定為「重試用完、turn 以 API 錯誤結束」，不把單次重試算成卡住。它與 Orca 的安全底線一致，也最小。

**Q4：Codex reviewer profile 的 R1 放在 Feature 2 還是 Feature 4？**
- 選項：(a) 照 roadmap，Feature 2 兩個 profile 都跑完整 R1；(b) Feature 2 只跑 Claude 的完整 R1，Codex 的 R1 移到 Feature 4（Reviewer 第一次被派時）；(c) Feature 2 跑 Codex 的 model、effort、位置讀回，權限負例（不能寫作者 branch）留到 Feature 4。
- 證據：roadmap L32、D79(3) 都寫兩個 profile 各跑 R1；Reviewer 派工在 Feature 4（roadmap L34）；Codex 的 sandbox 與 Orca IPC 衝突（§5.2、§6）可能讓 Codex R1 在 Feature 2 就 Blocked；G11、G12 在 F2 只成立 R1 部分（§2.1）。
- 建議：(a)。及早暴露 Codex 的風險；若 R1 unverified，Feature 2 仍可交付 Claude 這條路徑，矩陣如實標記。

**Q5：`engineer`／`reviewer` 工作區與 Orca repo 由誰建立？**
- 選項：(a) 人一次性建立（註冊 repo、建立具名工作區），loopctl 的 preflight 只核對存在與位置；(b) loopctl 以外部寫入 `worktree_create` 經 Orca 建立，先登記再讀回；(c) orchestrate skill 呼叫 Orca 建立，loopctl 不登記。
- 證據：本機 `orca repo list` 只有 `cross-node-xfer`，`worktree list` 沒有 `engineer`、`reviewer`；高層設計 §4 的外部寫入種類含 `worktree_create`；D76(1) 只說「送進兩個固定名稱的 Orca 工作區」；(c) 不符合 DUR-06「派工與外部寫入先登記」。
- 建議：(a)。工作區是固定名稱、跨 Feature 重用，不必每個 run 建立。
