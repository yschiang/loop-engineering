# Spec 審查第 2 輪（Claude Fable 5.1 xhigh，同一 session）

- 受審版本：`f50b534`（相對第 1 輪的 `79bdb45`）。時間：2026-10-03T03:10:47Z ～ 2026-10-03T03:15:17Z。
- 提問：見 [spec-review-2-prompt.md](spec-review-2-prompt.md)。
- 結果：`changes_required`。第 1 輪 18 條中 17 條 resolved、S-13 partly；新增 S-19～S-25，其中 S-19、S-21 為 blocking。

## 處理

| Finding | 處理 |
| --- | --- |
| S-19 | ORC-01：只有 `preflight` 能派出、讀回、停止探測 worker；`preflight`、`status`、`next` 都能以固定命令讀 transport 與 agent CLI 的版本。DUR-09 的版本一律寫「transport（Orca）與 agent CLI」 |
| S-20 | 用詞統一：transport 指 Orca，runtime 指 agent CLI（Claude Code、Codex CLI） |
| S-21 | preflight 以一個 run 為脈絡，依該 run 的政策核准判定；receipt 綁定該 run 已核准的 digest，存在 run 狀態之外，可被已核准同一 digest 的 run 採用；AC-D30 的 WHEN 加上 run |
| S-22 | AC-G24 的目標是 Implementer 探測工作區的檔案與 branch；「被拒」與資源檢查依 AC-D27 |
| S-23 | 派出探測 worker 前先持久記錄 marker 與 handle；殘留的清理不受政策核准影響（DUR-09、AC-D30、AC-D31） |
| S-24 | AC-D29 只有 Implementer 的 verified 讓 `next` 派工；Reviewer 加不同模型的核對；矩陣補「載入的設定」「兩個角色不同模型」 |
| S-25 | preflight 不需要協調權、不寫 feature 狀態；receipt 帶自身內容的 digest，不符就不適用 |

## 審查原文

第 2 輪完成。我讀了 `f50b534` 的 proposal、三份 spec delta（含新增的 `delivery-orchestration`）、審查紀錄的「處理」一節與 `git diff 79bdb45 f50b534`，並對照現行 `openspec/specs/`、Feature 1 的 archived design 與決策。

## 第 1 輪 finding 核對

| ID | 狀態 | 證據 |
| --- | --- | --- |
| S-1 | resolved | durable-delivery L39-41 AC-D29：WHEN 各項成立，THEN verdict `verified`、receipt 含全部欄位、`status` 與 `next` 的結果 |
| S-2 | resolved | L28「停止 SHALL 以 process-info 確認…liveness、停止回應或 terminal 已關閉，SHALL NOT 單獨作為證據」；AC-D19 L48「停止後 process-info 仍顯示探測 agent」；proposal L101 待決 1 改寫 |
| S-3 | resolved | AC-D27 L15 定義「被拒」：native 紀錄顯示嘗試、被 runtime 權限或 sandbox 拒絕而未執行、資源未變；未嘗試、自述、loopctl 自己的核對都不算；proposal L19 同 |
| S-4 | resolved | L25「native 紀錄 SHALL 恰好有一份含這個 marker…取自 marker 所在的 turn…SHALL NOT 以…時間先後或相同目錄推定」；AC-D18 L44-45；proposal L18 |
| S-5 | resolved（但引出 S-19） | delivery-orchestration L5 MODIFIED ORC-01，三條既有 scenario AC-O01、O19、O30 原樣保留；proposal L26、L39 |
| S-6 | resolved（但引出 S-21） | L23 政策未核准拒跑；L37 `next` 回報需要 `policy_change`；AC-D30 L67-69 |
| S-7 | resolved | L35「以最新的一份為準，較新的 `unverified` 取代較早的 `verified`…綁定目前已核准的 digest…版本等於目前值才適用」；AC-D26 L60 |
| S-8 | resolved（Project Lead 決定） | proposal L45-56：Implementer 必須 `verified`，Reviewer 如實；逐 AC 的驗法表 |
| S-9 | resolved | proposal L76-87 表；spec L21「接入工具的名稱 SHALL NOT 被當成已有可派工的能力」、L27 認證可用、L31 研究報告、L33 未清理的 runtime 紀錄、AC-D22 L53 |
| S-10 | resolved | proposal L16「探測時的 effort…逐 task 的 effort…在 Feature 2」、L18；spec L25「effort 是探測時要求的值，位置和探測工作區比對」 |
| S-11 | resolved | AC-D27 L14「profile 允許清單以外的 `orca` 子命令（至少一個會改變 Orca 狀態的子命令）」；proposal L16 |
| S-12 | resolved | L29 profile 的保留與排除清單（Claude、Codex 各自詞彙）；L33 receipt 加權限模式、執行模式、權限設定來源、送達方式；AC-D28 L65 |
| S-13 | partly | AC-D19 L48 加了「探測工作區、runtime 的 repo 註冊不存在」；AC-G24 L12 改成「代表作者的 branch 與 worktree」，但誰指定這個目標仍沒寫，見 S-22 |
| S-14 | resolved（見 S-23 的補充） | AC-D31 L71-73；L33「中斷的 preflight SHALL NOT 產生 `verified`」；proposal L23 |
| S-15 | resolved | L37「回報 `preflight` 動作，附 profile 與原因」；AC-D26 L61；AC-D19 L49「preflight 的輸出與 `status` 顯示具體 Blocked」 |
| S-16 | resolved | GAT-08 L17 每格記證據類型與 verdict、最小能力列；L33 receipt 保存遮蔽後的摘錄與 digest；proposal L23、L28 |
| S-17 | resolved | AC-D27 L15「沒有新的 Orca 物件或 `gh` 寫入」，觀察法留給 design |
| S-18 | resolved | L21 不再有 model ID；L25「再讀出該目錄的 repo 與 branch」；proposal L17 無 `--role`；AC-D23 保留一條，理由可接受 |

## 新的 finding

**S-19 · blocking · delivery-orchestration L5；durable-delivery L33、L35、L37、AC-D26 L60；proposal L23-26**
- 問題：版本的規則有兩處新矛盾。(a) ORC-01 的例外把「讀取版本」綁在 `preflight`，proposal L26 也寫「只有 `preflight` 可以…並讀版本」；但 L35「版本等於目前值」、L37 的派工管制與 AC-D26「版本和目前不同」都要 `next` 知道目前版本，`status` L37 也要顯示版本。spec 沒有說 `next` 從哪裡取得「目前值」；照 ORC-01 的寫法它不能自己讀，照 AC-D26 它又必須比對。(b) L21 把 transport 與 runtime 分欄，Orca 是 transport、Claude Code 與 Codex CLI 是 runtime；L33、L35、L60 卻寫「runtime 與 agent CLI 的版本」。照 L21 的詞彙，這句話等於「agent CLI 與 agent CLI」，Orca 的版本從 spec 本文消失，與 D76(5)、D81(2) 及 proposal L23-24「Orca 與 agent CLI 的版本」不符。
- 證據：delivery-orchestration L5「只有一個例外：`preflight` 可以…並讀取 runtime 與 agent CLI 的版本」；durable-delivery L21「transport、runtime、provider、model 與 effort SHALL 分欄保存」；L35「runtime 與 agent CLI 的版本等於目前值時才適用（D76(5)、D81）」；D81(2)「每次派工前比對 Orca 與 agent CLI（Claude Code、Codex CLI）的版本和 R1 receipt」。
- 建議：ORC-01 的例外改成「`preflight`、`status` 與 `next` 可以以固定命令讀取 transport 與 agent CLI 的版本；只有 `preflight` 可以派出、讀回、停止探測 worker」；DUR-09 把「runtime 與 agent CLI 的版本」全部改成「transport（Orca）與 agent CLI 的版本」。

**S-20 · non-blocking · durable-delivery L23、L27、L28、L48；delivery-orchestration L5**
- 問題：去掉 Orca 專名後，「runtime」一詞兩個意思混用。L23「經所選 runtime 派一個探測 worker」、L27「以 runtime 的回報管道交出完成（Orca 為 `worker_done`）」、L28「runtime 的 liveness、停止回應」、L48「runtime 的 repo 註冊」都指 Orca；L7、L15「被 runtime 的權限或 sandbox 拒絕」、L25「runtime 的啟動參數」、L27「runtime 的認證可用」、L49「未核准的 runtime 或 model」都指 Claude Code 或 Codex。
- 建議：指 Orca 的地方一律用「transport」，指 agent CLI 的地方用「runtime」，與 L21 的分欄一致。

**S-21 · blocking · durable-delivery L23、L33、L35；AC-D30 L67-69**
- 問題：「政策已核准」在現行產品裡是 run 範圍的事實，preflight 與 receipt 卻是 profile 範圍。AC-D30 的 WHEN「`workflow.yaml` 沒有綁定目前 digest 的人工 `policy_change`，有人執行 preflight」沒有說是哪個 run 的 `policy_change`；L33「已核准 `workflow.yaml` 的 digest」、L35「綁定目前已核准的 digest」同樣沒有脈絡。兩個 run 可以核准不同 digest，receipt 在哪些 run 適用、preflight 要不要指定 run、沒有任何 run 時能不能跑，都沒定，AC-D30 的前置無法建立。
- 證據：Feature 1 archived design L127「`policy_approval`…`policy_change`」是 run 狀態的欄位；L337「`policy_change`：已登記 policy…`policy_approval = {decision, locator, digest}`」；L375-381 `policy.status` 在每個 run 讀取時計算；現行 AC-G22（`openspec/specs/delivery-gates/spec.md` L19-20）以 `status` 顯示該 run 的核准狀態。
- 建議：寫明「preflight 以一個 run（repo＋feature）為脈絡，依該 run 的 `policy_approval` 判定政策是否核准；receipt 綁定該 digest；任一 run 的 `next` 只採用 digest 等於該 run 已核准 digest 的 receipt」。AC-D30 的 WHEN 加上 run。

**S-22 · non-blocking · delivery-gates AC-G24 L12；proposal 待決 7 L107**
- 問題：「代表作者的 branch 與 worktree」仍沒有說由誰指定。負例要可重現，目標必須是政策或 preflight 固定的對象。另外 AC-G24 沒說「做得到」的判準沿用 AC-D27 的「被拒」定義。
- 建議：寫明目標是 Implementer profile 的探測工作區與它的 branch，或由政策檔宣告；加一句「拒絕與資源檢查依 AC-D27」。

**S-23 · non-blocking · AC-D31 L71-73；L23、AC-D30 L69；proposal 待決 1 L101**
- 問題：AC-D31 要「下一次 preflight 先找出殘留的探測 worker」，但 spec 沒有要求派出前先持久記錄 marker 與 handle。待決 1 預設自訂 terminal，verification L22 說這種 terminal 的 `worker-stop` 回 `stop_unknown`，Orca 不一定列得出它，沒有自己的紀錄就找不到。另外 AC-D30 讓政策未核准時 preflight 直接拒跑，這時殘留的 worker 不會被清理。
- 建議：DUR-09 加「派出探測 worker 之前 SHALL 先持久記錄 marker 與 handle」；AC-D31 的清理不受政策核准狀態影響，或在 AC-D30 的 THEN 寫明仍先處理殘留。

**S-24 · non-blocking · AC-D29 L41；L26；GAT-08 L17**
- 問題：AC-D29 的 THEN「已核准的 run 的 `next` 回報可以派工」只對 Implementer 成立，L37 只看 Implementer 的 receipt；套到 Reviewer 的 verified 會讀成也能派工。L25-29 的逐項判定沒有「兩個 profile 的 model 不同」這一項，proposal L22 與 AC-G23 有。GAT-08 的最小能力列沒有「載入的設定」與「不同模型」。
- 建議：AC-D29 的 THEN 改成「若該 profile 是 Implementer，已核准的 run 的 `next` 回報可以派工」；L26 加「Reviewer 另做 GAT-05 的隔離負例與不同模型核對」；矩陣列補兩項。

**S-25 · non-blocking · delivery-orchestration L5；durable-delivery L33-37**
- 問題：ORC-01 說「可執行的動作 SHALL 只依協調權（claim token）與人工 decision 判定」，preflight 兩者都不需要，spec 沒說它要不要協調權。receipt 會決定 `next` 能不能派工，但它不是 run 狀態，DUR-01 的手改偵測不涵蓋。
- 建議：加一句「preflight 不需要協調權，不寫 feature 狀態；receipt 不是 run 狀態，手改不在偵測範圍（D48）」，或要求 receipt 帶自身 digest 並由 `next` 核對。

VERDICT: changes_required
