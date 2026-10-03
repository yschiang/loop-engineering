---
date: 2026-10-03
topic: Feature 2（orca-dispatch）研究報告的驗證
subject: research.md（commit 28d7f5c）
base: main@458ab77
method: 6 個面向各一位驗證者（claude-opus-5-5）重新查證，再由 Claude Fable 5.1 逐條反證，最後一位完整性評審列缺口；全部唯讀
---

# Feature 2 研究報告的驗證

[研究報告](research.md)寫好之後、寫 proposal 之前做了一次驗證。報告本身不改；**與本文衝突時以本文為準**。

## 方法與結果

- 6 個面向：Orca 能力、AC 歸屬、Feature 1 的實例、Feature 1 基準與延伸點、R1、規模。每個面向由一位驗證者從原始來源重做查證，不採用報告的寫法；每一條判定再由 Claude Fable 5.1 試著推翻；最後由一位評審列出還缺的東西。
- 全部唯讀。Orca 只用唯讀命令（`--version`、`status --json`、各命令 `--help`、`skills get`、`repo list`、`worktree list`），另外讀了 Orca app bundle 與本機設定檔；沒有建立、綁定或改變任何 Orca 物件。
- 159 條判定：確認 90、部分成立 65、推翻 2、無法查證 2。反證者沒有推翻任何一條驗證者的判定。評審列出 14 個缺口，其中 8 個會影響範圍。

## 一、改變結論的發現

1. **Orca 的 worker 預設跳過權限。** 本機 Orca 設定（`~/Library/Application Support/orca/profiles/local-default/orca-data.json` 的 `settings.agentDefaultArgs`）讓 Claude worker 以 `--dangerously-skip-permissions`、Codex worker 以 `--dangerously-bypass-approvals-and-sandbox` 啟動；這是 Orca 出廠的預設（`tui-agent-launch-defaults.js:21,113`）。照現在的設定，R1 的權限負例（f5）與 G12 的 Reviewer 隔離都不會成立，DUR-02「未驗證的 profile SHALL NOT 被默認可用」會讓派工停下。
   - 能帶權限設定的地方有兩條：(a) Orca 的全域 per-agent 設定 `agentDefaultArgs`／`agentCmdOverrides`，可以和 `worker-start --model --effort` 並用，但會套到使用者自己開的 Claude／Codex 分頁；(b) 自己開 terminal（`terminal create --command` 加 `worker-start --terminal`），只影響派出去的 worker，但 Orca 不記錄 launch 的 model／effort，`worker-stop` 對這種 terminal 回 `stop_unknown`（2026-09-25 實例，`runtime-probe.md` L36）。
   - 不論哪一條，Feature 1 的 `loop/settings.template.json` 都不能照搬：它設了 `disableAllHooks: true`，會關掉 Orca 掛在 `~/.claude/settings.json` 的 13 個 hook，而 Orca 的 liveness、`stage.activity` 與 hook 回報的 transcript 都靠這些 hook。
2. **規模約是報告估計的 1.3～1.5 倍。** 報告的程式估計假設 main 的寫法和參考實作一樣精簡；Feature 1 實際是參考實作對應模組的 1.36～1.53 倍。校準後 Feature 2 約 3,000～4,400 行程式、7,000～10,200 行測試，合計 10,000～14,600 行，是 Feature 1（5,699 行）的 1.8～2.6 倍，約 12～18 個 Feature 1 大小的 task（Feature 1 是 7 個）。報告分項表自己的合計是 2,350～3,100 行，不是 2,400～2,900。
   - 報告提的切法（卡住偵測、Codex R1、clear 實驗切成另一半）只搬走 6～14%。依資料相依，能獨立切出的是「R1 preflight＋Orca adapter＋能力矩陣」：約 700～800 行（25～32%），參考實作的 `preflight.py` 第 1 行就寫明它不讀寫 feature 狀態。切出後，派工的部分仍約 1,750～2,200 行（校準後 2,400～3,300），不小於 Feature 1。沒有一種二分能讓兩半都降到 Feature 1 的大小。
   - D79 的「放進 Feature 2，不再拆」是針對卡住偵測，回答時沒有規模數字；D57(4) 說 PR 大小看結構不看行數。Feature 1 的 5,699 行 PR 在 G2 兩輪（約 9 分、7 分）通過，但整個 change 從開到 merge 約 3 天、計畫審查 17 輪、開工後 6 次因設計缺口改計畫。
3. **orchestrate、loopctl 與三個內圈 skill 的分工還沒定。** D69(5) 讓 orchestrate 依序叫 spec-to-plan、plan-to-code、to-pr；但 plan-to-code 自己派 Implementer（`claude -p`）、自己做收件檢查與逐 task 審查（`codex exec`）、自己算每個 task 最多 3 次，三個 skill 都沒有提到 loopctl 或 Orca。要決定：在 orchestrate 跑的 run 裡，哪些步驟改經 `loopctl next` 與 Orca，哪些留在 skill。
4. **固定名稱的 `engineer` 工作區和「每個 Feature 一個 worktree」衝突。** D67 讓每個 Feature 在自己的 `feature/<id>` worktree 上 commit；git 不允許同一個 branch 同時 checkout 在兩個 worktree。如果 `engineer` 是一個固定的 checkout，Implementer 就不能在 Feature 的 branch 上 commit，Feature 5 也不能同時跑兩個 Feature。另外，Orca 目前唯一註冊的 repo 是 `folder` 類型、9 個工作區共用同一個路徑，沒有檔案隔離；`engineer`、`reviewer` 要有隔離，得先把 loopctl 的 repo 以 git repo 註冊。
5. **`reviewer` 工作區若是同一個 repo 的 git worktree，Reviewer 能改作者的 branch。** 所有 worktree 共用 `.git`，Reviewer 可以用 `git update-ref`／`git branch -f` 移動 `feature/<id>`。DUR-02 要求 Reviewer 用獨立的 clone 與 session；Feature 1 是用全新 clone 加 `codex exec -s read-only`。
6. **Orca 的 worker 會繼承使用者整套 agent 設定。** 本機 `~/.claude/settings.json` 讓所有 Claude 流量經過本機 gateway（`ANTHROPIC_BASE_URL` 指向 127.0.0.1:8787 的 caveman-proxy）、預設 model 是 haiku、PreToolUse 有 `caveman shrink-hook`，並啟用 superpowers、ponytail、ralph-wiggum 三個 plugin。ponytail 要求留下 `ponytail:` 註解，正是 AGENTS.md「不在程式裡留『以後再改』」禁止的。R1 目前只核對 model、effort、cwd 與權限負例，「verified」的 receipt 並不描述 worker 實際載入了什麼。
7. **D38 仍寫 OpenCode 預設、Orca／Codex／Claude Code 選配。** DUR-09 與 project-intent 的這句話來自 D38，D76 沒有修訂它，E-5 的影響範圍也只涵蓋 design-candidate 目錄。Feature 2 選用的正是 Orca＋Claude Code＋Codex。只有在「這是部署層級的選擇，M1 的部署選了 Orca，沒有 Orca 的部署仍可存在（D20 在 M2）」這個讀法下兩者才並存；這要 Project Lead 確認或修訂 D38，F2 的 spec 自己不能推翻一個現行決策。

## 二、逐節更正

| 報告位置 | 報告的說法 | 更正 |
| --- | --- | --- |
| §4 版本 | `remoteUpdateSupport.automatic: true` 表示自動更新開啟 | 這個欄位是說遠端 Orca client 能否驅動安裝，不是 app 自己的更新設定。Orca 會自己升級，只能從版本紀錄看出：09-25 是 1.4.209，10-01 是 1.4.215，10-03 是 1.4.218。D76(5) 不受影響 |
| §4 權限設定 | 引「How the worker runs follows the user's own setting for new agent tabs; there is no flag for it」說明沒有權限旗標 | 這句話講的是 terminal 或 structured chat 的執行模式，不是權限。`worker-start` 確實沒有權限參數，但權限由 Orca 的全域 per-agent 設定套上（見第一節第 1 點） |
| §4、§6 f5 | 自訂 argv 只能走 `--terminal`，而那樣不能帶 `--model`／`--effort` | 另有第三條：`agentCmdOverrides`／`agentDefaultArgs` 可帶 `--settings`、`--permission-mode` 或 Codex sandbox 參數，並和 `--model`／`--effort` 並用（只要不含 model、effort 參數）。自訂 terminal 本身也能帶 CLI 自己的 `--model`、`--effort`、`--settings`、`--session-id`，代價是 Orca 不記錄 launch 值、`worker-stop` 回 `stop_unknown` |
| §4、§6 native session ID | Orca 不提供 native session ID 或 transcript 路徑，對應方法要從頭找 | 沒有欄位，但有兩個有證據的候選：Claude 的 `worker-read` 訊息 id 等於 native 紀錄的 uuid（09-25 的 ctx_6f0f35db294f 40／40 相符），可定位 `<sessionId>.jsonl`；Orca 注入的 preamble 帶 Task 與 Dispatch ID，會出現在兩種 runtime 的 native 第一則 prompt。另外 `orca search --json` 回傳 native sessionId、cwd、branch 與檔案路徑。卡點的原因是：參考實作與 Feature 1 都用 `--session-id` 預先指定 ID，而 `worker-start` 不能傳這個參數 |
| §4、§5.1 訊號 2 | Orca 不分類卡住或 API 錯誤 | 編排層確實沒有。但 Orca 把 Claude 的 `StopFailure` hook 記成 turn 結束、outcome `failure`；`stage.activity` 是 hook 推得的 `working`／`blocked`／`waiting`／`done`（Stop、StopFailure、SessionEnd → done；PermissionRequest、permission_prompt → waiting）。`mainAgent.outcome` 是否出現在任何 orchestration CLI 輸出，未查證。Orca app 裡 `isApiErrorMessage`、`api_error` 出現 0 次，正規化後的訊息只有 text、tool-call、tool-result 三種 block，所以 Claude 的結構化 API 錯誤欄位不會經 `worker-read` 傳出來 |
| §5.1 訊號 3 | 由 `worker-read` 最後一則訊息的時間或 heartbeat 量 | Orca 內建 30 分鐘沒有 hook 事件就標 `stale_status`／`stale` 的機制（`agent-status-freshness.js:11`），正好等於 D79 的預設。它量的是 hook 靜默，不是輸出成長；30 分鐘後 `stage.activity` 變 `unknown`，所以 loopctl 要在 turn 結束後 30 分鐘內輪詢才看得到 `done`，之後要改讀 transcript |
| §4 冪等與讀回 | `request-show` 回 completed／pending／absent | receipt 以呼叫者身份為鍵。協調者從另一個 terminal 或程序恢復時，舊請求一律是 `absent`，所以 crash 後的讀回不能只靠 `request-show` |
| §6 stop 確認 | `worker-stop` 的 verdict 加 `worker-list` 轉 `exited` | `worker-stop` 之後的 `exited`（`source: worker_stop`）只是重述 Orca 自己的紀錄。R1 應以 stop verdict 本身或 `source: execution_host` 為準；自訂 terminal 會是 `stop_unknown` |
| §6 f3 | Orca 只有 `launch.requested`／`launch.effective` | `worker-list` 的 projection 另有 hook 觀察到的 `provider.model`，可做便宜的交叉核對，不取代 native 讀回 |
| §6 effort | effort「可能」讀得回 | 兩種 runtime 都穩定讀得回。D76(2) 要求 Reviewer 的 effort 也由 native 紀錄讀回；spec 要決定 effort 不符（不只是缺漏）是否使 R1 unverified |
| §6 f5 允許的 `orca` 子命令 | 只要允許 `send`、`check` | 至少還有 `ask`：preamble 要 worker 用 `ask` 問阻擋問題，並且不要用 AskUserQuestion。另一種做法是 assignment 改寫規則，要求以 `worker_done --outcome failed` 回報阻擋。Codex 的 sandbox 無法只放行特定子命令：放行 socket 就等於開放整個 Orca API |
| §6 Codex sandbox | `runtime_unavailable`，1.4.218 未重測 | 根因同日已查到（[integration-gaps.md](../../2026-09-25/integration-gaps.md)）：AF_UNIX 被 sandbox 擋住，加一條 `--allow-unix-socket` 可解；但放行後 Reviewer 能呼叫整個 Orca API，而且 socket 路徑隨 Orca 程序改變。照 Orca 現在的預設，Codex 沒有 sandbox，所以沒有 IPC 衝突，也沒有隔離 |
| §6 版本 | Orca 版本變就重跑 R1 | agent CLI 也會自己更新：Feature 1 期間 Claude Code 從 2.1.285 到 2.1.288，Codex 從 0.153.4 到 0.157.0。design §6 把 R1 綁在 runtime 版本，D76(5) 只寫 Orca，spec 要擇一 |
| §5.2 preamble 被當注入 | runtime-probe.md L16 只記「完成」 | L17 有記「agent 等確認，明確指示後才執行」，沒記 agent 判定為注入並拒絕 `check`。當時 Orca 沒傳 `--model`，worker 跑的是 claude-sonnet-5（不是 profile 的 claude-opus-5-5），preamble 以 `<pasted_content>` 送達，解開它的是 Codex 協調者的 `orca terminal send`，不是人。1.4.218 對 Claude 改用 `promptInjectionMode: 'argv'`、`--prefill`（`tui-agent-config.js:16-21`），送達方式可能已變，要在 R1 記錄 |
| §5.3 2.1 attempt 1 | 原因是權限 allow 清單漏列 | 不只是漏列：Implementer 設定刻意不給網路，而 task 2.1 要求線上核對 action SHA；協調者改由自己查 SHA 寫進 attempt 2，設定沒改。這是 task 需求與權限設定之間的缺口（plan／assignment 層）。AC-D16 只能類推，它的 THEN 是回到修正流程，不適用這種缺口。4.2 attempt 1 是第二個「有結果、結果回報阻擋」的例子（plan gap），卻被算成不計次；2.1 被算成 infra 重試。spec 需要一條路由與計次規則 |
| §5.3 訊號 2 的定義 | 「重試用完、turn 以 API 錯誤結束」 | 應定為「turn 以合成的 API 錯誤訊息結束」（`isApiErrorMessage: true`、`model: <synthetic>`）。`retryAttempt == maxRetries` 在自行恢復的執行中也出現（3.1 attempt 2 9／9、5.1 attempt 1 10／10），`maxRetries` 也會變（9、10、1）；互動 session 的終止錯誤可能完全沒有重試紀錄 |
| §5.3、§9 假設 3 | 30 分鐘門檻要大於最長的正常工具呼叫，504 秒的空白支持這點 | 504 秒是模型回應時間（xhigh 思考與 API 延遲），18 次執行中最長的工具執行只有 15 秒。門檻應以模型與 API 延遲為依據 |
| §5.3 B1 | 約 10 分鐘沒人發現 | 是因為人照例問「進度」才發現；等待迴圈除了 Bash 工具的 2 小時 timeout 沒有其他出口，最長可能 2 小時沒人發現。`review.sh` 有同樣的 `set -e` 加背景子 shell，至今沒改；B1 之後只修了等待條件 |
| §9 假設 2 | Claude Code 遇到 API 錯誤會停在提示 | 有直接觀察：互動 session（Claude Code 2.1.284）在 00:24:52Z 以「API Error: No response from API」結束 turn，停在提示，直到人輸入「Continue」才繼續 |
| §2.1 完成數 | F2 能完成 7 條 | 7 條有前提：D04、D18、D19 要兩個 profile 的 R1 都在 F2 跑（Q4(a)），D04 還要 F2 實作卡住觸發的 stop 與讀回；D21 只對 Orca＋Claude／Codex 成立，OpenCode 的部分屬 2b 或 M2，應比照 D23 標成部分完成 |
| §2.1 O06 | 完成點 F3（R2），F4 補「finding 修正不需再批准」 | O06 在 F3 完成；d3 已在 F2 驗到「修正不需再批准」。若要以真實 finding 再證一次，roadmap 的 F4 要加 ORC-03 |
| §2.1 O07 | F2 新增的情境（attempt 進行中收到 `scope_change`）不在 coverage | 就是 coverage 的 d4（O07、O23），前提在 F2 才第一次存在。coverage 沒定的是進行中的 attempt 怎麼辦：停下、等它、或丟掉結果；E-1 只涵蓋還沒送出的操作 |
| §2.1 D17 | F3 補 CI 等待與證據命令，F4 補 review | D79 後，D17 之後的部分是 Reviewer 卡住（F4），也可能是無人看守的同時執行（F5）。CI 等待算不算卡住、證據命令的上限是否保留，都還沒定 |
| §2.1 D16 | F2 是 w4、o1、o3、d9 | o3 依賴 `read_call_s` 在 D79 後是否保留。D79 一方面保留「infra 操作額外重試 2 次」，一方面把「API 或 infra 錯誤」算成卡住並交人；worker session 的 API 錯誤走哪一條，spec 要定（Feature 1 的 B1 是以 infra 重試處理） |
| §2.1 D25 | `active`、`ci_wait` 失去作用對象 | `attempts:<unit>:+1` 原本也是為 worker 時限設計（design §10）；但 D69(2) 的「每個 task 最多 3 次」給了它新的對象，前提是 loopctl 開始計算每個 task 的 attempt（Feature 1 沒有）。只有 `rounds:+1` 的對象在 F4 不變 |
| §2.1 | 列出 F2 的全部 AC | 漏了 O29、O30：F2 MODIFIED ORC-03、ORC-01 時要一起帶著。拆分：MODIFIED ORC-01、ORC-03、DUR-02、DUR-08；ADDED ORC-08、GAT-05、GAT-08、DUR-03、DUR-04、DUR-06、DUR-09 |
| §2.1 | 只分類 scenario | requirement 本文裡沒有自己 scenario 的 SHALL 也要分類，例如 DUR-09「派工前 SHALL 核對安裝版本、工具權限、實際 repo／workspace／branch、認證可用性與結果通道」（每次派工，不只 R1）、DUR-03 assignment 的「依賴」與「skill 版本」、ORC-08「保存 skill 引用版本」、DUR-02 worker 的寫入範圍與單一 writer、ORC-01「不讓任何路徑略過 D11、G1、D27 或 owner 的核對」 |
| §2.2 | 列出原文提到 Herdr 的地方 | 加上 AC-D21（L162）與 AC-D22（L166）；改讀依據引 D76（修訂 D45），不只 E-5。w9 用 OpenCode 的 `ses_…` handle，F2 沒有 OpenCode profile，要改用 Codex 的 session ID |
| §2.2 | 只有 DUR-08、AC-D17 的時間字樣要照 E-6 讀 | E-6 沒涵蓋：DUR-02「Timeout、lease 到期」、AC-D04「worker 超時…到期」、DUR-08 的離線計時（D47、S1-R09）、project-intent L73「stuck work 有 timeout」、L79「每個 run 主動執行最多 4 小時」。另外 D79 只拿掉 4h、45、30、30 分；`read_call_s`、`write_call_s`、`push_call_s`、`pr_ensure_call_s`、`evidence_call_s`（900 秒，D53 的 15 分鐘證據上限）這些單次呼叫的上限沒提到 |
| §3 `next` 詞彙 | `wait`、`observe`、`write`、`import`、`human` 都還沒實作 | `human`（附 blockers 與 decision_kinds）已實作；缺的是 `wait`、`observe`、`write`、`import`。`dispatch` 不在高層設計的詞彙裡，orchestrate 目前只能停在它 |
| §3 子命令 | 加 `write`、`observe`、`result import`、`safety`、`preflight` | 高層設計 §2 的命令表是 `write`、`observe`、`result import`、`preflight`；`safety` 是 envelope 欄位，要不要也做成子命令是 design 的選擇 |
| §3 測試接縫 | conftest 提供 clock 替換 | clock 是在各測試模組裡 monkeypatch `loopctl.clock.now`，`test_approval.py:381-398` 有可移動的 Clock，不在 conftest。會被 F2 改到的 F1 測試還有 `test_decisions.py:339-369`（resolve_* 回 unsupported）、`test_decisions.py:287-301`（四種預算目標）、`test_state.py:630` |
| §7 不能直接搬 | 列了 store 介面、plan 格式、pyyaml、`workflow.yaml` | 再加：參考實作的 `writes.py`、`observe.py` 依賴 `loopctl.gates` 與 `tools.gh`（屬 F3、F4）；參考實作的 commit 沒有 payload，冪等靠重跑 mutate 比狀態，main 則是同一 transition id 帶不同 payload 就記成衝突並擋住整個 run，所以 transition id 與 payload 要重新設計，不能照抄 |
| §8 | 程式 2,400～2,900 行、1.4～1.7 倍 | 見第一節第 2 點 |

## 三、報告沒有的事實

**Orca**

- Orca worker 的 liveness、`stage.activity` 與 hook 回報的 transcript 都依賴 `~/.claude/settings.json` 裡 Orca 的 hook；Feature 1 的 `dispatch.sh` 還 unset 了 `ORCA_AGENT_HOOK_*` 變數。關掉 hook 會讓 liveness 變成 `unverifiable`、`worker-read` 退回讀 terminal 輸出（`session_not_reported`）。要 live probe 確認。
- 執行模式：使用者設定 `openAgentTabsInChatByDefault`（本機 false）決定 worker 是 structured chat session 還是 terminal agent；重用 terminal 或自訂命令會強制 terminal 模式。模式改變會改變權限、liveness 來源與能否重用，R1 receipt 要記錄。
- `--model`／`--effort` 需要 runtime capability `orchestration.worker-launch-preferences.v1`，沒有時 CLI 丟 `incompatible_runtime`；preflight 可以和版本一起核對。
- 同一個 Orca Task 連續失敗 3 次會 circuit-break，而且不准以新 Run 或無關的 Dispatch 繞過（skill L676-678）。loopctl 的 attempt、infra 重試與修正輪怎麼對應 Orca 的 Task 與 `--retry-of`，要避開這個限制。
- 每次接受結果之後，協調者要重用、保留或釋放 worker terminal，`worker-list --run <id> --terminal-state reclaimable` 要回空（skill L159-174、L692-712）。
- `dispatch-show --task <id> --preamble` 與 `dispatch --dry-run --return-preamble` 能讀到實際注入的 preamble，可用於 R1 的 preamble 核對。09-25 的 preamble 有 Task 與 Dispatch ID，沒有 Run ID，loopctl 的 assignment 要自己帶 Run ID。
- Orca 可以用自己管理的 `CODEX_HOME` 跑 Codex（`orca/codex-runtime-home/home`），這時 rollout 不在 `~/.codex/sessions`。一次 Codex 派工也可能產生多個 rollout（subagent），對應時要選 root thread。
- 本機同時跑兩代 Orca PTY daemon（`daemon-v36` 自 09-28、`daemon-v37` 自 10-02 隨 1.4.218 啟動）。版本更新時進行中的 worker 留在舊 daemon；新版能否 list、read、stop 它，沒查過。
- `orca automations`（排程與 `--precheck`）存在，但它是常駐排程器，D47 排除用它做卡住偵測。

**Native 紀錄與憑證**

- Native 紀錄也帶權限狀態：Claude 的 user 紀錄有 `permissionMode`，Codex 的 `turn_context` 有 `sandbox_policy`、`approval_policy`、`permission_profile`。R1 可以直接讀實際生效的權限，作為 G12 的證據，不只靠負例。
- Claude 每筆紀錄的 `cwd` 會跟著 agent 的 `cd` 變（Feature 1 的 18 次中有 3 次），f6 要讀派工第一則或 marker 那則紀錄的 cwd。
- Claude Code 預設約 30 天清掉 transcript：本機最舊的 session transcript 是 2026-09-03。09-25 的 Orca worker transcript 約 10-25 就會消失，B1 與 4.1 的在 11 月初。R1 receipt 只存 ID 與讀回值的話，到 M1 驗收時會指向已刪除的檔案。
- Orca worker 的 preamble 與 transcript 帶 dispatch capability（`dcap_` 開頭的 48 字元值），worker 的工具呼叫也會原樣帶著。DUR-09 規定 dispatch capabilities 不得寫入交接文件或自動進 Git；保存 native 原文（D06）、R1 證據與 ticket 留言之前都要遮蔽。

**Feature 1 的紀錄**

- Feature 1 的 502 錯誤全部帶 `cave_gateway_error`／`cave_upstream_unavailable`，也就是經過本機 gateway；協調者用同一個 gateway，這也符合 4.1 與協調者同時停住。gateway 故障會讓 worker 與協調者一起失效，正是 D47 不設 watchdog 時抓不到的情況。
- stderr 的 `Decompression error: ZlibError` 出現在 4 次 API 錯誤中的 3 次開頭，比 transcript 的第一筆重試早；它只在 terminal 上看得到。
- 權限拒絕很常見：18 次執行中有 17 次出現，共 72 筆，幾乎都被 agent 繞過；只有 2.1 attempt 1 因此停下。單一拒絕事件不能算卡住或 infra。
- 4.1 的停滯區間 00:00:31～00:35:19 共 34.8 分鐘，中間只在 00:26:44 有一個模型 turn，所以才差 3.8 分鐘沒到 30 分鐘；`worker-read` 的 `--source auto|transcript|terminal` 會量出不同的「沒有新輸出」，spec 要指定來源。
- 4.1 跑了 77.3 分鐘並被接受；照舊的 45 分鐘 worker 上限它會被停掉。
- Feature 1 的成本：49 個 commit、計畫審查 17 輪、Implementer 17 次計時 attempt 共 4.46 小時、ledger 的牆鐘約 25.7 小時（含約 9.3 小時等待）、從開 change 到 merge 約 3 天；重切研究假設每個 Feature 約 1.5 個工作日。

**loopctl 基準**

- 退出碼：1 被拒、2 用法錯誤或 unsupported、3 只用在 transition 衝突、4 不是 owner、5 狀態不可信、6 IO 錯誤；`human` 的 `next` 回 0。高層設計把 3 定為一般的 Blocked，F2 要決定自己的 Blocked 用哪個碼、`blocked` 欄位放什麼。
- `resolve_conflict` 只處理 `decide:<id>` 的衝突（`decisions.py:266-312`）；F2 若讓 result import 或 write 也產生衝突（AC-D08 的「不同內容保留雙方並 Blocked」），現在解不開，`committed["kind"]` 會丟 KeyError。
- `approval` 已經釘住 plan 的 locator、version、digest，以及 spec、AC、design 的 digest；plan 與政策的內容已以 write-once 方式存在 object store。這正是 assignment 要帶的版本，也是 E-1 判斷 `superseded` 用的核准身份。
- `next` 不看政策：`workflow.yaml` 沒登記、沒核准或 digest 不符時，`next` 仍回 `dispatch`。roadmap 要求用 R1 驗證過的 profile 派工，所以 F2 要讓派工受政策核准、目前 digest 與 R1 receipt 管制，這就把檔案與外部輸入帶進 `next`（F1 design L467 預告的風險）。
- ORC-01 的產品 spec 寫 controller「SHALL NOT 常駐、啟動 agents 或執行呼叫者提供的命令」，F1 的 design 也寫「不開子程序」；高層設計 §4、§5 卻讓 loopctl 以固定 argv 執行外部寫入與讀取。F2 要在 MODIFIED ORC-01 說清楚 loopctl 能執行什麼。
- `phase` 只有 planning、awaiting_approval、approved；DUR-01 要 `status` 顯示目前階段，F2 要決定實作中與卡住是不是新的 phase。
- 每次 commit 都把整份狀態寫進歷史，`transitions` 永久保留每個 payload。高層設計每 30 秒輪詢一次並在每次讀取前持久化 `seq`；4.1 跑了 77 分鐘，照這樣提交每次輪詢會讓 `feature.json` 與歷史持續變大。
- CI 只允許 `only_on` 的平台 skip，而 ubuntu runner 上沒有 Orca；所有 pytest 都要用 fake `orca`，真實 R1 只能是另外產生的 receipt。
- 打包：F1 design 把 `loopctl.tools` 的 dist-smoke 檢查延到 F2，`dist-smoke.sh:43-44` 斷言 envelope 剛好 6 個鍵。
- plan 格式：若 loopctl 要從 `tasks.md` 讀 task 順序、AC、驗法、擁有路徑與 effort，spec-to-plan 寫的格式就變成機器契約。目前 spec-to-plan 只列每個 task 要有哪些內容，沒有結構；F1 的 `tasks.md` 是摘要表加逐 task 的文字段落，驗法是逐 task 寫，不是逐 AC。

## 四、更新後的待決事項

研究報告 §9 的未知 1、5、6 已縮小（見第二節），其餘仍要 live probe。下表是驗證後要由人決定、會影響 Feature 2 範圍的事；只影響 design 的留給 spec-to-plan。

| # | 事項 | 為什麼影響範圍 | 決定者 |
| --- | --- | --- | --- |
| 1 | Feature 2 要不要拆；若拆，先切出「R1 preflight＋Orca adapter＋能力矩陣」 | 校準後是 Feature 1 的 1.8～2.6 倍；R1 的 live probe 會回答派工 spec 需要的事實 | Project Lead（roadmap 重切） |
| 2 | Orca worker 的權限設定由哪裡帶：Orca 全域設定，或自己開 terminal | 前者改到使用者自己的分頁；後者失去 Orca 的 stop 與 launch 紀錄。不設的話 R1 一定不過 | Project Lead（環境與信任邊界） |
| 3 | orchestrate 跑的 run 裡，plan-to-code 的哪些步驟改經 loopctl 與 Orca（派工、attempt 計次、收件檢查、逐 task 審查、ticket 紀錄） | 決定 F2 要改哪些 skill、loopctl 要不要算 attempt（D69(2)） | Project Lead |
| 4 | `engineer` 是「目前 Feature 的 worktree 的名稱」，還是固定 checkout；Feature 5 同時跑時怎麼命名 | 固定 checkout 和每個 Feature 一個 branch 衝突 | Project Lead |
| 5 | Reviewer 的放置：每次 review 一個 clone，或 git worktree 加 sandbox 與改 ref 的負例 | 決定 Codex R1 在 F2 能測什麼；工作區形式選錯，F4 會違反 DUR-02 | Project Lead（可與 #1、Q4 一起） |
| 6 | worker 繼承的設定（gateway、hooks、plugins、預設 model）哪些要固定或排除，用什麼帶 | R1 receipt 要能描述 worker 實際載入的東西；ponytail 與 AGENTS.md 衝突 | Project Lead |
| 7 | D38 的讀法：確認為部署層級的選擇，或修訂 D38 | DUR-09 的「Orca 選配」不能只靠 F2 的 MODIFIED 改掉 | Project Lead |
| 8 | Orca 的 mailbox 由誰消化；worker 的 `ask`、escalation 算不算要交人 | worker 在 `ask` 裡等時沒有新輸出，30 分鐘後會觸發卡住，而 Orca 認為它健康 | spec（需 Project Lead 同意） |
| 9 | F2 的 orchestrate 寫 ticket 留言時，是否算 DUR-06 的外部寫入（D60 的「另議」） | 算的話 F2 要提前做 `publish_issue` 的一部分 | Project Lead |
| 10 | worker session 的 API／infra 錯誤：照 D16 重試 2 次，還是照 D79 算卡住交人；gateway 錯誤歸哪一類 | Feature 1 的 B1 是以 infra 重試處理 | Project Lead |
| 11 | engineer 工作區 clear 時機的實驗：保留、移到 Feature 3，或依 Feature 1 的數據直接定為每個 task 清空 | `--terminal` 重用不能帶 `--model`／`--effort`，和 D69(4) 的逐 task effort 衝突；Feature 1 的 18 次都是新 session，0 次壓縮 | Project Lead（修訂 D76(6)） |
| 12 | Feature 2 自己的 task 用什麼派：照 Feature 1 用 `claude -p`，或手動經 Orca | 手動經 Orca 時，權限預設是跳過，也還沒有卡住偵測 | Project Lead |
| 13 | D79 沒提到的單次呼叫上限（`read_call_s`、`evidence_call_s` 等）保留與否；R1 在 agent CLI 換版時要不要重跑 | o3、w11 與 F3 的 g15 依賴前者 | spec（需 Project Lead 同意） |

只影響 design、留給 spec-to-plan 的：transition id 與 payload 的設計、`resolve_conflict` 的擴充、Blocked 的退出碼、`phase`、輪詢提交的成本、native 紀錄複製進 object store、`dcap_` 遮蔽、daemon 換代時進行中的 worker、preamble 的送達方式、request-show 以呼叫者為鍵的讀回。
