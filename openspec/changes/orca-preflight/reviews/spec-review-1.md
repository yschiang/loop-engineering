# Spec 審查第 1 輪（Claude Fable 5.1 xhigh）

- 審查者：`claude-opus-5-5` 以外的模型 `claude-fable-5-1`，effort xhigh，全新 session（`6d1ce8c4-53ae-4023-9400-401dfefa93e2`），唯讀設定，全新 clone。
- 受審版本：`79bdb45`。時間：2026-10-03T02:55:49Z ～ 2026-10-03T03:06:44Z。
- 提問：見 [spec-review-1-prompt.md](spec-review-1-prompt.md)。
- 結果：`changes_required`（8 條 blocking、10 條 non-blocking）。

## 處理

| Finding | 處理 |
| --- | --- |
| S-1 | 新增 AC-D29（探測全部成立的主流程） |
| S-2 | DUR-09 的停止改以 process-info 確認，liveness、停止回應、terminal 已關閉不單獨作證據；AC-D19 加「停止後 process-info 仍顯示探測 agent」；proposal 待決 1 改寫 |
| S-3 | AC-D27 定義「被拒」：native 紀錄顯示嘗試、被 runtime 權限或 sandbox 擋下、資源未變；未嘗試、自述、loopctl 自己的拒絕都不算 |
| S-4 | DUR-09 加 marker：恰好一份 native 紀錄含 marker，讀回值取自該 turn；不以時間先後或相同目錄推定；AC-D18 涵蓋 |
| S-5 | 新增 MODIFIED ORC-01：只有 `preflight` 能以固定命令經 runtime 派出、讀回、停止探測 worker並讀版本 |
| S-6 | 新增 AC-D30：政策未核准時 preflight 拒跑、`next` 回報需要 `policy_change` |
| S-7 | DUR-09 加「適用的 receipt」：以最新一份為準，綁定已核准 digest 與目前版本才適用；AC-D26 涵蓋 |
| S-8 | Project Lead 決定：Implementer 必須 `verified`，Reviewer 結果如實、缺口在 Feature 4 前解決；proposal 加「驗收條件」與逐 AC 的驗法 |
| S-9 | proposal 加「需求原文沒有帶入的句子」；認證可用性以探測 worker 有 native turn 為證；研究報告不作成功證據寫入 AC-D19；未清理的 runtime 紀錄不自動進 Git 寫入 DUR-09 |
| S-10 | 位置和探測工作區比對；profile 的 effort 是探測時的值，逐 task effort 屬 Feature 2 |
| S-11 | profile 列允許的 `orca` 子命令；負例至少一個會改變 Orca 狀態的子命令 |
| S-12 | profile 列保留與排除的設定來源（Claude、Codex 各自的詞彙）；receipt 加實際權限模式、執行模式、權限設定來源、任務送達方式 |
| S-13 | AC-D19 加「探測工作區或 repo 註冊不存在」；AC-G24 的目標改為「代表作者的 branch 與 worktree」 |
| S-14 | 新增 AC-D31（中斷不產生 verified；下次先停殘留的探測 worker） |
| S-15 | `next` 回報 `preflight` 動作；Blocked 出現在 preflight 輸出與 `status` |
| S-16 | 矩陣每格記證據類型與 verdict，列出最小能力列；receipt 保存遮蔽後的 native 摘錄與 digest |
| S-17 | AC-D27 的資源檢查改寫成可在真實環境觀察的結果（沒有新的 Orca 物件或 `gh` 寫入）；觀察方法由 design 定 |
| S-18 | model ID 移出 spec，只留在 proposal 與 `workflow.yaml`；AC-D23 依需求原文保留為一條（原文本來就含兩種情況） |

## 審查原文

審查完成。我讀了受審的三份文件、需求輸入（DUR-02、DUR-09、GAT-05、GAT-08 與 AC）、E-5、validation 的 M-PRE 與 R1、design §6、現行 `openspec/specs/`、Feature 1 的 archive、決策 D38–D79，並從 `origin/docs/split-orca-preflight` 讀了 D80、D81 與 roadmap 的 2a 列，以及研究與驗證報告。部分 shell 指令被環境拒絕，但不影響以上覆蓋。

先說結論：**AC ID 沒有衝突，MODIFIED DUR-02 完整保留了 Feature 1 的內容，G11／G12 改用新 ID 符合 Feature 1 先例。** 問題集中在三處：沒有正向主流程的 scenario；「確認停止」「被拒」「native 紀錄對應」三個判準沒寫，真實 R1 無法判定；`next` 的派工管制漏了「政策未核准」與「多份 receipt」的規則，並與現行 ORC-01 衝突。

## Findings

**S-1 · blocking · `specs/durable-delivery/spec.md` DUR-09 的 scenario 全體**
- 問題：七條 scenario 的 THEN 都是 `unverified`、`none` 或不派工，沒有一條描述「各項都成立 → `verified`」的主流程。驗收清單無法勾「verified 路徑」，而且 receipt 在 verified 時必含哪些內容沒有 scenario 約束。
- 證據：AC-D18、D19、D22、D23、D27、D28 的 THEN（L29、L33、L37、L41、L15、L49）都是負向；只有 AC-D26 L45 結尾「重新執行 preflight 得到 `verified` 之後，`next` 才回報可以派工」帶到正向。validation f5(a) L226「(a) 全部被拒且資源未變、stop 經確認 → `verified`」是輸入裡的正向案例。`skills/feature-to-spec/SKILL.md` L68 要求「the main flow and each exception have a scenario」。
- 建議：加一條主流程 scenario（例如 AC-D29）：WHEN 兩個 profile 的探測各項都成立；THEN receipt 的 verdict 為 `verified`，含 L23 列的全部欄位，`status` 顯示 verified 與版本，已核准的 run 的 `next` 回報派工。

**S-2 · blocking · `durable-delivery/spec.md` L23「確認停止」、AC-D19 L32「停止無法確認」；proposal L22、L74**
- 問題：spec 沒有說「停止有確認」以什麼為準。輸入裡唯一的判準是 AC-D04 的規則，2a 把它默默拿掉，連「runtime 的 idle／done 狀態不能單獨作證據」這句也沒帶入。待決 1 預設走自訂 terminal，而驗證報告說這條路 `worker-stop` 回 `stop_unknown`，所以沒有判準時這一項在真實 R1 無法判定。
- 證據：需求輸入 durable-delivery L44-48「確認停止或 idle SHALL 以可核對的權威證據判定…stop 已經過 process-info 確認…terminal idle、runtime 的 idle／done 狀態，SHALL NOT 單獨作為 writer 已結束的證據」。validation R1 L258「stop 經 process-info 確認」；f5(d) L226「stop 後 process-info 仍顯示 agent → `unverified`」在 2a 沒有對應 scenario。verification L44「`worker-stop` 之後的 `exited`（`source: worker_stop`）只是重述 Orca 自己的紀錄…自訂 terminal 會是 `stop_unknown`」。proposal L74「要由 loopctl 關掉 terminal 作為停止證據」把「關掉終端」當證據，與輸入的 process-info 規則不同。
- 建議：在 DUR-09 加一句「停止 SHALL 以 process-info 確認該 agent 程序已不存在；Orca 的 liveness、stop verdict 或 terminal 已關閉 SHALL NOT 單獨作為證據」，並補 f5(d) 的 scenario。

**S-3 · blocking · AC-D27 L13-15、AC-G24 L11-13、DUR-02 L7**
- 問題：「觀察到被拒」沒有定義觀察來源與拒絕的層級。至少四種情況會被混為「被拒」：runtime 權限拒絕執行；worker 自述被拒；worker 根本沒嘗試；命令有執行、由 loopctl 因 actor 或 token 拒絕。只有第一種符合 DUR-02「由 runtime 的權限設定拒絕」。`loopctl decide` 這一項尤其危險：AC-O19 本來就會拒絕非 human 的 actor，沒有任何 runtime deny 也會「被拒」且 revision 不變。
- 證據：DUR-02 L7「並由 runtime 的權限設定拒絕呼叫狀態寫入命令」；需求輸入 delivery-gates L38「worker 的自述只作說明」；verification L88「Native 紀錄也帶權限狀態：Claude 的 `permissionMode`，Codex 的 `sandbox_policy`…可以直接讀實際生效的權限」；verification L50 的 2026-09-25 實例是 worker 自己「拒絕執行」，不是權限拒絕。
- 建議：定義「被拒」為「native 紀錄顯示 worker 嘗試了該命令，且該命令被 runtime 的權限或 sandbox 拒絕、沒有執行」；worker 未嘗試、自述、或 loopctl 自己的拒絕都算該項不成立。`loopctl decide` 的負例要求 runtime 層拒絕，不以 loopctl 的 actor 檢查代替。

**S-4 · blocking · DUR-09 L23「由 native 紀錄讀回」、AC-D18 L27-29**
- 問題：spec 沒有要求 native 紀錄必須能對應到本次探測的 Dispatch。Orca 不給 native session ID，若 design 用「最近一個 session」或「同目錄的 session」就能滿足字面，卻可能讀到使用者自己的互動 session。L23 的 SHALL NOT 清單也沒排除這兩種推定。輸入裡的 marker 要求被拿掉了。
- 證據：design §6 L177「讀回 native model 與 marker」；validation R1 L258「model 與 marker 讀回一致」；2a L23 只寫「native session ID、讀回的值」。verification L40「Claude 的 `worker-read` 訊息 id 等於 native 紀錄的 uuid…Orca 注入的 preamble 帶 Task 與 Dispatch ID，會出現在兩種 runtime 的 native 第一則 prompt」；L89「Claude 每筆紀錄的 `cwd` 會跟著 agent 的 `cd` 變…要讀派工第一則或 marker 那則紀錄的 cwd」。
- 建議：加入「native 紀錄 SHALL 含本次探測的 marker（Orca Task／Dispatch ID 或 loopctl 自帶的 nonce）；model、effort、工作目錄取自 marker 所在 turn；找不到或多於一份候選 → `unverified`」，並把「時間順序、目錄相同」加進 SHALL NOT 推定的清單。

**S-5 · blocking · proposal L44-47「Modified Capabilities」；DUR-09 L23、L25**
- 問題：現行 ORC-01 規定 controller「SHALL NOT 常駐、啟動 agents 或執行呼叫者提供的命令」，而 2a 讓 `loopctl preflight` 經 Orca 派探測 worker，`next` 還要讀 Orca 與 agent CLI 的目前版本。2a 沒有 MODIFIED ORC-01，archive 後 `openspec/specs/` 會自相矛盾。
- 證據：`openspec/specs/delivery-orchestration/spec.md` L10；2a L23「經 Orca 派一個探測 worker」；AC-D26 L44「Orca 版本或 agent CLI 版本和目前不同」。verification L108「ORC-01 的產品 spec 寫 controller『SHALL NOT 常駐、啟動 agents…』，F1 的 design 也寫『不開子程序』…F2 要在 MODIFIED ORC-01 說清楚 loopctl 能執行什麼」。
- 建議：加 MODIFIED ORC-01，寫明 loopctl 可以依政策檔以固定 argv 執行哪些外部命令（探測 worker 的派出、讀回、停止，以及版本讀取），仍不常駐、不執行呼叫者提供的命令；proposal 的 Modified Capabilities 補上 `delivery-orchestration`。

**S-6 · blocking · AC-D26 L43-45、DUR-09 L25；proposal L31-33**
- 問題：roadmap 的 2a 列明寫「政策沒核准」也不給派工，spec 只寫 digest「和目前不同」，沒有「沒有核准的 digest」這個情況。也沒有 scenario 說政策未核准或 digest 不符時 preflight 能不能跑、receipt 綁什麼 digest。
- 證據：roadmap（PR 分支）2a 列「profile 沒驗證過、政策沒核准或 Orca 版本變了，`next` 就不給派工」；AC-D26 L44 只有「receipt 對應的政策 digest…和目前不同」；verification L107「`next` 不看政策：`workflow.yaml` 沒登記、沒核准或 digest 不符時，`next` 仍回 `dispatch`」；現行 AC-G22（`openspec/specs/delivery-gates/spec.md` L18-20）只讓 `status` 顯示未核准。
- 建議：AC-D26 的 WHEN 加「或 `workflow.yaml` 沒有綁定目前 digest 的 `policy_change`」；另加 scenario：政策未核准時執行 preflight，receipt 記錄綁定的 digest 並標示未核准，`next` 仍不派工並列出原因；或明定 preflight 拒跑。

**S-7 · blocking · AC-D26 L44「沒有 `verified` receipt」、DUR-09 L23「profile 與 `workflow.yaml` 的 digest」**
- 問題：同一 profile 有多份 receipt 時以哪一份為準沒寫。字面上「有一份 verified receipt」被舊的 verified 滿足，即使之後有一份較新的 `unverified`。另外 receipt 同時記 profile digest 與 `workflow.yaml` digest，AC-D26 只說「政策 digest」，另一個 profile 改了要不要重跑這個 profile 不明。
- 證據：L23 與 L44 的用字如上；proposal L32「profile 沒有對應目前政策 digest 的 verified receipt」同樣沒有新舊規則。
- 建議：加規則「每個 profile 以最新一份 receipt 為準；較新的 `unverified` 取代較早的 `verified`；只有 digest 與版本都等於目前值的 receipt 才適用」，並指定適用的 digest 是「已核准的 `workflow.yaml` digest」。

**S-8 · blocking · proposal L36、L49；GAT-08 L17**
- 問題：「兩個 profile 的真實 R1 各跑一次，receipt 存進 repo，作為驗收證據」沒有說驗收條件：兩個都要 `verified` 才算完成，還是 receipt 存在、verdict 如實就算？研究已預告 Codex 很可能 unverified。也沒有說十條 AC 裡哪些只靠 CI 的 fake 驗、哪些要真實 receipt，CI 上沒有 Orca。
- 證據：D80(3)「2a 的實測先回答派工 spec 需要的事實」；research L316「若 R1 unverified，Feature 2 仍可交付 Claude 這條路徑，矩陣如實標記」；verification L111「ubuntu runner 上沒有 Orca；所有 pytest 都要用 fake `orca`，真實 R1 只能是另外產生的 receipt」；validation §1.5 L36、L46 把 M-PRE 與 R1 分成 ENV-F 與 ENV-R。
- 建議：在 proposal 寫明驗收條件，建議：兩個 profile 都有真實 receipt、verdict 如實；Implementer 必須 `verified`（Feature 2 依賴它），Reviewer 可以 `unverified` 但缺口要寫進矩陣。逐 AC 標「fake 可驗」或「需真實 receipt」。

**S-9 · non-blocking · 忠實度：默默拿掉或改寫的句子**
- 問題：以下句子既沒帶入，proposal 的「不做」或「和 roadmap 不同的地方」也沒寫，也沒有引決策：
  - DUR-09 L146「OpenCode SHALL 仍是預設 runtime（D38）」：2a L21 改寫成「從核准的接法中選用」，D81 只重新解讀「選配」，沒拿掉「預設」。
  - DUR-09「不引入另一套外層 orchestrator」：D76(3)(4) 已處理 loopctl 與 Orca 的分工，但 2a 沒帶、沒引。
  - DUR-09「使啟動／resume、派工、結果回收與工作區管理不依賴這些選配程式」與「選配入口的產品名稱不代表已提供可派工 API」。
  - DUR-09「派工前 SHALL 核對…認證可用性」：preflight 的核對項目沒有認證可用性。
  - DUR-09「未清理 runtime logs SHALL 不…自動進 Git」：2a L23 只保留 credentials 與 dispatch capabilities。
  - DUR-02 L32「實際 worktree SHALL 只有一個有效 writer」「對可核對的身份、版本、digest…不符保存證據並 Blocked」「Timeout、lease 到期…不等於舊 worker 已停止」。
  - AC-D19 L154「不把研究報告當成成功實證」；AC-D22 L167「不能藉替換 runtime 自動放寬獨立 Codex review 政策」。
- 建議：逐句在 proposal 列明「延後到 Feature N」或「依 D81 改讀」；認證可用性加進 preflight 項目，或寫明「探測 worker 的 native turn 即為認證可用的證據」。

**S-10 · non-blocking · proposal L14-16、L19 與 DUR-09 L23、AC-D18 L28 不一致**
- 問題：proposal L19 說位置「與要求相符」，spec L23 與 L28 說「和 profile 比對」，但 proposal L16 的 profile 欄位沒有 repo、branch、目錄。另外 L16 說每個 profile 有 effort，L14 的 implementer 卻沒列；D69(4) 與 D76(2) 的 Implementer effort 依 task，profile 釘住 effort 會與之衝突。
- 建議：位置比對對象改為「preflight 要求的探測工作區」；明寫 profile 的 effort 是探測時的要求值，派工時逐 task 的 effort 屬 Feature 2。

**S-11 · non-blocking · proposal L20、AC-D27 L14「回報結果以外的 `orca` 子命令」**
- 問題：允許集合沒定義。verification L47 指出 preamble 要 worker 用 `ask`，還有 `check` 與 heartbeat 的 `send`；Codex sandbox 又無法只放行特定子命令。負例「被拒」要可驗，被拒的集合得具體。
- 建議：由政策檔列允許的子命令，負例至少取一個會改變 Orca 狀態的子命令（例如 `worker-start`、`gate-resolve`、`run-use`）。

**S-12 · non-blocking · AC-D28 L47-49、DUR-09 L21、proposal L29、L75**
- 問題：「profile 排除的 plugin 或 hook」要求 profile 宣告保留與排除清單，但 L21 的 profile 欄位沒有。Codex 沒有 plugin／hook 的詞彙。receipt 也沒記 D80(3) 要回答的事實：權限設定由哪裡帶、實際生效的權限模式、worker 的執行模式、preamble 的送達方式。
- 證據：verification L30「『verified』的 receipt 並不描述 worker 實際載入了什麼」；L77「模式改變會改變權限、liveness 來源與能否重用，R1 receipt 要記錄」；L50「1.4.218 對 Claude 改用 `promptInjectionMode: 'argv'`…要在 R1 記錄」；L88 native 紀錄帶 `permissionMode`、`sandbox_policy`。
- 建議：profile 加「保留與排除的 gateway、plugin、hook」欄位，Codex 以其設定來源表達；receipt 加「生效的權限模式、執行模式、權限設定來源、preamble 送達方式」。

**S-13 · non-blocking · AC-G24 L12；proposal 待決 6、7（L79-80）**
- 問題：2a 沒有派工，「作者的 branch」「作者 worktree」在探測時指什麼沒定；探測工作區或 Orca repo 沒建立時怎麼回報也沒有 scenario。
- 建議：指定負例目標為 engineer 探測工作區的 branch 與目錄；加 scenario「工作區或 repo 未註冊 → `unverified`，原因為環境未設定」。

**S-14 · non-blocking · 缺 scenario：preflight 中途中斷與殘留資源**
- 問題：探測 worker 派出後 preflight 被中斷，receipt 會不會寫出一半、殘留的 Task／terminal 誰處理、下一次 preflight 要不要先停掉它，都沒寫。proposal L64 把外部寫入的登記延到 Feature 2，所以這裡要有替代的最低規則。
- 證據：verification L80「`worker-list --run <id> --terminal-state reclaimable` 要回空」；L83 daemon 換代時進行中的 worker 留在舊 daemon。
- 建議：加 scenario：中斷 → 沒有 receipt 或 receipt 標 interrupted，都不算 verified；下一次 preflight 先列出並停掉殘留探測 worker，記進 receipt。並在 proposal 明寫「探測的外部寫入不走 DUR-06 的登記，Feature 2 補」。

**S-15 · non-blocking · AC-D26 L45、AC-D19 L33、AC-D23 L41**
- 問題：D81(2) 說重跑不需要人工決策，所以 `next` 不能回 `human`，但 spec 沒命名這個動作；Feature 1 的設計說未列的動作一律停下。AC-D19、D23 的「Blocked」顯示在哪個命令的輸出也沒寫。
- 證據：archived design D8 L285-288；D81(2)「重跑不需要人工決策，沒過才停下交人」。
- 建議：寫明 `next` 回報「執行 preflight」的動作，附 profile 與原因；Blocked 出現在 preflight 輸出與 `status`。

**S-16 · non-blocking · GAT-08 L17、AC-G19 L21、proposal L35-36**
- 問題：矩陣格子只標證據類型，不標結果，探測跑過但 unverified 的格子標什麼不明；「每項能力」的列沒有最小清單。receipt 只存 native session ID，驗證報告指出 transcript 約 30 天後會被清掉，M1 驗收時證據會指向不存在的檔案。
- 證據：verification L90「R1 receipt 只存 ID 與讀回值的話，到 M1 驗收時會指向已刪除的檔案」。
- 建議：格子記「證據類型＋verdict」；spec 列最小能力列；receipt 內嵌已遮蔽的 native 摘錄或其 digest。

**S-17 · non-blocking · AC-D27 L15 在真實 R1 的資源檢查**
- 問題：「呼叫紀錄沒有新增」只在 fake `gh`／`orca` 可觀察；真實 R1 對 `gh` 與 `orca` 的資源檢查要看什麼沒寫。
- 建議：spec 要求 fake 與真實用同一類可觀察結果，由 design 指定真實的觀察法（例如 PATH 上的記錄 wrapper、Orca 查詢無新 Task）。

**S-18 · non-blocking · 範圍與 design 字眼**
- 問題：DUR-09 L21 把具體 model ID 寫進產品 spec，2b 改接法時要再 MODIFIED；L23「再以 git 讀該目錄」是做法不是行為；proposal L17 的 `--role` 是介面細節；AC-D23 L40 把兩個情境併在一條。
- 建議：spec 只寫「核准的 profile」，model ID 留在 `workflow.yaml` 與 proposal；AC-D23 拆成兩條。

VERDICT: changes_required
