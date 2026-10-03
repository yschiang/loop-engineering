# Tasks

本檔是 `orca-preflight` 唯一的實作計畫。它不放實作碼。每個 task 列出：

- 要寫的測試；
- 每個測試斷言的行為；
- Red 應該失敗在哪個斷言；
- Green 的預期結果；
- 執行指令（D68）。

介面與不變式見 [design.md](design.md)，以下用 D1～D12 引用它的章節。

## 共同規則

- **模型與模式**（D52、D72）：
  - 每個 task 都用預設模式：plan 寫到設計、介面、不變式與測試為止。
  - Implementer 是 Claude Opus 5.5，照 Feature 1 用 `claude -p` 派（proposal 待決 9）。
  - Reviewer 是 GPT-6 Astra（另一家廠商）。每個 task 在新 session、新 clone 上唯讀審查。
  - effort 依 D69 的表，逐 task 標在下方。
- **順序**：依序實作 1.1 → 2.1 → 3.1 → 3.2 → 4.1 → 5.1 → 6.1 → 7.1。依賴只從前往後。每張測試表的列序就是撰寫順序。
- **Red 的規則**（D68）：
  - Red 必須是所列斷言的比較失敗（AssertionError）。ImportError、usage error、unknown command，或停在呼叫上的例外，都不算。
  - 1.1 先建立 `preflight` 命令與 stub。stub 回 exit 3，`blocked.reasons == ["not_implemented"]`、`result.items == {}`。所以後面 task 的測試都能走到自己的斷言。
  - 巢狀欄位用不會拋例外的方式取值（Feature 1 的 `Result`，D13）。
  - 每個 Red 都以同一 task 前面的測試已經 Green 為前提。
  - 標「突變」的測試，預期會因為前面的實作而一寫就 Green。這時以一次不提交的突變證明它會失敗在所列斷言上：照表中寫的方式暫時破壞行為，記下失敗，再還原。
  - 沒有標「突變」的測試一寫就 Green → 停下，回報計畫有誤，不自行改測試。
- **fake 與時間**（D10）：
  - 所有測試都經 PATH 上的 fake `orca`、`claude`、`codex`、`ps` 執行；`HOME`、`CODEX_HOME` 指到 tmp；git 用真的，`origin` 是 tmp 裡的 bare repo。
  - 時間只經 `loopctl.clock.now` 與 `loopctl.clock.sleep` 的替身前進。
  - 不加任何只給測試用的設定或 hook。`preflight.timeout_s` 是政策值，測試可以在自己的政策檔設定它。
- **每個 task 的完成條件**：
  - 在 task 的 head 上，`uv run pytest && uv run ruff check . && uv run mypy src` 全部通過，前面 task 的測試也包含在內。
  - 1.1 另外要 `scripts/dist-smoke.sh` 通過（`pyproject.toml` 改了）。
  - 逐 task 審查沒有未解的 blocking finding。
- **指令**：每張測試表註明檔案；單一測試的指令是 `uv run pytest <檔案> -k <名稱>`。
- **證據**：
  - 每個 task 的 Red 與 Green 原始紀錄（命令、完整輸出、exit code、commit）存在 `.delivery/orca-preflight/<task>/attempt-<n>/`，不進 Git。
  - 逐 task 審查的結果貼在 #44。
- **Commit**：
  - 格式：`<type>(<scope>): <祈使句>`，英文，不超過 72 字元。
  - scope 用模組名：`policy`、`tools`、`orca`、`native`、`receipts`、`preflight`、`cli`、`next`、`state`、`store`、`clock`。`build` 不帶 scope。
  - `feat`、`fix`、`refactor` 的 body 要有 `Why:` 與 `Behavior:`。
  - 沒有 `Co-Authored-By` 或任何 AI 署名。
  - 每個 task 一到幾個 commit，各自綠燈。核取方塊在 task 的最後一個 commit 勾選。

### 共用檔案（依序擁有，不並行修改）

| 檔案 | 擁有順序 | 規則 |
| --- | --- | --- |
| `pyproject.toml`、`uv.lock` | 1.1 把 pyyaml 移到執行依賴 | 兩者在同一個 commit 更新；全新 clone 的 `uv sync --frozen` 仍成功 |
| `tests/conftest.py` | 1.1 加 `fakes`、`orca_env`、`clock`、`approved_run` | 只新增 fixture，不改既有 fixture 的行為 |
| `tests/fakes/`（`bin/fake`、`scenarios.py`） | 1.1 建立 → 3.1、3.2、4.1、6.1 只新增 scenario 產生器 | 不改既有產生器的輸出 |
| `src/loopctl/cli.py` | 1.1 加 parser 與 stub → 2.1 換成實作的 handler → 5.1 改 `status`、`next` | 只動自己的 handler；envelope 仍是 6 個鍵 |
| `src/loopctl/preflight.py` | 1.1 建立（stub 與政策核准）→ 2.1 → 3.1 → 3.2 → 4.1 → 6.1 | 每個 task 只加自己的步驟，保持 D4 的順序 |
| `src/loopctl/store.py` | 2.1 加 `append_record`、`list_records`、`locked_dir` | 不改既有函式 |
| `src/loopctl/receipts.py` | 2.1 建立 → 5.1 加 `applicable` | — |
| `src/loopctl/native.py` | 3.1 建立（Claude 讀回）→ 3.2（負例與設定）→ 4.1（Codex） | — |
| `src/loopctl/orca.py`、`tools.py` | 2.1 建立（版本、status、run、worktree）→ 3.1 加 terminal 與 worker 命令 → 4.1、6.1 只加需要的呼叫 | argv 固定；不接受呼叫者提供的命令 |
| `src/loopctl/next.py`、`state.py` | 5.1 | `derive` 不改；只加 `effective` 與視圖欄位 |
| `workflow.yaml`、`tests/test_ci.py` | 7.1 | — |
| `tests/test_approval.py`、`tests/test_scope_policy.py` | 5.1 | 只改核准後 `next` 的斷言（D9），其他斷言不動 |

### 總覽

| Task | 交付 | 依賴 | Implementer／Reviewer effort | AC |
| --- | --- | --- | --- | --- |
| 1.1 | 測試骨架：fake 工具與 scenario、`clock.sleep`、pyyaml、`policy.load`、`preflight` 命令與政策核准的拒絕 | — | high／high | D30（preflight 部分） |
| 2.1 | receipt 與探測紀錄的 store、verdict 與 exit、不需派 worker 的判定、`--out` | 1.1 | xhigh／xhigh | D19、D23、G23 |
| 3.1 | Implementer 探測的主流程：marker、terminal、worker-start、等待、Claude 讀回、停止、`worker_done` | 2.1 | xhigh／xhigh | D18、D19 |
| 3.2 | Claude 的權限負例、載入的設定、摘錄與遮蔽；全部成立才 verified | 3.1 | xhigh／xhigh | D27、D28、D29 |
| 4.1 | Reviewer 探測：Codex 啟動、rollout 讀回、sandbox 拒絕、隔離負例、獨立 clone | 3.2 | xhigh／xhigh | G24、D18、D27、D22 |
| 5.1 | 派工管制：適用判定、目前版本、`next.effective`、`status` 的 profiles | 4.1 | xhigh／xhigh | D26、D30（next 部分）、D01、D22 |
| 6.1 | 殘留清理、中斷與互斥 | 5.1 | xhigh／xhigh | D31、D30（清理） |
| 7.1 | 政策檔的實際 profiles、能力證據矩陣、CI 測試調整 | 6.1 | medium／high | G19、D22 |

Effort 的依據（D69）：

- 1.1 是一般行為加測試骨架。
- 2.1～6.1 守的是「未驗證的 profile 不可用」這道安全界線，或 receipt 的完整性；出錯會讓不安全的 worker 被判成可用。
- 7.1 只改設定與文件。

## 1. 測試骨架與政策檔

- [ ] 1.1 fake 工具、`clock.sleep`、pyyaml 執行依賴、`policy.load`、`preflight` 命令與政策核准的拒絕；驗證：`uv run pytest tests/test_harness.py tests/test_policy.py` 與完整的完成條件通過

**模式與 effort**：預設模式；high／high。

**交付**：

- **fake 工具**：
  - `tests/fakes/bin/fake`：依 basename 扮成 `orca`、`claude`、`codex`、`ps`（D10）。
  - `tests/fakes/scenarios.py`：產生 scenario 的 helper，本 task 只有「固定回應」與「沒有預期的呼叫」兩種。
- **fixture**（conftest）：
  - `fakes(*tools, scenario)`：裝上 PATH，設好 `FAKE_SCENARIO`、`FAKE_LOG`；`fakes.calls()` 讀回呼叫紀錄。
  - `orca_env`：設 `ORCA_TERMINAL_HANDLE`；`HOME`、`CODEX_HOME` 指到 tmp。
  - `clock`：替換 `now` 與 `sleep`；`sleep` 只推進假時間。
  - `approved_run(repo, feature, policy_text)`：`init`、`claim`、登記 policy、人工 `policy_change` 核准。
- `src/loopctl/clock.py` 加 `sleep(seconds)`。
- `pyproject.toml`、`uv.lock`：pyyaml 移到 `[project] dependencies`（D2）。
- `src/loopctl/policy.py`：`load(path) -> Policy`，含 `digest`、`profiles`（逐 profile 的 `invalid` 原因）、`preflight.timeout_s`（D2）。
- **`preflight` 命令**：
  - `cli.py` 加 `preflight` 的 parser（`--repo`、`--feature`、`--role {implementer,reviewer}`、`--out`）與 handler。
  - `src/loopctl/preflight.py` 做 D4 的第 1、3 步：政策未核准就 `policy_not_approved`；其餘回 stub（共同規則）。

**擁有路徑**：上列各檔，`tests/test_harness.py`、`tests/test_policy.py`。

**依賴**：無（Feature 1 的程式已在 main）。

**AC**：D30（preflight 拒絕的部分）。

**Commit**：

- `build: make pyyaml a runtime dependency`
- `feat(policy): read workflow profiles once with their digest`
- `feat(preflight): refuse to probe without an approved policy`

`tests/test_harness.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_fake_tool_replays_the_scenario_and_logs_argv` | 以 scenario `{orca: [{match: ["--version"], stdout: "1.4.218\n"}]}` 執行 `orca --version`：stdout 是 `1.4.218`、exit 0；`fakes.calls()` 恰好一筆 `{tool: "orca", argv: ["--version"]}` | fake 腳本先寫成回空字串：`stdout == "1.4.218\n"` 不成立 | 通過 |
| `test_unexpected_call_is_recorded_and_fails` | 呼叫 scenario 沒有的 argv：exit 97；`fakes.calls()[-1]["unexpected"] is True` | fake 先對所有呼叫回 0：exit 的比較不成立 | 通過 |
| `test_clock_sleep_advances_fake_time` | `clock` fixture 下 `clock.sleep(5)`，之後 `clock.now()` 比之前多 5 秒，沒有真的等待（整個測試在 1 秒內結束） | `clock.sleep` 先不推進：時間差的比較不成立 | 通過 |

`tests/test_policy.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_profiles_are_parsed_with_the_file_digest` | D2 範例檔：兩個 profile 的欄位逐一相等；`digest == "sha256:" + sha256(bytes)`；`timeout_s == 900` | `load` 先回空的 `profiles`：欄位比較不成立 | 通過 |
| `test_profile_missing_fields_is_invalid_not_an_error` | 拿掉 Reviewer 的 `model`：`load` 不拋例外；Reviewer 的 `invalid == ["model"]`；Implementer 的 `invalid == []`。同樣以 `runtime: opencode` 測：`invalid` 含 `runtime` | `invalid` 先永遠是空清單：比較不成立 | 通過 |
| `test_preflight_refuses_without_an_approved_policy` | 以參數化跑四種情況：登記了但沒核准、核准後檔案被改、沒有登記、檔案讀不到。`preflight --role implementer` 都是 exit 1、`error == "policy_not_approved"`、`policy` 欄是 `policy_view` 的狀態；`fakes.calls()` 是空的；`$LOOPCTL_HOME/repos` 下沒有 `receipts/` 紀錄 | 1.1 的 handler 先一律回 stub（exit 3）：exit 的比較不成立 | 通過 |
| `test_approved_policy_is_not_refused` | 核准的政策：exit 不是 1，`error` 不是 `policy_not_approved`（之後的 task 加上判定，這個斷言仍成立） | 突變：把核准判定反過來，`error` 的比較不成立 | 通過 |

## 2. Receipt 與不需派 worker 的判定

- [ ] 2.1 repo 層級的 receipt 與探測紀錄、verdict 與 exit、profile 與環境的判定、未選用接入、`--out`；驗證：`uv run pytest tests/test_preflight_static.py tests/test_receipts.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `store.py`：`append_record(dir, payload) -> seq`（`O_CREAT|O_EXCL`、fsync、撞號換下一號）、`list_records(dir)`（略過不完整的紀錄並回報檔名）、`locked_dir(dir)`（`flock` 非阻塞，拿不到時丟 `Busy`）（D8）。
- `receipts.py`：`write(repo, role, receipt) -> ref`（`put_object` 加上索引紀錄）與 `latest(repo, role)`。latest 讀回時以 `get_object` 核對 digest，不符丟 `ReceiptCorrupt`。
- `tools.py`：`run(argv, timeout_s)`。執行檔不存在時回 `missing`，逾時回 `timeout`，都不丟例外（D1）。
- `orca.py`：`version()`、`status()`、`run_current()`、`run_create(objective)`、`worktrees()`、`repos()`。
- `preflight.py`：
  - D4 的第 0、4、5 步與第 13 步；
  - verdict 是逐項的 AND；
  - exit 0／3 與 `blocked`（D3）；
  - `--out` 寫出同一份 receipt；
  - D4 第 6 步以後先回 `not_implemented` 項目，讓 verdict 為 unverified。
- `cli.py`：`preflight` 的 handler 包進 `guarded`；`Busy` 對應 exit 1 `preflight_running`。

**擁有路徑**：上列各檔，`tests/test_receipts.py`、`tests/test_preflight_static.py`。

**依賴**：1.1，從它取得：

- `policy.load(path) -> Policy`：不丟例外，以 `invalid` 表達欄位問題。
- fixture：`fakes`、`orca_env`、`clock`、`approved_run`。
- `preflight` 的參數固定，本 task 不改。

**AC**：D19（缺必要設定、環境不存在）、D23、G23。

**Commit**：

- `feat(store): add write-once records outside run state`
- `feat(receipts): keep the latest preflight receipt per repo and role`
- `feat(preflight): judge profiles and environment before any probe`

`tests/test_receipts.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_latest_receipt_wins_and_reads_back_by_digest` | 依序寫入 verified、unverified 兩份：`latest` 是 unverified 那份；兩份都在 `objects/`，內容的 sha256 等於索引裡的 ref | `latest` 先回第一份：verdict 的比較不成立 | 通過 |
| `test_tampered_receipt_is_reported_not_trusted` | 寫入後改動 object 的內容：`latest` 丟 `ReceiptCorrupt`，訊息含該 ref | 先不核對 digest：預期的例外沒有出現（`pytest.raises` 的斷言） | 通過 |
| `test_records_are_write_once_and_ordered` | 連續 `append_record` 三次：編號 1、2、3，內容依序讀回；寫一個不完整的 `4.json` 後，`list_records` 回三筆，並回報 `4.json` | 先用 `os.replace` 覆寫同一檔：筆數的比較不成立 | 通過 |

`tests/test_preflight_static.py`（所有測試都用 `approved_run` 與 `orca_env`）：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_invalid_profile_is_unverified_without_calling_tools` | Implementer 缺 `model`：exit 3、`blocked.reasons` 含 `profile_invalid:model`；`fakes.calls()` 是空的；`latest` 是這份 unverified | 1.1 的 stub reasons 是 `not_implemented`：reasons 的比較不成立 | 通過 |
| `test_same_model_makes_the_reviewer_unverified` | 兩個 profile 的 model 相同（effort 不同）：Reviewer 的 preflight exit 3，`reasons` 含 `model_not_distinct`，`items["model.distinct"].pass is False` | 先不比較 model：reasons 的比較不成立 | 通過 |
| `test_missing_selected_tools_block_the_profile` | 參數化：(a) PATH 上沒有 `orca`；(b) `orca status` 的 `runtime.reachable` 是 false；(c) 沒有 `claude`；(d) 不在 Orca terminal（沒有 `ORCA_TERMINAL_HANDLE`）；(e) Orca 沒有路徑等於 repo 根目錄的 git repo；(f) 找不到 `preflight-engineer` 工作區。每一種都 exit 3，`reasons` 只含該項的原因，例如 `transport_missing`、`transport_unreachable`、`runtime_missing`、`not_in_orca_terminal`、`repo_not_registered`、`workspace_not_found` | 先只回 `not_implemented`：reasons 的比較不成立 | 通過 |
| `test_unselected_tools_are_never_called` | PATH 上另裝 `herdr`、`opencode` 的 fake，scenario 讓它們一被呼叫就 exit 97；環境齊全時 preflight 走到 `not_implemented`；`fakes.calls()` 中沒有 `herdr`、`opencode` | 突變：在環境檢查加一個 `opencode --version`，呼叫紀錄的斷言不成立 | 通過 |
| `test_no_run_is_created_when_one_is_bound` | `run-current` 回既有的 Run：不呼叫 `run-create`；沒有綁定時呼叫一次 `run-create`，之後的檢查用它回傳的 id | 先總是呼叫 `run-create`：呼叫紀錄的比較不成立 | 通過 |
| `test_out_writes_the_same_receipt` | `--out <path>`：檔案內容的 sha256 等於 `result.receipt` 的 ref | 先不寫 `--out`：檔案存在的斷言不成立 | 通過 |
| `test_concurrent_preflight_for_one_role_is_refused` | 以 `cli_proc` 在另一個程序持有該 role 的 lock（prelude 取得 lock 並等待）：第二個 preflight exit 1、`error == "preflight_running"`，沒有新的 receipt | 先不取 lock：exit 的比較不成立 | 通過 |

## 3. Implementer 探測

- [ ] 3.1 marker 與探測紀錄、啟動 Claude、worker-start、等待、讀回、停止與 `worker_done`；驗證：`uv run pytest tests/test_preflight_claude.py -k "not negative and not settings"`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `preflight.py`：D4 第 6～12 步，Claude 的部分：
  - D5 的設定檔與命令文字；
  - 探測任務的文字（共 7 步）；
  - D7 的等待與停止。
- `orca.py`：`terminal_create`、`worker_start`、`worker_show`、`terminal_wait`、`terminal_close`、`task_count`。
- `native.py`：Claude transcript 的搜尋（恰好一份含 marker、檔名等於 uuid）、讀回、turn 是否完成。
- `tests/fakes/scenarios.py`：`claude_probe(...)`。它產生完整的 Orca 對話，並在 `terminal create` 時寫出 transcript。transcript 依 research P4、P5 的欄位，可以設定每一步的結果。

**擁有路徑**：上列各檔，`tests/test_preflight_claude.py`。

**依賴**：2.1，從它取得：

- `receipts.write`／`latest`：同一 role 以最新一份為準，讀回時核對 digest。
- `tools.run(argv, timeout_s) -> Completed`：執行檔不存在時回 `missing`，不丟例外。
- `orca.version/status/run_current/run_create/worktrees/repos`。
- `locked_dir` 與 exit 0／3 的 envelope。

**AC**：D18、D19（任務、回報、停止）。D29 的整體 verified 在 3.2：本 task 還不判讀負例與設定，那兩類 item 回 `not_implemented`，verdict 一定是 unverified。

**Commit**：`feat(preflight): probe the Claude profile through an Orca terminal`

`tests/test_preflight_claude.py`（本 task 的部分）：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_full_probe_passes_launch_readback_and_stop_items` | scenario 的每一步都成立：`readback.*`、`placement.*`、`permission.mode`、`positive.inside_write`、`task.accepted`、`task.worker_done`、`stop.confirmed` 都 `pass`；receipt 含 D6 列的欄位（`marker`、`native_session_id`、`orca.dispatch`、`versions.native == "2.1.288"`）。本測試不斷言 verdict | 2.1 在第 6 步以後回 `not_implemented`，這些 item 不存在：比較不成立 | 通過 |
| `test_launch_command_and_settings_are_fixed` | `terminal create` 的 `--command` 依序含 `PREFLIGHT_MARKER=<marker>`、`claude --model claude-opus-5-5 --effort high --session-id <uuid>`、`--setting-sources project,local`、`--settings <path>`、`--permission-mode dontAsk`；設定檔的 `hooks` 只含命令中有 `ORCA_AGENT_HOOK` 的 hook，`enabledPlugins` 只有 superpowers，`allow` 含工作區的 `Edit(...)` 與三個 `orca orchestration` 規則 | 先照抄全部 hook：hook 數量的比較不成立 | 通過 |
| `test_marker_is_recorded_before_the_terminal_exists` | `probes/` 的第一筆是 `started`，含 marker 與 uuid；它的寫入早於 fake 收到 `terminal create`（以 `FAKE_LOG` 的順序與紀錄編號比較）；之後依序是 `terminal`、`dispatch`、`closed` | 先在拿到 handle 後才寫：順序的比較不成立 | 通過 |
| `test_readback_mismatch_is_unverified` | 參數化：transcript 的 model 是 `claude-sonnet-5`；effort 是 `medium`；cwd 是另一個目錄；只有 prompt、沒有 assistant 紀錄；有兩份含 marker 的 transcript；檔名不等於 uuid。每一種都 exit 3，對應的 item 不成立，原因寫出要求值與實際值 | 先不比對、一律成立：verdict 的比較不成立 | 通過 |
| `test_task_not_reported_is_unverified` | worker 沒有送 `worker_done`（`worker-show` 的 status 仍是 `dispatched`）：`task.worker_done` 不成立，verdict unverified；terminal 仍被關閉並確認 | 先以 transcript 的完成當作 `worker_done`：item 的比較不成立 | 通過 |
| `test_stop_must_be_confirmed_by_process_info` | `terminal close` 之後 fake `ps` 仍列出 marker：檢查 10 次（`clock.sleep(0.5)` 被呼叫 10 次）後 `stop.confirmed` 不成立；`probes/` 沒有 `closed`，最後一筆是 `stop_unconfirmed` | 先以 `terminal close` 的 `ptyKilled` 為準：item 的比較不成立 | 通過 |
| `test_probe_timeout_is_unverified_and_still_stops` | `terminal wait` 都回 timeout，transcript 一直沒完成，`timeout_s` 為 60：假時間超過 60 秒後 `reasons` 含 `probe_timeout`；`terminal close` 仍被呼叫，`stop.confirmed` 成立 | 先在逾時時直接返回：`terminal close` 的呼叫紀錄斷言不成立 | 通過 |
| `test_worker_start_failure_reports_the_stage` | `worker-start` exit 1，JSON 的 `failedStage: "agent_readiness"`：`reasons` 含 `task_not_started:agent_readiness`；terminal 仍被關閉 | 先忽略 exit：reasons 的比較不成立 | 通過 |

- [ ] 3.2 Claude 的權限負例、載入的設定、摘錄與遮蔽；驗證：`uv run pytest tests/test_preflight_claude.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `native.py`：
  - 依 D5 的步驟找出每個負例的 `tool_use` 與 `tool_result`；
  - 判定「嘗試、runtime 拒絕、資源未變」；
  - `settings.excluded` 的判讀。
- `preflight.py`：
  - D6 的資源前值與後值；
  - 摘錄與 `native_digest`；
  - `dcap_` 遮蔽（套用到 receipt、`--out`、探測紀錄）。
- `tests/fakes/scenarios.py`：`claude_probe` 加上可設定每個負例結果與載入設定的參數，只新增參數，預設值不變。

**擁有路徑**：上列各檔，`tests/test_preflight_claude.py`。

**依賴**：3.1，從它取得：

- `claude_probe(...)` scenario；
- `native.find_claude(marker, uuid) -> Transcript`，含「恰好一份」的判定；
- 探測任務的 7 個步驟與它們的固定文字；
- receipt 的 `items` 結構。

**AC**：D27、D28。

**Commit**：`feat(native): judge Claude permission denials from the transcript`

`tests/test_preflight_claude.py`（本 task 加入）：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_full_probe_is_verified` | 全部成立的 scenario：exit 0、`verdict == "verified"`，每一項 `pass`；已核准的 run 之後由 5.1 的管制採用 | 3.1 時負例與設定回 `not_implemented`：verdict 的比較不成立 | 通過 |
| `test_negative_counts_only_a_runtime_denial` | 參數化 5 個負例 × 4 種結果：(a) 有 `tool_use`、`is_error` 為 true、帶 `toolDenialKind`、資源未變 → 成立；(b) 沒有 `tool_use`（worker 沒嘗試）；(c) 有 `tool_use` 但結果沒有 `toolDenialKind`（命令執行了）；(d) 被拒但資源改變（範圍外檔案出現、遠端 ref 出現、Task 數多 1）。只有 (a) 讓該項成立；(b)～(d) 該項不成立，verdict unverified，原因寫明是哪一種 | 突變：把 (b) 的「沒有 `tool_use`」也判成立，該列的比較不成立 | 通過 |
| `test_worker_self_report_is_not_a_denial` | transcript 的最後文字寫「all steps denied」，但 `git push` 那一步沒有 `toolDenialKind`：`negative.git_push` 不成立 | 突變：改成讀最後文字判定，item 的比較不成立 | 通過 |
| `test_excluded_settings_make_the_profile_unverified` | 參數化：`skill_listing` 出現 `ponytail`；有一筆 `hook_success` 的命令不含 `ORCA_AGENT_HOOK`。每一種都讓 `settings.excluded` 不成立；只有 superpowers 與 Orca hook 時成立；receipt 的 `gateway == {configured: <設定檔的 ANTHROPIC_BASE_URL>, observable: false}` | 突變：讓 `settings.excluded` 不看 `skill_listing`，ponytail 那一列的比較不成立 | 通過 |
| `test_capabilities_are_redacted_everywhere` | transcript 的 `worker_done` 命令含 `dcap_abc123`：receipt、`--out` 檔、`probes/` 與 `settings/` 下所有檔案都不含 `dcap_abc123`，含 `dcap_<redacted>` | 先不遮蔽：搜尋的斷言不成立 | 通過 |
| `test_receipt_keeps_redacted_excerpts_and_the_native_digest` | 每一項的 `evidence` 都指向 `excerpts` 中存在的 id；`native_digest` 等於 transcript 檔的 sha256；把 transcript 刪掉之後，`latest` 讀回的 receipt 仍有全部摘錄 | 先只存 native session ID：摘錄存在的斷言不成立 | 通過 |

## 4. Reviewer 探測

- [ ] 4.1 Codex 的啟動、rollout 讀回、sandbox 拒絕、隔離負例、獨立 clone；驗證：`uv run pytest tests/test_preflight_codex.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `preflight.py`：D5 的 Codex 命令文字，以及 Reviewer 的第 8、9 步。
- `native.py`：
  - rollout 的搜尋：`CODEX_HOME`、日期目錄、恰好一份含 marker；
  - 從 `turn_context` 讀回；
  - 以 `Operation not permitted` 判定 sandbox 拒絕；
  - 以 `task_complete` 判定完成。
- `isolation.independent_clone` 的判定。
- `tests/fakes/scenarios.py`：`codex_probe(...)`，欄位依 research P7。

**擁有路徑**：上列各檔，`tests/test_preflight_codex.py`。

**依賴**：3.2，從它取得：

- 負例的「嘗試、拒絕、資源未變」判定介面，只是 runtime 不同；
- 資源前值與後值的表；
- 遮蔽與摘錄。

**AC**：G24、D18（Codex）、D27（Codex）、D22（兩個 profile 分開保存）。

**Commit**：`feat(native): probe the Codex reviewer profile and its isolation`

`tests/test_preflight_codex.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_codex_launch_avoids_interactive_prompts` | `terminal create` 的命令含 `codex -m gpt-6-astra`、`-c model_reasoning_effort="xhigh"`、profile 的每個 `-c` 覆寫、`-s read-only`、`-a never`、`--no-daemon`，以及 `PREFLIGHT_MARKER` 與 PATH 前綴 | 3.1 只組 Claude 的命令，Reviewer 走到 `runtime_unsupported`：命令文字的斷言不成立 | 通過 |
| `test_codex_readback_comes_from_turn_context` | rollout 的 `turn_context` 為 `gpt-6-astra`、`xhigh`、`read-only`、`never`，cwd 是 Reviewer 工作區：讀回與 `permission.mode` 各項成立；參數化 model、effort、cwd 不符，或有兩份含 marker 的 rollout：對應的 item 不成立 | 未實作 Codex 讀回時，item 不存在：比較不成立 | 通過 |
| `test_sandbox_denial_is_read_from_the_output` | 某個負例的輸出含 `Operation not permitted` 且資源未變 → 成立；輸出是 `error connecting to api.github.com`，或 exit 0 而且有正常輸出（live probe 的 `git push --dry-run`）→ 不成立 | 先以 exit code 非 0 判定：網路錯誤那一列的比較不成立 | 通過 |
| `test_reviewer_cannot_touch_the_implementer_workspace` | 第 8、9 步被拒，Implementer 工作區沒有新檔案、它的 branch ref 前後相同 → `negative.implementer_file`、`negative.implementer_ref` 成立；scenario 讓 fake effect 真的寫入檔案或移動 ref → 該項不成立 | 先不檢查資源：item 的比較不成立 | 通過 |
| `test_shared_git_dir_fails_the_independent_clone_check` | Reviewer 工作區是 Implementer 那個 repo 的 linked worktree（`git worktree add`）→ `isolation.independent_clone` 不成立；是另一個 `git clone` 的工作區 → 成立 | 先不檢查：item 的比較不成立 | 通過 |
| `test_live_probe_shape_is_unverified_with_listed_gaps` | 照 research P7 的實際結果組 scenario（`git push --dry-run` 有執行、`orca` 全部 EPERM、沒有 `worker_done`、linked worktree）：verdict unverified；`reasons` 恰好是 `negative.git_push`、`task.worker_done`、`isolation.independent_clone` 三項，其他項成立 | 突變：把 `Operation not permitted` 判讀拿掉，`reasons` 會多出 orca 那一項 | 通過 |
| `test_profiles_keep_separate_latest_receipts` | Implementer verified、Reviewer unverified 之後：兩個 role 的 `latest` 各自是自己的 receipt；Reviewer 的 unverified 不影響 Implementer 的 `latest` | 突變：把兩個 role 的索引目錄寫成同一個，`latest` 的比較不成立 | 通過 |

## 5. 派工管制

- [ ] 5.1 適用判定、目前版本、`next.effective`、`status` 的 profiles；驗證：`uv run pytest tests/test_gating.py tests/test_approval.py tests/test_scope_policy.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `receipts.applicable(...)`（D9）。
- `preflight.current_versions(role)`。
- `next.effective(state_next, policy_status, impl)`。
- `cli.status`、`cli.next_step` 依 D9 重新判定：
  - envelope 的 `next` 是 `effective` 的結果；
  - `result` 加 `state_next`；`status` 另加 `profiles`；
  - `--human` 兩者都印。
- `state.view`、`state.human` 加對應欄位。
- `test_approval.py:606-633`、`test_scope_policy.py:254-257` 改成：先核准政策，並寫入適用的 receipt，再斷言 `dispatch`。

**擁有路徑**：上列各檔，`tests/test_gating.py`，以及兩個既有測試的那幾行。

**依賴**：4.1，從它取得：

- 兩個 role 各自的 `latest`；
- receipt 的 `versions` 與 `policy_digest` 欄位；
- `claude_probe`、`codex_probe` scenario：用來以真的 preflight 產生 receipt，不直接寫檔。

**AC**：D26、D30（`next` 的部分）、D01、D22。

**Commit**：`feat(cli): gate dispatch on an applicable preflight receipt`

`tests/test_gating.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_dispatch_needs_an_applicable_implementer_receipt` | 已核准 plan 與政策，Implementer 從未 preflight：`next` 的 envelope `next == {action: "preflight", role: "implementer", reasons: ["not_run"]}`、exit 0；狀態檔的 `next` 仍是 `dispatch`；跑一次 verified 的 preflight 之後，`next` 回 `dispatch` | 4.1 時 `next` 照抄狀態檔：action 的比較不成立 | 通過 |
| `test_receipt_stops_applying_when_anything_changes` | verified 之後，參數化：(a) 新跑一次 unverified；(b) `orca --version` 變成 1.4.219；(c) `claude --version` 變成 2.1.289；(d) `claude` 讀不到版本；(e) 政策重新核准成另一個 digest；(f) receipt 的 object 被改。每一種的 `next` 都是 `preflight`，`reasons` 分別是 `latest_unverified`、`transport_version_changed`、`agent_cli_version_changed`、`version_unknown`、`policy_digest_changed`、`receipt_corrupt` | 先只看 verdict：(b) 的比較不成立 | 通過 |
| `test_unapproved_policy_comes_before_the_receipt` | 已核准 plan，但政策被改過（`digest_mismatch`）、receipt 適用：`next == {action: "human", decision_kinds: ["policy_change"], reason: "policy_not_approved", policy: "digest_mismatch"}`；fake 的呼叫紀錄沒有任何 `--version` | 先檢查 receipt：action 的比較不成立 | 通過 |
| `test_gating_never_changes_next_before_approval` | 參數化：未 claim、有未解衝突、等待 `approve_plan`：envelope 的 `next` 等於狀態檔的 `next`；fake 的呼叫紀錄是空的 | 突變：讓 `effective` 對所有 action 都檢查政策，衝突那一列的比較不成立 | 通過 |
| `test_status_shows_both_nexts_and_each_profile` | `status` 的 `result.state_next` 是 `dispatch`；envelope 的 `next` 等於同一時刻 `next` 命令回報的值；`result.profiles.implementer` 與 `reviewer` 各有 `status`、`verdict`、`receipt`、`versions`、`reasons`；`--human` 的文字同時含兩個 next 與兩個 profile | 先不加這些欄位：`state_next` 的斷言不成立 | 通過 |
| `test_write_commands_keep_the_state_next` | `decide` 的 envelope `next` 等於狀態檔的值；fake 的呼叫紀錄沒有 `--version`（ORC-01） | 突變：讓 `decide` 也呼叫 `effective`，呼叫紀錄的斷言不成立 | 通過 |

## 6. 殘留清理、中斷與互斥

- [ ] 6.1 殘留探測 worker 的清理、中斷後不產生 verified、清理不受政策影響；驗證：`uv run pytest tests/test_preflight_residual.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `preflight.py`：D4 第 2 步與 D8 的殘留規則。
- `cleanup` 紀錄與輸出欄位。
- 殘留確認不了停止時，不派新的 worker。

**擁有路徑**：`src/loopctl/preflight.py`、`tests/test_preflight_residual.py`、`tests/fakes/scenarios.py`（只新增 `residual(...)`）。

**依賴**：5.1，從它取得：

- 完整的探測流程；
- `probes/` 紀錄的種類；
- `latest` 與 `applicable`。

**AC**：D31、D30（清理的部分）。

**Commit**：`feat(preflight): clean up probe workers left by an interrupted run`

`tests/test_preflight_residual.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_interrupted_preflight_leaves_no_verified_receipt` | 以 `cli_proc` 執行 preflight，在 fake 收到 `worker-start` 之後由 scenario 結束程序（SIGKILL）：`latest` 不變（沒有新的 receipt）；`probes/` 有 `started`、`terminal`、`dispatch`，沒有 `closed` | 突變：在派出前先寫一份 verified receipt，`latest` 的比較不成立 | 通過 |
| `test_next_preflight_closes_the_residual_first` | 上一個測試之後再跑一次 preflight：在新的 `terminal create` 之前，先對殘留的 handle 呼叫 `terminal close`，並以 `ps` 確認；`probes/` 多一筆 `cleanup {marker, handle, confirmed: true}`；輸出的 `cleanup` 欄列出它；之後照常探測 | 2.1～5.1 不處理殘留：呼叫紀錄的順序斷言不成立 | 通過 |
| `test_residual_that_will_not_stop_blocks_a_new_probe` | 殘留的程序在 `terminal close` 之後仍在：不呼叫新的 `terminal create`；政策已核准時寫一份 unverified receipt，`reasons` 含 `residual_not_stopped`，並列出殘留的 marker 與 handle | 先記錄後照常探測：`terminal create` 的呼叫斷言不成立 | 通過 |
| `test_cleanup_runs_even_without_an_approved_policy` | 有殘留，而且政策未核准：exit 1、`policy_not_approved`；殘留仍被關閉，`cleanup` 紀錄與輸出都有；沒有新的 receipt | 先在政策檢查之後才清理：`terminal close` 的呼叫斷言不成立 | 通過 |

## 7. 政策檔、矩陣與 CI

- [ ] 7.1 `workflow.yaml` 的實際 profiles、能力證據矩陣、`test_ci.py` 調整；驗證：`uv run pytest tests/test_ci.py tests/test_policy.py`

**模式與 effort**：預設模式；medium／high。

**交付**：

- `workflow.yaml`：加入 D2 的 `profiles` 與 `preflight`。
- `tests/test_ci.py:45-55`：改成斷言頂層鍵是 `{schema_version, repo, g3, profiles, preflight}`。
- `docs/validation/capability-matrix.md`：
  - 欄：Orca＋claude、Orca＋codex；
  - 列：D6 的 item；
  - `fake` 欄填對應的測試名稱，`profile-probe` 與 `real-E2E` 先標 `none`。真實 R1 之後由協調者更新（D11）。

**擁有路徑**：`workflow.yaml`、`tests/test_ci.py`、`docs/validation/capability-matrix.md`。

**依賴**：6.1，從它取得：完整的 item 名稱與測試名稱。

**AC**：G19、D22（矩陣）。

**Commit**：

- `feat(policy): declare the Orca profiles in workflow.yaml`
- `docs(validation): add the capability evidence matrix`

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_ci.py` 的政策檔鍵（改寫既有斷言） | 頂層鍵是五個；`policy.load("workflow.yaml")` 兩個 profile 的 `invalid` 都是空清單 | 先只改測試、不改 `workflow.yaml`：鍵集合的比較不成立 | 通過 |
| `test_policy.py::test_repo_policy_profiles_are_distinct_models` | repo 的 `workflow.yaml`：Reviewer 與 Implementer 的 model 不同，Reviewer 的 runtime 是 `codex`、Implementer 的是 `claude` | 先把 Reviewer 的 model 填成 `claude-opus-5-5`：比較不成立 | 通過 |

矩陣文件沒有 Red：它是文件，內容由 Reviewer 對照測試名稱與 D6 核對。

## 驗收驗證

- **CI**：每條 AC 都由下表的測試，在 G1（全新 clone、完整套件）與 PR 上的 `unit-linux` 通過來證明。
- **真實環境**：真實 R1 由協調者在 Orca terminal 內執行（D11），要 Project Lead 授權。receipt 存在 `docs/validation/orca-preflight/receipts/`。驗收條件：Implementer `verified`；Reviewer 如實記錄。
- **彙整**：to-pr 把結果彙整到 #44 的 PR Pass package。

| AC | 驗證的測試（task） | 真實 receipt | 通過代表 |
| --- | --- | --- | --- |
| D01 | 5.1 `…both_nexts_and_each_profile…` | — | 狀態檔的下一步只依 run 狀態；`status` 另顯示依 receipt 與版本判定的結果，等於 `next` |
| D18 | 3.1 `…readback_mismatch…`；4.1 `…turn_context…` | 兩份 | 讀回值不符、沒有 native turn、找不到或多於一份含 marker 的紀錄，都是 unverified |
| D19 | 2.1 `…invalid_profile…`、`…missing_selected_tools…`；3.1 `…task_not_reported…`、`…stop_must_be_confirmed…`、`…worker_start_failure…` | — | 能力缺口具體 Blocked，不改用其他工具 |
| D22 | 4.1 `…separate_latest_receipts…`；5.1 `…each_profile…`；7.1 矩陣 | 兩份 | 兩個 profile 分開保存，不共用成功標記 |
| D23 | 2.1 `…unselected_tools_are_never_called…`、`…missing_selected_tools…` | — | 未選用的接入不被呼叫；已選的工具不在就 Blocked |
| D26 | 5.1 前兩個測試 | — | 沒有適用的 receipt 就不派工；任一條件改變就要重跑 |
| D27 | 3.2 `…only_a_runtime_denial…`、`…self_report…`；4.1 `…sandbox_denial…` | Implementer | 只有「嘗試、runtime 拒絕、資源未變」才算被拒 |
| D28 | 3.2 `…excluded_settings…`、`…redacted_everywhere…` | 兩份 | 記錄載入的設定；排除的設定被載入就 unverified；不含憑證 |
| D29 | 3.2 `…full_probe_is_verified…`；3.1 `…launch_readback_and_stop_items…` | Implementer（必須 verified） | 全部成立才 verified，`next` 才能派工 |
| D30 | 1.1 `…refuses_without_an_approved_policy…`；5.1 `…unapproved_policy…`；6.1 `…cleanup_runs_even…` | — | 政策未核准時不探測、不派工，殘留仍被清理 |
| D31 | 6.1 前三個測試 | — | 中斷不產生 verified；下次先清殘留，停不掉就不派新的 |
| G19 | 7.1 矩陣；4.1 `…live_probe_shape…` | 兩份 | 沒有真實證據的格子標 `none`，不宣稱 E2E |
| G23 | 2.1 `…same_model…` | — | 兩個角色同一 model 時 Reviewer 不可用 |
| G24 | 4.1 `…implementer_workspace…`、`…independent_clone…` | Reviewer（如實） | Reviewer 改得到 Implementer 的檔案或 branch、或不是獨立 clone，就 unverified |

## 範圍

本檔只涵蓋 proposal 的 What Changes。派工、assignment、結果匯入、卡住偵測與 orchestrate skill 在 Feature 2。Reviewer 的獨立 clone 是環境設定，由人做（design D12）。

## 環境

- 本機 macOS、Python 3.12、uv。
- CI 的 `unit-linux` 上沒有 Orca、Claude、Codex，所有測試都用 fake。
- 真實 R1 需要：
  - Orca 1.4.218 以上、已註冊的 loop-engineering（git）；
  - `preflight-engineer`、`preflight-reviewer` 工作區（已在研究時建立）；
  - Claude Code、Codex CLI；
  - 一個 Orca terminal。

## 風險

- 見 design「Risks / Trade-offs」。計畫層面另外兩點：
  - 3.1 是最大的 task（D4 的 7 個步驟）。若超出一個 session，可以把「等待與逾時」（後兩個測試）切成 3.1b，其他不變。
  - fake transcript 依 live probe 的欄位寫成；真實格式若不同，真實 R1 會以 unverified 暴露，再回到計畫修正。

## 執行界線

- 每個 task 最多 3 次 attempt（D69(2)）。
- Implementer 不碰真實 Orca：只在 worktree 內跑測試，不執行 `orca`、不碰 `~/.claude`、`~/.codex` 的真實紀錄。
- 真實 R1 由協調者在所有 task 完成後執行，需要 Project Lead 授權。
