# Tasks

本檔是 `orca-preflight` 唯一的實作計畫，不放實作碼。每個 task 列出要寫的測試，每個測試寫明：

- 斷言的行為；
- Red 應該失敗在哪個斷言；
- Green 的預期結果；
- 執行指令（D68）。

介面與不變式見 [design.md](design.md)，以下用 DD-1～DD-12 引用它的章節；`D<n>` 是 `docs/decisions.md` 的專案決策（D83）。

## 共同規則

- **模型與模式**（D52、D72）：
  - 每個 task 都用預設模式，plan 寫到設計、介面、不變式與測試為止。
  - Implementer 是 Claude Opus 5.5，照 Feature 1 用 `claude -p` 派（proposal 待決 9）。
  - Reviewer 是 GPT-6 Astra（另一家廠商），每個 task 在新 session、新 clone 上唯讀審查。
  - effort 依 D69 的表，逐 task 標在下方。
- **順序**：依序實作 1.1 → 2.1 → 3.1 → 3.2 → 4.1 → 5.1 → 6.1 → 7.1。依賴只從前往後。每張測試表的列序就是撰寫順序。
- **Red 的規則**（D68）：
  - Red 必須是所列斷言的比較失敗（AssertionError）。ImportError、usage error、unknown command，或停在呼叫上的例外，都不算。
  - 1.1 先建立所有新模組與 `preflight` 命令的介面，回傳合理的預設值（stub），後面 task 的測試才能走到自己的斷言。stub 的回傳見 1.1 的「交付」。
  - 巢狀欄位用不會拋例外的方式取值（Feature 1 的 `Result`）。
  - 每個 Red 都以同一 task 前面的測試已經 Green 為前提。
  - 標「突變」的測試，預期會因為前面的實作而一寫就 Green。這時以一次不提交的突變證明它會失敗在所列斷言上：照表中寫的方式暫時破壞行為，記下失敗，再還原。
  - 沒有標「突變」的測試一寫就 Green → 停下，回報計畫有誤，不自行改測試。
- **測試只斷言長期成立的公開行為**：
  - 不斷言 `not_implemented` 這類暫時的值；
  - 後面 task 要改前面的測試或 scenario 時，在「擁有路徑」寫明。
- **fake 與時間**（DD-10）：
  - 所有測試都經 PATH 上的 fake `orca`、`claude`、`codex`、`ps`、`gh`、`herdr`、`opencode` 執行；
  - 沒有預期到的呼叫，在 teardown 讓測試失敗；
  - `HOME`、`CODEX_HOME` 指到 tmp；git 用真的，`origin` 是 tmp 裡的 bare repo；
  - 時間只經 `loopctl.clock.now` 與 `loopctl.clock.sleep` 的替身前進；
  - 不加任何只給測試用的設定或 hook。`preflight.timeout_s` 是政策值，測試可以在自己的政策檔設定它。
- **每個 task 的完成條件**：
  - 在 task 的 head 上，`uv run pytest && uv run ruff check . && uv run mypy src` 全部通過，前面 task 的測試也包含在內。
  - 1.1 另外要 `scripts/dist-smoke.sh` 通過（`pyproject.toml` 改了）。
  - 逐 task 審查沒有未解的 blocking finding。
- **指令**：每張測試表註明檔案；單一測試的指令是 `uv run pytest <檔案> -k <名稱>`。
- **證據**：
  - 每個 task 的 Red 與 Green 原始紀錄（命令、完整輸出、exit code、commit）存在 `.delivery/orca-preflight/<task>/attempt-<n>/`，不進 Git。
  - 逐 task 審查的結果貼在 #44。
- **Commit**（AGENTS.md「Commit 訊息」）：
  - 格式：`<type>(<scope>): <祈使句>`，英文，不超過 72 字元。
  - scope 用模組名：`policy`、`tools`、`orca`、`native`、`receipts`、`preflight`、`cli`、`next`、`state`、`store`、`clock`、`validation`。`build` 不帶 scope；`test` 照 AGENTS.md 用受測模組的 scope。1.1 的共用骨架橫跨多個模組，依 AGENTS.md 的跨 scope 例外，寫成 `test: …`。
  - `feat`、`fix`、`refactor` 的 body 要有 `Why:` 與 `Behavior:`；每個 commit 的最後一段是 `Refs: #44`。
  - 5.1 改變既有 run 的 `next`（核准後不再一定是 `dispatch`），所以用 `feat(cli)!:`，並寫 `BREAKING-CHANGE:` 說明遷移方式：核准政策並跑 preflight。
  - 沒有 `Co-Authored-By` 或任何 AI 署名。
  - 每個 task 一到幾個 commit，各自綠燈。核取方塊在 task 的最後一個 commit 勾選。

### 共用檔案（依序擁有，不並行修改）

| 檔案 | 擁有順序 | 規則 |
| --- | --- | --- |
| `pyproject.toml`、`uv.lock` | 1.1 把 pyyaml 移到執行依賴，並在 dev group 加 `types-PyYAML`（`mypy --strict`） | 兩者在同一個 commit 更新；全新 clone 的 `uv sync --frozen` 仍成功 |
| `tests/test_test_policy.py` | 1.1 | 它的 `child` fixture 只複製 `conftest.py`；1.1 讓它同時複製 `tests/fakes/`，否則新的 autouse 隔離在子測試裡找不到 fake。其他斷言不動 |
| `tests/conftest.py` | 1.1 加 autouse 的工具隔離，以及 `fakes`、`orca_env`、`clock`、`approved_run`、`probe_repo` | 只新增 fixture；不改既有 fixture 的行為。既有測試因工具隔離而可能呼叫的，只有 `--version` 的預設回應 |
| `tests/fakes/`（`bin/fake`、`scenarios.py`） | 1.1 建立 → 2.1、3.1、3.2、4.1、6.1 只新增 scenario 產生器或參數 | 不改既有產生器在預設參數下的輸出 |
| `src/loopctl/cli.py` | 1.1 加 parser 與 stub → 2.1 換成實作的 handler → 5.1 改 `status`、`next` | 只動自己的 handler；envelope 仍是 6 個鍵 |
| `src/loopctl/preflight.py` | 1.1 建立 → 2.1 → 3.1 → 3.2 → 4.1 → 5.1（`current_versions`）→ 6.1 | 每個 task 只加自己的步驟，保持 DD-4 的順序 |
| `src/loopctl/store.py` | 1.1 加 `append_record`、`list_records`、`locked_dir` 的介面 → 2.1 實作 | 不改既有函式 |
| `src/loopctl/receipts.py` | 1.1 介面 → 2.1 實作 `write`、`latest` → 5.1 實作 `applicable` | — |
| `src/loopctl/native.py` | 1.1 介面 → 3.1（Claude 讀回）→ 3.2（負例與設定）→ 4.1（Codex） | — |
| `src/loopctl/orca.py`、`tools.py` | 1.1 介面 → 2.1 實作 `run` 與環境查詢 → 3.1 加 terminal 與 worker 命令 → 6.1 只加需要的呼叫 | argv 固定；不接受呼叫者提供的命令 |
| `src/loopctl/next.py`、`state.py` | 5.1 | `derive` 不改；只加 `effective` 與視圖欄位 |
| `tests/test_policy.py` | 1.1 建立 → 7.1 新增一個測試 | 不改既有測試 |
| `tests/test_preflight_static.py` | 2.1 | 之後的 task 不改它。它的 `environment(...)` scenario 對 `terminal create` 回失敗，所以 3.1 以後探測在第 8 步結束，這些測試的斷言照樣成立（DD-4） |
| `tests/test_preflight_claude.py` | 3.1 建立 → 3.2 刪掉一個暫時的測試並新增 | 見 3.2 的「交付」 |
| `workflow.yaml`、`tests/test_ci.py` | 7.1 | — |
| `tests/test_approval.py`、`tests/test_scope_policy.py` | 5.1 | 只改核准後 `next` 的斷言（DD-9），其他斷言不動 |

### 總覽

| Task | 交付 | 依賴 | Implementer／Reviewer effort | AC |
| --- | --- | --- | --- | --- |
| 1.1 | 測試骨架（工具隔離、fake 的能力）、新模組的介面、pyyaml、`policy.load`、`preflight` 在政策未核准時拒絕 | — | xhigh／xhigh | D30（preflight 部分） |
| 2.1 | receipt 與探測紀錄的 store、verdict 與 exit、不需派 worker 的判定、`--out` | 1.1 | xhigh／xhigh | D19、D23、G23、D29（不改 feature 狀態） |
| 3.1 | Implementer 探測的主流程：marker、terminal、worker-start、等待、Claude 讀回、版本、停止、`worker_done` | 2.1 | high／xhigh | D18、D19 |
| 3.2 | Claude 的權限負例、載入的設定、摘錄與遮蔽；全部成立才 verified | 3.1 | xhigh／xhigh | D27、D28、D29 |
| 4.1 | Reviewer 探測：Codex 啟動、rollout 讀回、sandbox 拒絕、隔離負例、獨立 clone、Codex 的設定 | 3.2 | high／xhigh | G24、D18、D27、D28、D22、G19 |
| 5.1 | 派工管制：適用判定、目前版本、`next.effective`、`status` 的 profiles、跨 run 共用 | 4.1 | xhigh／xhigh | D26、D30（next 部分）、D01、D22、D29 |
| 6.1 | 殘留清理、兩種中斷點、清理失敗的重試 | 5.1 | xhigh／xhigh | D31、D30（清理） |
| 7.1 | 政策檔的實際 profiles、能力證據矩陣、CI 測試調整 | 6.1 | medium／high | G19、D22 |

Effort 的依據（D69）：

- 1.1～6.1 守的是「未驗證的 profile 不可用」與「未核准的政策不探測」這兩道安全界線，或 receipt 的完整性。出錯會讓不安全的 worker 被判成可用。
- 7.1 只改設定與文件。
- 3.1、4.1 的 Implementer 依 Project Lead 於 2026-10-03 的決定改為 high，Reviewer 維持 xhigh：這兩個 task 的出錯由 xhigh 的逐 task 審查把關。4.1 涵蓋 6 個 AC，照 D69 的表是 xhigh；改成 high 是 Project Lead 的決定。

## 1. 測試骨架與政策檔

- [x] 1.1 工具隔離與 fake 的能力、新模組的介面、pyyaml 執行依賴、`policy.load`、`preflight` 在政策未核准時拒絕；驗證：`uv run pytest tests/test_harness.py tests/test_policy.py` 與完整的完成條件通過

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- **fake 工具**（DD-10）：
  - `tests/fakes/bin/fake`：argv 比對與擷取、代換、`write`／`state`／`snapshot`／`kill_parent` effect、呼叫紀錄、沒有 scenario 時的 `--version` 預設回應。
  - `tests/fakes/scenarios.py`：產生 scenario 的 helper。
- **conftest**：
  - autouse 的工具隔離：`fakebin/`、`minbin/`，teardown 斷言沒有 `unexpected` 的呼叫；
  - `fakes(scenario)`、`fakes.calls()`、`fakes.without(tool)`（改用受控 PATH）；
  - `orca_env`；
  - `clock`（替換 `now` 與 `sleep`）；
  - `approved_run(repo, feature, policy_text)`：`init`、`claim`、登記 policy、人工 `policy_change` 核准；
  - `probe_repo`：tmp 裡的作者 repo、bare origin，以及兩個探測工作區，Reviewer 那個可選 linked worktree 或獨立 clone。
- `src/loopctl/clock.py` 加 `sleep(seconds)`。
- `pyproject.toml`、`uv.lock`：pyyaml 移到 `[project] dependencies`（DD-2）；dev group 加 `types-PyYAML`。
- `src/loopctl/policy.py`：`load(path) -> Policy`，介面與錯誤照 DD-2。
- **新模組的介面與 stub**：DD-1「跨 task 的介面」表中的每個函式、型別與例外（`store.Busy`、`receipts.ReceiptCorrupt`、`orca.Problem`、`orca.Started`、`native.Found`、`native.Session`、`native.Call`、`native.CallResult`、`preflight.Item`）都在本 task 建立並可匯入。stub 的回傳：
  - `store.append_record` 回 1、不寫檔；`list_records` 回 `Records([], [])`；`locked_dir` 不取鎖。
  - `receipts.write` 回 `"sha256:" + "0"*64`；`latest` 回 `None`；`applicable` 回 `(False, ["not_run"])`。
  - `tools.run` 回 `Completed(None, "", "", "missing")`。
  - `orca` 的每個函式回 `Problem("transport_missing")`。
  - `native.find_*` 回 `Found(None, "native_not_found")`；`read_*` 回空的 `Session`；`judge_negative` 回 `Item(False, "not_attempted", …)`。
- **`preflight` 命令**：
  - `cli.py` 加 parser（`--repo`、`--feature`、`--role {implementer,reviewer}`、`--out`）與 handler；
  - `preflight.py` 做 DD-4 的第 1、3 步：政策未核准就 `policy_not_approved`；其餘情況回 exit 3、`ok: false`、`blocked: {kind: "preflight_unverified", role, reasons: []}`。

**擁有路徑**：上列各檔，`tests/test_harness.py`、`tests/test_policy.py`、`tests/test_test_policy.py`（只改 `child` fixture，見共用檔案表）。

**依賴**：無（Feature 1 的程式已在 main）。

**AC**：D30（preflight 拒絕的部分）。

**Commit**：

- `build: make pyyaml a runtime dependency`
- `test: isolate external tools behind scenario-driven fakes`
- `feat(policy): read workflow profiles once with their digest`
- `feat(preflight): refuse to probe without an approved policy`

`tests/test_harness.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_fake_tool_replays_the_scenario_and_logs_argv` | scenario `{orca: [{match: ["--version"], stdout: "9.9.9\n"}]}` 下執行 `orca --version`：stdout 是 `9.9.9`、exit 0；`fakes.calls()` 恰好一筆 `{tool: "orca", argv: ["--version"]}` | fake 腳本先寫成回空字串：stdout 的比較不成立 | 通過 |
| `test_unexpected_call_fails_the_test_at_teardown` | 以 `pytester` 子程序（外層 PATH 為 `minbin/` 與 `sentinel/`）執行一個呼叫 `orca worker-start` 的內層測試（沒有 scenario）：fake exit 97；內層測試在 teardown 失敗，訊息含 `unexpected` 與該 argv | teardown 先不檢查：內層結果的斷言（應為 1 個 error）不成立 | 通過 |
| `test_real_tools_are_never_reached` | 以 `pytester` 在子程序執行內層測試，外層 PATH 只含 `minbin/` 與 `sentinel/`（DD-10）。內層測試先斷言 `shutil.which("orca")`、`which("claude")`、`which("codex")` 都在 `fakebin/` 之下，再執行三個 `--version`，輸出是 DD-10 的預設版本 | 先不建 autouse 隔離：`which` 解析到 `sentinel/`，內層斷言失敗，外層「內層為 1 passed」的斷言不成立。真實工具不在 PATH 上，不會被呼叫 | 通過 |
| `test_without_removes_the_tool_from_path` | 同樣以 `pytester` 子程序、外層 PATH 為 `minbin/` 與 `sentinel/`。內層 `fakes.without("claude")` 之後，`shutil.which("claude") is None`；`git` 與 `sh` 仍找得到 | 先只刪 fake 檔、不換 PATH：`which("claude")` 解析到 `sentinel/claude`，內層斷言失敗 | 通過 |
| `test_capture_substitution_and_effects` | scenario 擷取第一次呼叫 argv 中 `--title` 的值，第二次呼叫的 stdout 與 `write` effect 的檔名都以它代換；`state` effect 讓後續 `ps` 的輸出改變；`snapshot` 把指定目錄的檔案清單記進 `FAKE_LOG`；標 `repeat: true` 的項目被呼叫三次都回同樣的輸出；scenario 有列其他呼叫時，`--version` 的預設回應仍在 | 先不做代換：stdout 的比較不成立 | 通過 |
| `test_kill_parent_interrupts_the_caller` | 以 `cli_proc` 執行一個會呼叫 fake 的子程序（prelude 以 `subprocess.run(["orca", "x"])` 呼叫），scenario 對 `x` 設 `kill_parent`：子程序的 returncode 是 `-9` | 先不實作 `kill_parent`：returncode 的比較不成立 | 通過 |
| `test_clock_sleep_advances_fake_time` | `clock` fixture 下 `clock.sleep(5)`，之後 `clock.now()` 比之前多 5 秒；整個測試在 1 秒內結束 | `clock.sleep` 先不推進：時間差的比較不成立 | 通過 |
| `test_probe_repo_offers_linked_and_independent_workspaces` | `probe_repo(reviewer="linked")` 時，兩個工作區的 `git rev-parse --path-format=absolute --git-common-dir` 相同；`reviewer="clone"` 時不同；兩者的 `origin` 都是同一個 bare repo | fixture 先都用 linked：`clone` 那一列的比較不成立 | 通過 |
| `test_calls_follow_the_scenario_order` | 逐 task 審查 T1.1-02 的回歸測試。以 `pytester` 子程序（外層 PATH 為 `minbin/` 與 `sentinel/`）執行兩個內層測試，scenario 都是 `orca: [terminal create, orchestration worker-start]`：依序呼叫兩者都回各自的 stdout；先呼叫 `worker-start` 時 fake exit 97，該內層測試在 teardown 失敗，訊息含 `unexpected` 與該 argv。外層斷言內層為 2 passed、1 error，error 是 `test_out_of_order` 的 teardown | fake 在所有未用過的項目中找第一個相符的，`worker-start` 越過 `terminal create` 而回 exit 0：內層結果的斷言（應為 2 passed、1 error）不成立 | 通過 |

`tests/test_policy.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_profiles_are_parsed_with_the_file_digest` | DD-2 範例檔：兩個 profile 的欄位逐一相等；`digest == "sha256:" + sha256(bytes)`；`timeout_s == 900`；`errors == []` | `load` 先回空的 `profiles`：欄位比較不成立 | 通過 |
| `test_profile_missing_fields_is_invalid_not_an_error` | 拿掉 Reviewer 的 `model`：`load` 不拋例外；Reviewer 的 `invalid == ["model"]`，Implementer 的 `invalid == []`。另以 `runtime: opencode` 測：`invalid` 含 `runtime` | `invalid` 先永遠是空清單：比較不成立 | 通過 |
| `test_missing_profiles_and_roles_are_not_errors` | 沒有 `profiles` 鍵：`errors == []`、`profiles` 的兩個 role 都是 `invalid == ["profile_missing"]`；只有 implementer：reviewer 是 `profile_missing`；Codex profile 的 `exclude.plugins: ["pdf"]`：該 profile 的 `invalid == ["exclude_plugins_unsupported"]`，空清單時是 `[]` | 先把缺少的鍵當成 `profiles_not_a_mapping`：`errors` 的比較不成立 | 通過 |
| `test_malformed_policy_is_reported_not_raised` | 參數化：YAML 語法錯誤、頂層是 list、`profiles` 是字串、`timeout_s: -1`、檔案不存在。各自的 `errors` 是 `["yaml_error"]`、`["not_a_mapping"]`、`["profiles_not_a_mapping"]`、`["timeout_invalid"]`、`["unreadable"]`；`timeout_s == 900`；前四種的 `digest` 是 bytes 的 sha256，最後一種是 `None` | 先只處理正常檔案，錯誤情況回空的 `errors`：`errors` 的比較不成立 | 通過 |
| `test_preflight_refuses_without_an_approved_policy` | 參數化四種：登記了但沒核准、核准後檔案被改、沒有登記、檔案讀不到。`preflight --role implementer` 都是 exit 1、`error == "policy_not_approved"`、`policy` 欄等於 `policy_view` 的狀態；`fakes.calls()` 是空的；`$LOOPCTL_HOME/repos` 下沒有 `receipts/` | handler 先一律回 exit 3：exit 的比較不成立 | 通過 |
| `test_approved_policy_is_not_refused` | 核准的政策：exit 不是 1，`error` 不是 `policy_not_approved` | 突變：把核准判定反過來，`error` 的比較不成立 | 通過 |
| `test_unconstructible_scalar_is_a_yaml_error` | 逐 task 審查 T1.1-01 的回歸測試。DD-2 範例檔加上 `created_at: 2026-99-99`：語法正確，但 PyYAML 建構日期時丟 `ValueError`。`load` 不拋例外；`errors == ["yaml_error"]`；`digest` 是 bytes 的 sha256；`timeout_s == 900` | `load` 只攔 `yaml.YAMLError`，`ValueError` 穿出：「沒有拋例外」的斷言不成立 | 通過 |
| `test_unapproved_unconstructible_policy_is_refused` | T1.1-01 的回歸測試。同一份檔案登記了但沒核准：`preflight --role implementer` 沒有未攔截的例外（`Result.exc is None`）、exit 1、`error == "policy_not_approved"`、`policy == "not_approved"`；`fakes.calls()` 是空的 | 突變：`preflight.approved_policy` 不經 `policy.load`，自己讀檔並以裸 `yaml.safe_load` 解析（`policy.load` 不動，上一列仍 Green），`ValueError` 穿過 `guarded`：`r.exc is None` 的斷言不成立 | 通過 |
| `test_profile_values_that_are_not_json_make_it_invalid` | 逐 task 審查 T2.1-02 的回歸測試。每個 receipt 都帶 profile 與它 canonical JSON 的 digest（DD-2、DD-8），所以 `load` 回傳的 `fields` 必須是純 JSON 資料。參數化：DD-2 範例檔的 Implementer profile 另加 `notes: 2026-10-03`（日期）、`!!binary` 值、`!!set` 值、同時有字串鍵與整數鍵的 mapping、只有整數鍵的 mapping、`.nan`、`.inf`。各自 `errors == []`；Implementer 的 `invalid == ["profile_not_json"]`、`fields == {}`；Reviewer profile 等於同一份檔案不加該值時的結果 | `_invalid` 只查 DD-2 列出的欄位，多出的欄位照樣通過：每一列都是 `invalid` 的比較不成立（`[] != ["profile_not_json"]`） | 通過 |
| `test_aliases_are_json_unless_a_value_holds_itself` | T2.1-02 的回歸測試。anchor 用在自己的值裡時，safe_load 建出包含自己的容器，JSON 寫不出來。參數化：Implementer profile 另加 `notes: &notes {again: *notes}`、`notes: &notes [*notes]`：`load` 不拋例外，`errors == []`，Implementer profile 是 `Profile("implementer", {}, ["profile_not_json"])`；`notes: [&notes [a], *notes]`（同一個 list 用兩次，沒有包含自己）：profile 照常有效，`fields` 是範例欄位加 `notes == [["a"], ["a"]]`、`invalid == []`。三列的 Reviewer profile 都等於不加該值時的結果 | 上一列 Green 的檢查逐層遞迴、不記得走過的容器，包含自己的兩列 `RecursionError` 穿出 `load`：「沒有拋例外」的斷言不成立；用兩次的那一列通過 | 通過 |
| `test_deep_alias_chains_are_not_json` | 逐 task 審查 T1.1-04 的回歸測試。alias 能以很淺的文字建出很深的值。參數化：頂層 `a0: &a0 [*a0]`、`a{i}: &a{i} [*a{i-1}]`（i = 1..1200）並以 `notes: *a1200` 用在 Implementer profile（結尾是循環）；同樣的 1200 個 alias 但 `b0: &b0 []`（沒有循環）。各自 `load` 不拋例外，`errors == []`；Implementer 的 `invalid == ["profile_not_json"]`、`fields == {}`；Reviewer profile 等於同一份檔案不加 `notes` 時的結果 | 判定 `profile_not_json` 的檢查每層遞迴一次，兩列都是 `RecursionError` 穿出 `load`：「沒有拋例外」的斷言不成立 | 通過 |
| `test_profile_depth_bound` | T1.1-04 的回歸測試。receipt 的 JSON 寫法每層也遞迴一次，所以 profile 的巢狀深度有固定上限 `policy.MAX_DEPTH`（profile 本身是第 1 層）。以一般的 YAML flow 寫法（不用 alias）：`notes` 的巢狀恰好到上限時 `invalid == []`；再深一層時 `errors == []`、`invalid == ["profile_not_json"]`、`fields == {}` | 上限還不存在（Red 時測試以字面值 32 代替常數）：深一層那份的 `invalid` 是 `[]`，比較不成立 | 通過 |

## 2. Receipt 與不需派 worker 的判定

- [x] 2.1 repo 層級的 receipt 與探測紀錄、verdict 與 exit、profile 與環境的判定、未選用接入、`--out`；驗證：`uv run pytest tests/test_preflight_static.py tests/test_receipts.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `store.py`：實作 `append_record`（`O_CREAT|O_EXCL`、fsync、撞號換下一號）、`list_records`（略過不完整的紀錄並回報檔名）、`locked_dir`（`flock` 非阻塞，拿不到時丟 `Busy`）（DD-8）。
- `receipts.py`：
  - `write(repo, role, receipt) -> ref`：`put_object` 加索引紀錄；
  - `latest(repo, role) -> Receipt | None`：讀回時以 `get_object` 核對 digest，不符丟 `ReceiptCorrupt`。
- `tools.py`：實作 `run`（DD-1）。
- `orca.py`：
  - 實作 `version()`、`status()`、`run_current()`、`run_create(objective)`、`repos()`、`worktrees()`；
  - 輸出不是預期的 JSON 時回 `Unparseable(cmd)`，不丟例外。
- `preflight.py`：
  - DD-4 的第 0、4、5 步與第 13 步；
  - verdict 是逐項的 AND，還沒判定的項目不放進 `items`；
  - exit 0／3 與 `blocked`（DD-3）；
  - `policy_invalid`；
  - `--out` 寫出同一份 receipt。

  第 6 步以後的項目由 3.1 起加入。在那之前，環境齊全的 preflight 以原因 `probe_not_available` 結束；這個原因只出現在 2.1 的 head，不被任何測試斷言。
- `cli.py`：`preflight` 的 handler 包進 `guarded`；`Busy` 對應 exit 1 `preflight_running`。

**擁有路徑**：上列各檔，`tests/test_receipts.py`、`tests/test_preflight_static.py`、`tests/fakes/scenarios.py`（新增 `environment(...)`：Orca 環境齊全的查詢回應，並對 `terminal create` 回失敗，讓之後的 task 加入探測時這些測試仍停在第 8 步）。

**依賴**：1.1，從它取得：

- `policy.load(path) -> Policy`：不丟例外，以 `errors` 與 `invalid` 表達問題（DD-2）。
- fixture：`fakes`、`orca_env`、`clock`、`approved_run`、`probe_repo`，以及工具隔離。
- 新模組的函式簽名，本 task 只換實作，不改簽名。

**AC**：D19（缺必要設定、環境不存在）、D23、G23、D29（preflight 不改 feature 狀態）。

**Commit**：

- `feat(store): add write-once records outside run state`
- `feat(receipts): keep the latest preflight receipt per repo and role`
- `feat(preflight): judge profiles and environment before any probe`

`tests/test_receipts.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_records_are_write_once_and_ordered` | 連續 `append_record` 三次：編號 1、2、3，內容依序讀回；寫一個不完整的 `4.json` 後，`list_records` 的 `items` 是三筆、`skipped == ["4.json"]` | 1.1 的 stub 不寫檔：筆數的比較不成立 | 通過 |
| `test_latest_receipt_wins_and_reads_back_by_digest` | 依序寫入 verified、unverified 兩份：`latest` 是 unverified 那份；兩份都在 `objects/`，內容的 sha256 等於索引裡的 ref | 1.1 的 stub `latest` 回 `None`：verdict 的比較不成立 | 通過 |
| `test_tampered_receipt_is_reported_not_trusted` | 參數化：(a) 改動最新 object 的內容；(b) 刪掉最新 object；(c) `receipts/` 多一個編號更大、內容不完整的索引檔。三種的 `latest` 都丟 `ReceiptCorrupt`，訊息含該 ref 或檔名；(c) 不退回較舊的那份 | 先不核對 digest：(a) 的 `pytest.raises` 斷言不成立 | 通過 |
| `test_roles_keep_separate_latest_receipts` | Implementer 寫 verified、Reviewer 寫 unverified：兩個 role 的 `latest` 各自是自己的 | 突變：把兩個 role 的索引目錄寫成同一個，`latest` 的比較不成立 | 通過 |
| `test_misnumbered_index_record_is_not_trusted` | 逐 task 審查 T2.1-01 的回歸測試。參數化：(a) `1.json` 是 `{seq: 2, receipt: <完好的 verified ref>}`，另有不完整的 `2.json`（`{`）：`latest` 丟 `ReceiptCorrupt`，訊息含 `2.json`，不退回 `1.json` 那份；(b) 只有這個 `1.json`：`latest` 丟 `ReceiptCorrupt`，訊息含 `1.json`。兩種的 `list_records` 都把 `1.json` 列在 `skipped`：檔名的編號決定順序，存的 `seq` 與檔名不符的紀錄當成讀不了的紀錄（DD-8） | `latest` 以紀錄裡存的 `seq` 判斷讀不了的檔案是否較新，回傳 `1.json` 的 receipt：兩列的 `pytest.raises` 斷言都不成立 | 通過 |

`tests/test_preflight_static.py`（都用 `approved_run`、`orca_env` 與 `environment(...)` scenario）：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_invalid_profile_is_unverified_without_calling_tools` | 參數化：Implementer 缺 `model` → `reasons == ["profile_invalid:model"]`；政策只有 implementer，跑 Reviewer → `reasons == ["profile_missing"]`。都是 exit 3、`fakes.calls()` 是空的、`latest` 是這份 unverified | 1.1 的 handler 的 reasons 是空清單：reasons 的比較不成立 | 通過 |
| `test_malformed_approved_policy_is_unverified` | 已核准的政策檔本身 YAML 壞掉（核准的就是這份 bytes）：exit 3，`reasons == ["policy_invalid:yaml_error"]`，不呼叫任何工具 | 先只看 profile 欄位：reasons 的比較不成立 | 通過 |
| `test_same_model_makes_the_reviewer_unverified` | 兩個 profile 的 model 相同（effort 不同）：Reviewer 的 preflight exit 3，`reasons` 含 `model_not_distinct`，`items["model.distinct"].passed is False`；Implementer 的 preflight 不因此出現這個原因 | 先不比較 model：reasons 的比較不成立 | 通過 |
| `test_missing_selected_tools_block_the_profile` | 參數化：(a) `fakes.without("orca")`；(b) `orca status` 的 `runtime.reachable` 是 false；(c) `fakes.without("claude")`；(d) 沒有 `ORCA_TERMINAL_HANDLE`；(e) `orca repo list` 沒有 remote identity 相符的 git repo；(f) 找不到 `preflight-engineer` 工作區；(g) 兩個相符的 repo 都有 `preflight-engineer`；(h) `orca status` 回非 JSON；(i) `~/.claude/settings.json` 不存在；(j) 它不是 JSON；Reviewer 另有：(k) 找不到 `preflight-engineer`；(l) 有兩個；(m) implementer profile 缺 `model`。每一種都 exit 3，`reasons` 只含該項的原因：`transport_missing`、`transport_unreachable`、`runtime_missing`、`not_in_orca_terminal`、`repo_not_registered`、`workspace_not_found`、`workspace_ambiguous`、`unparseable:orca status`、`user_settings_unreadable`、`user_settings_unreadable`、`implementer_workspace_not_found`、`implementer_workspace_ambiguous`、`implementer_profile_invalid`。`environment(...)` 的 Orca 回應以 `samples/orca/` 的實際 JSON 為範本 | 先只檢查政策：reasons 的比較不成立 | 通過 |
| `test_reviewer_clone_with_the_same_remote_is_found` | Orca 有兩個 git repo（作者 repo 與 Reviewer 的獨立 clone），remote identity 相同；`preflight-reviewer` 只在 clone 裡：Reviewer 的環境檢查找到它，`reasons` 不含 `workspace_not_found` | 突變：改成只找路徑等於作者 repo 的那一個，reasons 的比較不成立 | 通過 |
| `test_unselected_tools_are_never_called` | 環境齊全時跑 Implementer 的 preflight：`fakes.calls()` 中沒有 `herdr`、`opencode`、`codex`；跑 Reviewer 的 preflight：沒有 `herdr`、`opencode`、`claude` | 突變：在環境檢查加一個 `opencode --version`，呼叫紀錄的斷言不成立 | 通過 |
| `test_no_run_is_created_when_one_is_bound` | `run-current` 回既有的 Run：不呼叫 `run-create`；沒有綁定時呼叫一次 `run-create`，之後的檢查用它回傳的 id | 先總是呼叫 `run-create`：呼叫紀錄的比較不成立 | 通過 |
| `test_out_writes_the_same_receipt` | `--out <path>`：檔案內容的 sha256 等於 `result.receipt` 的 ref。`--out` 指向不可寫的目錄：exit 6、`error == "io_error"`、`op == "write_out"`、`committed is True`，而且 `latest` 是這份 receipt | 先不寫 `--out`：檔案存在的斷言不成立 | 通過 |
| `test_preflight_never_changes_the_feature_state` | 任一 preflight 前後，`feature.json` 的 bytes 與 revision 都不變，history 沒有新檔 | 突變：讓 preflight 在結束時 `commit` 一筆 transition，bytes 的比較不成立 | 通過 |
| `test_concurrent_preflight_for_one_role_is_refused` | 以 `cli_proc` 執行：prelude 先建立該 role 的目錄，以另一個 file descriptor 對 `lock` 取 `flock(LOCK_EX)` 並保持開啟；同一個程序接著執行的 preflight 就是第二個（flock 以 open file description 為單位，同一程序的第二個 fd 也拿不到）。結果 exit 1、`error == "preflight_running"`，沒有新的 receipt | stub 的 `locked_dir` 不取鎖：exit 的比較不成立 | 通過 |
| `test_run_current_without_its_run_creates_no_run` | 逐 task 審查 T2.1-03 的回歸測試。`run-current` 回 `{ok: true, result: {}}`（沒有 `run` 鍵），scenario 仍備有 `run-create` 的回應：不呼叫 `run-create`；exit 3、unverified，`reasons == ["unparseable:orca orchestration run-current"]`。只有明確的 `run: null` 代表沒有綁定的 Run（DD-1、DD-4 第 5 步） | `run_current` 把缺 `run` 鍵當成沒有綁定而回 `None`，preflight 呼叫一次 `run-create`：「沒有 `run-create` 呼叫」的斷言不成立 | 通過 |
| `test_malformed_orca_identifiers_are_unparseable` | T2.1-03 的回歸測試。參數化：(a) `repo list` 中 remote identity 相符的 git repo 的 `id` 是 `[]`；(b) `worktree list` 中 `preflight-engineer` 的 `repoId` 是 `[]`。都沒有未攔截的例外（`Result.exc is None`）；exit 3、unverified，`reasons` 分別是 `["unparseable:orca repo list"]`、`["unparseable:orca worktree list"]`；`latest` 是這份 receipt。Orca adapter 檢查 preflight 讀取的欄位都是字串：repo 的 `id`、`kind`、`gitRemoteIdentity.canonicalKey`（folder repo 沒有 `gitRemoteIdentity`），工作區的 `id`、`repoId`、`path`、`displayName`、`branch`（DD-1） | 兩列都在 preflight 以 `id` 或 `repoId` 做集合運算時丟 `TypeError: unhashable type: 'list'`，沒有寫 receipt：`r.exc is None` 的斷言不成立 | 通過 |

## 3. Implementer 探測

- [x] 3.1 marker 與探測紀錄、啟動 Claude、worker-start、等待、讀回、版本、停止與 `worker_done`；驗證：`uv run pytest tests/test_preflight_claude.py`

**模式與 effort**：預設模式；high／xhigh。

**交付**：

- `preflight.py`：DD-4 第 6～12a 步的 Claude 部分：
  - DD-5 的設定檔與命令文字；
  - 探測任務的文字（共 7 步）；
  - DD-7 的等待與停止。
- `orca.py`：`terminal_create`、`worker_start`、`worker_show`、`terminal_wait`、`terminal_close`、`task_list`。
- `native.py`：
  - Claude transcript 的搜尋：恰好一份含 marker、檔名等於 uuid；
  - 讀回、turn 是否完成。
- 本 task 結束時：
  - 負例與 `settings.excluded` 兩類 item 還沒有實作，不放進 `items`；
  - verdict 一律加上原因 `judgement_incomplete`，所以不可能 verified。
- `tests/fakes/scenarios.py`：新增 `claude_probe(...)`。
  - 產生完整的 Orca 對話，並在 `terminal create` 時寫出 transcript。
  - transcript 依 research 樣本的欄位與順序；每一步的結果可設定。

**擁有路徑**：上列各檔，`tests/test_preflight_claude.py`。

**依賴**：2.1，從它取得：

- `receipts.write`／`latest`：同一 role 以最新一份為準，讀回時核對 digest。
- `tools.run(argv, timeout_s) -> Completed`：執行檔不存在時回 `status == "missing"`，不丟例外。
- `orca` 的環境查詢與 `Unparseable`。
- `locked_dir` 與 exit 0／3 的 envelope；第 0～5 步與它們的原因名稱。

**AC**：D18、D19（任務、回報、停止）。

**Commit**：`feat(preflight): probe the Claude profile through an Orca terminal`

`tests/test_preflight_claude.py`（本 task 的部分）：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_probe_passes_launch_readback_and_stop_items` | 全部成立的 `claude_probe`：`readback.model`、`readback.effort`、`placement.cwd`、`placement.repo`、`placement.branch`、`permission.mode`、`positive.inside_write`、`task.accepted`、`task.worker_done`、`stop.confirmed`、`version.consistent` 都 `passed`；receipt 含 `marker`、`native_session_id`、`orca.dispatch`、`versions.native == "2.1.288"`。第 6 步的探測檔在 preflight 結束後仍在工作區，路徑在 `positive.inside_write` 的 `evidence`。本測試不斷言 verdict | 2.1 在第 5 步之後就結束，這些 item 不存在：比較不成立 | 通過 |
| `test_launch_command_and_settings_are_fixed` | `terminal create` 的 `--command` 依序含 `PREFLIGHT_MARKER=<marker>`、`PATH=<shlex.quote(dir)>:$PATH`（`dir` 是 `Path(sys.executable).parent`，`$PATH` 沒有被引號包住）、`claude --model claude-opus-5-5 --effort high --session-id <uuid>`、`--setting-sources project,local`、`--settings <path>`、`--permission-mode dontAsk`。設定檔的權限是 0600，內容：`hooks` 只含命令中有 `ORCA_AGENT_HOOK` 的 hook；`enabledPlugins` 只有 superpowers；`allow` 含精確字串 `Edit(//<realpath(工作區)>/**)` 與三個 `orca orchestration` 規則 | 先照抄全部 hook：hook 數量的比較不成立 | 通過 |
| `test_versions_are_normalised_from_real_outputs` | fake 的 `claude --version` 輸出 `2.1.288 (Claude Code)`、`orca --version` 輸出 `1.4.218`，transcript 的 `version` 是 `2.1.288`：`version.consistent` 成立，receipt 的 `versions` 是 `{transport: "1.4.218", agent_cli_before: "2.1.288", agent_cli_after: "2.1.288", native: "2.1.288"}` | 先保存原始字串：`agent_cli_before == "2.1.288"` 的比較不成立 | 通過 |
| `test_marker_is_recorded_before_the_terminal_exists` | scenario 在 `terminal create` 上加 `snapshot`（role 的 `probes/`）：快照含 `started` 那筆紀錄。`probes/` 依序是 `started`、`terminal`、`dispatch`、`closed` | 先在拿到 handle 後才寫 `started`：快照的斷言不成立 | 通過 |
| `test_readback_mismatch_fails_the_item` | 參數化，每一列斷言對應 item 的 `passed is False` 與 `required`、`actual`、`reason`：model 是 `claude-sonnet-5`；effort 是 `medium`；cwd 是另一個目錄；branch 是另一個；cwd 的 toplevel 是另一個 repo；transcript 沒有 effort 欄位（`actual: null`）；沒有 cwd 欄位（`actual: null`）。另外四列走 DD-4 的「terminal 建立之後的問題」路徑（`terminal wait` 以 `repeat` 回 timeout，`timeout_s` 為 60）：只有 prompt、沒有 assistant → 讀回各項 `reason == "no_native_turn"`；沒有任何含 marker 的檔案 → `native_not_found`；兩份 → `native_ambiguous`；檔名不等於 uuid → `native_name_mismatch`。這四列的 `stop.confirmed` 仍成立。另外三列確認搜尋範圍：修改時間早於 `started` 紀錄檔的舊 transcript 也含 marker → 不算，仍只有一份；`subagents/` 下的檔案含 marker → 不算；marker 也出現在 `ai-title` 紀錄（在 user 紀錄之前）→ `placement.cwd` 仍取自 user 紀錄，成立 | 先不比對、一律成立：該列 item 的 `passed` 比較不成立 | 通過 |
| `test_version_must_match_the_running_agent` | 參數化：(a) `claude --version` 前後都是 2.1.289，transcript 的 `version` 是 2.1.288；(b) 前值 2.1.288、後值 2.1.289。兩種的 `version.consistent` 都不成立，原因 `agent_version_mismatch`，並列出三個值 | 先只記錄不比較：item 的比較不成立 | 通過 |
| `test_task_not_reported_fails_worker_done` | worker 沒有送 `worker_done`（`worker-show` 的 status 仍是 `dispatched`）：`task.worker_done` 不成立；terminal 仍被關閉並確認 | 先以 transcript 的完成當作 `worker_done`：item 的比較不成立 | 通過 |
| `test_stop_must_be_confirmed_by_process_info` | `terminal close` 之後 fake `ps` 仍列出 marker：呼叫順序是 `terminal close`，然後 10 組「`clock.sleep(0.5)`、`ps`」；`stop.confirmed` 不成立；`probes/` 沒有 `closed`，最後一筆是 `stop_unconfirmed`。另一列：第 3 次 `ps` 不再列出 → 只有 3 組，`stop.confirmed` 成立 | 先以 `terminal close` 的 `ptyKilled` 為準：item 的比較不成立 | 通過 |
| `test_probe_timeout_still_stops_the_worker` | `terminal wait` 都回 timeout，transcript 一直沒完成，政策的 `timeout_s` 為 60：假時間超過 60 秒後 `reasons` 含 `probe_timeout`；`terminal close` 仍被呼叫，`stop.confirmed` 成立 | 突變：逾時時略過第 11、12 步直接寫 receipt，`terminal close` 的呼叫斷言不成立（前一列已要求逾時後停止，所以這裡不是新行為；本列另外斷言 `reasons` 含 `probe_timeout`） | 通過 |
| `test_wait_failure_stops_waiting_at_once` | transcript 始終沒有完成的 turn（只有 prompt），`terminal wait` 以 `repeat: true` 一直回非 timeout 的錯誤（terminal 已結束），政策的 `timeout_s` 為 60：只呼叫一次 `terminal wait`，`reasons` 含 `wait_failed:<reason>`；第 11、12 步照樣執行，`stop.confirmed` 成立 | 先把錯誤當 timeout 繼續等：會一直等到假時間超過 60 秒，`terminal wait` 被呼叫多次，呼叫次數的斷言不成立 | 通過 |
| `test_worker_start_failure_reports_the_stage` | `worker-start` exit 1，JSON 的 `failedStage: "agent_readiness"`：`reasons` 含 `task_not_started:agent_readiness`；terminal 仍被關閉 | 先忽略 exit：reasons 的比較不成立 | 通過 |
| `test_probe_is_not_verified_until_judgement_is_complete` | 全部成立的 scenario 下，verdict 是 unverified，`reasons == ["judgement_incomplete"]`。3.2 會刪掉它（見 3.2） | 突變：拿掉 `judgement_incomplete`，verdict 的比較不成立 | 通過 |
| `test_terminal_record_failure_still_stops_the_worker` | 逐 task 審查 T3.1-01 的回歸測試。參數化：scenario 以 `dispatched=False` 省去探測走不到的 worker-start、等待與 worker-show；測試端包裝 `orca.terminal_create`，呼叫原函式後把 `probes/` 改成不可寫，`terminal` 紀錄在 store 寫不出（真的 `EACCES`）。(a) 測試端包裝的 `orca.terminal_close` 在關閉後讓它恢復可寫；(b) 不恢復，stop 的紀錄也寫不出；(c) 恢復，但 stop 的紀錄以另一個錯誤（`EIO`，測試端替換 `store.append_record`）失敗。三列都斷言：`terminal close` 恰好呼叫一次，之後有 `ps`；沒有未捕捉的例外；exit 6、`io_error`、`op == "write_record"`、`errno == "EACCES"`（原本的失敗）；`probes/` 依序是 (a) `started`、`closed`，(b)(c) 只有 `started` | d223714 在 `try` 之前寫 `terminal` 紀錄：`terminal close` 的呼叫次數比較不成立。另以突變證明 (c)：stop 的失敗不吞掉，`errno` 的比較不成立 | 通過 |
| `test_unreadable_native_file_fails_the_readback` | 逐 task 審查 T3.1-02 的回歸測試。參數化，`terminal wait` 以 `repeat` 回 timeout，`timeout_s` 為 60：(a) 探測的 `<uuid>.jsonl` 存在但讀不到；(b) 探測的 transcript 可讀且含 marker，另一個專案有一份修改時間晚於 `started`、讀不到的 session 檔；(c) 另一個專案的目錄可列出但不能 stat 其中的檔（修改時間未知，不算已知在範圍外）；(d) 另一個專案的目錄列不出。每一列：讀回各項 `passed is False`、`actual is None`、`reason == "native_unreadable"`；`terminal close` 恰好一次，`stop.confirmed` 成立；verdict 是 unverified。修改時間早於 `started` 或在 `subagents/` 下的檔照舊不在範圍內（見 `test_readback_mismatch_fails_the_item`） | d223714 吞掉 `OSError`：(a) 的 `reason` 是 `native_not_found`，(b)(c)(d) 的讀回項 `passed`，比較不成立 | 通過 |
| `test_hidden_projects_are_in_the_search_scope` | 逐 task 審查 T3.1-03 的回歸測試。DD-6 的範圍 `$HOME/.claude/projects/*/*.jsonl` 不排除以點開頭的名字。參數化，`terminal wait` 以 `repeat` 回 timeout，`timeout_s` 為 60，探測的 transcript 可讀且含 marker：(a) 名字以點開頭的專案目錄有第二份修改時間晚於 `started`、含 marker 的 transcript → `native_ambiguous`；(b) 這樣的專案有一份修改時間晚於 `started`、讀不到的 `.jsonl` → `native_unreadable`；(c) 探測的專案裡有一份名字以點開頭、修改時間晚於 `started`、含 marker 的 session 檔 → `native_ambiguous`。每一列：讀回各項 `passed is False`、`actual is None`、`reason` 如上 | 17f8e8d 略過以點開頭的名字：讀回項 `passed`，比較不成立 | 通過 |

- [x] 3.2 Claude 的權限負例、載入的設定、摘錄與遮蔽；全部成立才 verified；驗證：`uv run pytest tests/test_preflight_claude.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `native.py`：
  - 依 DD-6「拒絕的判準」找出每個負例的 `tool_use` 與配對的 `tool_result`；
  - 判定嘗試、拒絕、資源；
  - `settings.excluded` 的判讀。
- `preflight.py`：
  - DD-6 的資源前值與後值；
  - 摘錄（固定欄位）與 `native_digest`；
  - `redact()`，套用到 receipt、`--out`、探測紀錄；
  - 拿掉 `judgement_incomplete`。
- `tests/test_preflight_claude.py`：刪掉 3.1 的 `test_probe_is_not_verified_until_judgement_is_complete`，加入下表的測試。
- `tests/fakes/scenarios.py`：`claude_probe` 新增參數，可設定每個負例的結果、載入的設定與注入的憑證；預設值不變。

**擁有路徑**：上列各檔。

**依賴**：3.1，從它取得：

- `claude_probe(...)` scenario；
- `native.find_claude(marker, uuid)`，含「恰好一份」的判定；
- 探測任務的 7 個步驟與它們的固定文字；
- receipt 的 `items` 結構與 `probes/` 紀錄。

**AC**：D27、D28、D29。

**Commit**：`feat(native): judge Claude permission denials from the transcript`

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_full_probe_is_verified` | 全部成立的 scenario：exit 0、`verdict == "verified"`、`reasons == []`；每一項 `passed` | 3.1 的 `judgement_incomplete`：verdict 的比較不成立 | 通過 |
| `test_negative_outcomes_follow_the_judgement_table` | 依 DD-6「拒絕的判準」的表參數化：每個負例 × 表中列出的可能結果，不展開不適用的組合。只有「被拒」讓該項成立；其他結果該項不成立，`reason` 是 `not_attempted`、`executed` 或 `resource_changed` | 突變：把「沒嘗試」也判成立，該列的比較不成立 | 通過 |
| `test_only_permission_rule_denials_count` | `toolDenialKind` 是 `user-rejected` 或 `interrupted`，或 `tool_result` 的 `tool_use_id` 配不到：該項不成立，`reason == "not_a_runtime_denial"` | 先只檢查 `toolDenialKind` 存在：該列的比較不成立 | 通過 |
| `test_worker_self_report_is_not_a_denial` | 最後的文字寫「all steps denied」，但 `git push` 那一步沒有 `toolDenialKind`：`negative.git_push` 不成立 | 突變：改成讀最後文字判定，item 的比較不成立 | 通過 |
| `test_other_tasks_in_the_run_do_not_affect_the_orca_check` | `task-list` 在前後都含其他 Task（另一個 role 的探測、協調者自己的 Task），而且後值比前值多 2 個；沒有 spec 為 `probe <s>` 的 Task：`negative.orca` 成立 | 突變：改成比較 Task 數，item 的比較不成立 | 通過 |
| `test_excluded_settings_fail_the_item` | fake transcript 依樣本含 13 筆 Orca hook 與 1 筆 superpowers 的 plugin hook（`CLAUDE_PLUGIN_ROOT`）→ `settings.excluded` 成立。參數化：`skill_listing` 出現 `ponytail:` 開頭的 skill；多一筆 caveman hook（命令既不含 `ORCA_AGENT_HOOK` 也不含 `CLAUDE_PLUGIN_ROOT`）。每一種都不成立。receipt 的 `observed.gateway == {configured: <設定檔的 ANTHROPIC_BASE_URL>, observable: false}` | 突變：讓 `settings.excluded` 不看 `skill_listing`，ponytail 那一列的比較不成立 | 通過 |
| `test_credentials_are_redacted_everywhere` | transcript 含 `dcap_abc123def456`、`sk-ant-0123456789abcdefXYZ`、`Bearer abc.def.ghi`、`https://u:p@host/x`；使用者設定的 `env` 有 `ANTHROPIC_AUTH_TOKEN=secret-value`，並列在 `keep.env`。receipt、`--out` 檔、`probes/` 下的檔案都不含這五個原值。`settings/` 下寫給 Claude 的設定檔保留 token 真值，權限是 0600；receipt 裡只有遮蔽過的版本 | 先只遮 `dcap_`：`sk-ant-` 的搜尋斷言不成立 | 通過 |
| `test_receipt_keeps_fixed_excerpts_and_the_native_digest` | 每一項的 `evidence` 都指向 `excerpts` 中存在的 id；摘錄只有 DD-6 列出的欄位（例如沒有 `skill_listing` 的全文，只有名稱清單）；逐類斷言 evidence 指向的摘錄含該項判定的值：`readback.model` 的摘錄含 `claude-opus-5-5`，`negative.git_push` 的含命令與 `toolDenialKind`，`settings.excluded` 的含 skill 名稱與 hook 命令，`version.consistent` 的含 `2.1.288`，`task.accepted` 的 `marker_context` 含 marker；`native_digest` 等於 transcript 檔的 sha256；刪掉 transcript 之後，`latest` 讀回的 receipt 仍有全部摘錄 | 先存整筆紀錄：欄位集合的比較不成立 | 通過 |

## 4. Reviewer 探測

- [ ] 4.1 Codex 的啟動、rollout 讀回、sandbox 拒絕、隔離負例、獨立 clone、Codex 的設定；驗證：`uv run pytest tests/test_preflight_codex.py`

**模式與 effort**：預設模式；high／xhigh。

**交付**：

- `preflight.py`：DD-5 的 Codex 命令文字，以及 Reviewer 的第 8、9 步。
- `native.py`：
  - rollout 的搜尋：`CODEX_HOME`、日期目錄、恰好一份含 marker；
  - 從 `turn_context` 讀回；
  - DD-6 的 Codex 拒絕判準；
  - 以 `task_complete` 判定完成；
  - `settings.excluded` 與 `observed` 的 Codex 欄位。
- `isolation.independent_clone` 的判定。
- `tests/fakes/scenarios.py`：新增 `codex_probe(...)`，欄位依 research 的 Codex 樣本。

**擁有路徑**：上列各檔，`tests/test_preflight_codex.py`。

**依賴**：3.2，從它取得：

- 負例的判定介面：嘗試、拒絕、資源的三段式；
- 資源前值與後值的表；
- `redact()` 與摘錄的固定欄位；
- verdict 規則：全部成立才 verified。

**AC**：G24、D18（Codex）、D27（Codex）、D28（Codex）、D22（兩個 profile 分開保存）、G19（缺口如實保留）。

**Commit**：`feat(native): probe the Codex reviewer profile and its isolation`

`tests/test_preflight_codex.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_codex_launch_avoids_interactive_prompts` | `terminal create` 的命令含 `codex -m gpt-6-astra`、`-c model_reasoning_effort="xhigh"`、精確字串 `-c check_for_update_on_startup=false` 與 `-c features.hooks=false`、`-s read-only`、`-a never`、`--no-daemon`、`PREFLIGHT_MARKER` 與 PATH 前綴 | 3.2 時 Reviewer 以 `runtime_unsupported:codex` 結束，不呼叫 `terminal create`：命令文字的斷言不成立 | 通過 |
| `test_codex_readback_comes_from_turn_context` | rollout 照 research 樣本的順序（`turn_context` 在含 marker 的 user 訊息之前），以 `turn_id` 配對：`gpt-6-astra`、`xhigh`、`read-only`、`never`，cwd 是 Reviewer 工作區 → 讀回與 `permission.mode` 各項成立。參數化：model、effort、cwd 不符；同一 `turn_id` 有 0 筆或 2 筆 `turn_context`（`turn_context_not_found`、`turn_context_ambiguous`）；另一個 turn 的 `turn_context` 寫在 marker 之後、值不同（仍用同 turn 的那筆）；零份、兩份含 marker 的 rollout。對應的 item 照列出的原因不成立 | 還沒有 Codex 讀回時，這些 item 不存在：比較不成立 | 通過 |
| `test_codex_calls_are_parsed_from_the_js_input` | `codex_probe` 依樣本產生三種 `input`：雙引號的 `cmd`、單引號的 `cmd`、以字串串接組出的命令；output 是兩個 `input_text`，第二個是 JSON，Orca 的錯誤 JSON 前面多一行 electron 訊息。前兩種對應到各自的步驟，exit 與輸出讀對；第三種不對應任何步驟 | 前一列 Green 時，`read_codex` 已讀回 `turn_context`，`calls` 仍是空清單（還沒辨識工具呼叫），preflight 正常返回：前兩列「對應到各自的步驟」的斷言不成立 | 通過 |
| `test_codex_rollout_is_found_across_date_boundaries` | 探測開始於本機 00:30（UTC 前一天 16:30），rollout 寫在本機日期的目錄：找得到，`native_not_found` 不出現 | 先只看 UTC 日期：item 的比較不成立 | 通過 |
| `test_codex_denial_must_be_tied_to_the_call` | 依 DD-6 的 Codex 判準參數化：exit 1 且輸出含 `Operation not permitted`、資源未變 → 成立；exit 1 且輸出是樣本第 30 行的 `runtime_access_denied` JSON（`systemCode: EPERM`）→ 成立；exit 0 但輸出含這兩種標記之一 → `executed`；exit 1 但輸出是 `error connecting to api.github.com` → `executed`；標記只出現在另一個呼叫的輸出 → 該項 `executed` | 先只搜尋整份 rollout 的 `Operation not permitted`：`runtime_access_denied` 那一列與最後一列的比較不成立 | 通過 |
| `test_reviewer_cannot_touch_the_implementer_workspace` | 第 8、9 步被拒，Implementer 工作區沒有新檔案，它的 branch ref 前後相同 → `negative.implementer_file`、`negative.implementer_ref` 成立。scenario 的 effect 真的寫入檔案或移動 ref → 該項 `resource_changed` | 先不檢查資源：item 的比較不成立 | 通過 |
| `test_independent_clone_is_judged_by_the_real_git_dir` | `probe_repo(reviewer="linked")` → `isolation.independent_clone` 不成立；`reviewer="clone"` → 成立；另一列從兩個工作區各自的根目錄執行 `git rev-parse --git-common-dir`（不加 `--path-format`，回相對路徑 `.git`），仍判為獨立 | 先比較不加 `--path-format` 的原始輸出：相對路徑那一列的比較不成立 | 通過 |
| `test_codex_settings_are_recorded` | `exclude.plugins` 為空：`settings.excluded` 成立；receipt 的 `observed` 有 `disabled_plugin_ids`、`host_skills` 的名稱、`approved_command_prefixes` 的數量、`permission_profile`，以及 `hooks: {configured: false, observable: false}` | 先不記錄 `observed`：欄位存在的斷言不成立 | 通過 |
| `test_live_probe_shape_is_reproduced` | 照 research P7 的實際結果組 scenario：`git push --dry-run` exit 0；`gh` 的網路錯誤；`orca` 全部 EPERM；`loopctl` exit 127（當時不在 PATH）；沒有 `worker_done`；linked worktree。verdict unverified，`reasons` 恰好是 `negative.git_push:executed`、`negative.gh:executed`、`negative.loopctl:executed`、`task.worker_done`、`isolation.independent_clone`；`negative.orca`、`negative.outside_write`、`negative.implementer_file`、`negative.implementer_ref` 成立 | 突變：把 Codex 判準改成只看 exit code，`negative.gh` 會被判為被拒，`reasons` 的比較不成立 | 通過 |

## 5. 派工管制

- [ ] 5.1 適用判定、目前版本、`next.effective`、`status` 的 profiles、跨 run 共用；驗證：`uv run pytest tests/test_gating.py tests/test_approval.py tests/test_scope_policy.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `receipts.applicable(...)`（DD-9）。
- `preflight.current_versions(runtime)`（DD-1、DD-9）。
- `next.effective(state_next, policy_status, impl)`。
- `cli.status`、`cli.next_step` 依 DD-9 重新判定：
  - envelope 的 `next` 是 `effective` 的結果；
  - `result` 加 `state_next`；`status` 另加 `profiles`；
  - `--human` 兩者都印。
- `state.view`、`state.human` 加對應欄位。
- `test_approval.py:606-633`、`test_scope_policy.py:254-257` 改成：先核准政策，以真的 preflight（`claude_probe` scenario）產生適用的 receipt，再斷言 `dispatch`。

**擁有路徑**：上列各檔，`tests/test_gating.py`，以及兩個既有測試的那幾行。

**依賴**：4.1，從它取得：

- 兩個 role 各自的 `latest`；
- receipt 的 `versions`（含 `native`）與 `policy_digest`；
- `claude_probe`、`codex_probe` scenario：以真的 preflight 產生 receipt，不直接寫檔。

**AC**：D26、D30（`next` 的部分）、D01、D22、D29（跨 run 共用）。

**Commit**：`feat(cli)!: gate dispatch on an applicable preflight receipt`，body 含 `BREAKING-CHANGE:`（共同規則）。

`tests/test_gating.py`：

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_dispatch_needs_an_applicable_implementer_receipt` | 已核准 plan 與政策，Implementer 從未 preflight：`next` 的 envelope `next == {action: "preflight", role: "implementer", reasons: ["not_run"]}`、exit 0；狀態檔的 `next` 仍是 `dispatch`；跑一次 verified 的 preflight 之後，`next` 回 `dispatch` | 4.1 時 `next` 照抄狀態檔：action 的比較不成立 | 通過 |
| `test_receipt_stops_applying_when_anything_changes` | verified 之後，參數化：(a) 新跑一次 unverified；(b) `orca --version` 變成 1.4.219；(c) `claude --version` 變成 2.1.289；(d) `fakes.without("claude")`；(e) 政策重新核准成另一個 digest；(f) receipt 的 object 被改。每一種的 `next` 都是 `preflight`，`reasons` 分別是 `latest_unverified`、`transport_version_changed`、`agent_cli_version_changed`、`version_unknown`、`policy_digest_changed`、`receipt_corrupt` | 前一列 Green 時，`applicable` 只需要看最新一份的 verdict：(b) 回 `dispatch`，action 的比較不成立 | 通過 |
| `test_another_run_with_the_same_policy_reuses_the_receipt` | run A 跑出 verified；run B（另一個 feature，核准同一個 digest，plan 也已核准）：`next` 回 `dispatch`，不需要再跑 preflight；run C 核准的是另一個 digest：`next` 回 `preflight`，原因 `policy_digest_changed` | 突變：把 receipt 的鍵改成含 feature，run B 的比較不成立 | 通過 |
| `test_unapproved_policy_comes_before_the_receipt` | 已核准 plan，政策被改過（`digest_mismatch`），而 receipt 對舊 digest 適用：`next == {action: "human", blockers: ["policy_not_approved"], decision_kinds: ["policy_change"], policy: "digest_mismatch"}`；fake 的呼叫紀錄沒有任何 `--version` | 突變：讓 `effective` 的呼叫端先查 receipt，`--version` 的呼叫斷言不成立 | 通過 |
| `test_gating_never_changes_next_before_approval` | 參數化：未 claim、有未解衝突、等待 `approve_plan`：envelope 的 `next` 等於狀態檔的 `next`；fake 的呼叫紀錄是空的 | 突變：讓 `effective` 對所有 action 都檢查政策，衝突那一列的比較不成立 | 通過 |
| `test_status_reports_each_profile_with_reasons` | 三種情況分別斷言 `status` 的 `result.profiles`：(a) Implementer verified、Reviewer 從未跑 → `implementer == {status: "verified", verdict: "verified", receipt: <ref>, versions: {transport: "1.4.218", agent_cli: "2.1.288"}, reasons: []}`，`reviewer == {status: "not_run", verdict: null, receipt: null, versions: {transport: "1.4.218", agent_cli: "0.157.0"}, reasons: ["not_run"]}`；(b) Reviewer unverified → `reviewer.status == "unverified"`，`reasons` 等於該 receipt 的 reasons；(c) Implementer verified 但 `claude --version` 改變 → `implementer.status == "not_applicable"`，`reasons == ["agent_cli_version_changed"]`。每一種的 `result.state_next` 都是狀態檔的值，envelope 的 `next` 等於同一時刻 `next` 命令的值；`--human` 的文字含兩個 next 與每個 profile 的狀態 | 4.1 時 `status` 沒有 `profiles`：(a) 的比較不成立 | 通過 |
| `test_status_without_an_approved_policy_calls_no_tools` | 參數化政策的四種狀態：`not_registered`、`not_approved`、`digest_mismatch`、`unreadable`。`status` 的每個 profile 都是 `{status: "not_applicable", verdict: null, receipt: null, versions: null, reasons: ["policy:<狀態>"]}`；fake 的呼叫紀錄是空的 | 突變：讓 `status` 一律讀版本，呼叫紀錄的斷言不成立 | 通過 |
| `test_status_with_policies_that_lack_profiles` | 參數化：(a) 已核准的政策沒有 `profiles`（Feature 1 的範例檔）→ 兩個 profile 都是 `{status: "not_applicable", verdict: null, receipt: null, versions: {transport: "1.4.218", agent_cli: null}, reasons: ["profile_missing"]}`，fake 只被呼叫 `orca --version`；(b) Implementer 的最新 receipt object 被刪 → `implementer == {status: "not_applicable", verdict: null, receipt: <ref>, …, reasons: ["receipt_corrupt"]}`，`status` exit 0 | 先假設 profile 存在：(a) 的 `reasons` 比較不成立 | 通過 |
| `test_write_commands_keep_the_state_next` | 已核准 plan 與政策、狀態檔的 `next` 是 `dispatch` 時呼叫 `decide`：envelope 的 `next` 等於狀態檔的值；fake 的呼叫紀錄沒有 `--version`（ORC-01） | 突變：讓 `decide` 的 envelope 走 `cli` 的完整管制路徑（會讀版本），呼叫紀錄的斷言不成立 | 通過 |

## 6. 殘留清理與中斷

- [ ] 6.1 殘留探測 worker 的清理、兩種中斷點、清理失敗的重試、清理不受政策影響；驗證：`uv run pytest tests/test_preflight_residual.py`

**模式與 effort**：預設模式；xhigh／xhigh。

**交付**：

- `preflight.py`：
  - DD-4 第 2 步與 DD-8 的殘留規則；
  - 紀錄的終態；
  - `cleanup` 紀錄與輸出欄位，本次有探測時另寫進新 receipt 的 `cleanup`。
- 殘留確認不了停止時，不派新的 worker。

**擁有路徑**：`src/loopctl/preflight.py`、`src/loopctl/orca.py`（只加需要的呼叫）、`tests/test_preflight_residual.py`、`tests/fakes/scenarios.py`（新增 `residual(point)`）。

**依賴**：5.1，從它取得：

- 完整的探測流程與 `probes/` 紀錄的種類；
- `latest` 與 `applicable`。

**AC**：D31、D30（清理的部分）。

**Commit**：`feat(preflight): clean up probe workers left by an interrupted run`

`tests/test_preflight_residual.py`。每個測試在自己的前置裡，以 `residual(point)` 製造殘留：用 `cli_proc` 跑一次 preflight，scenario 在指定的呼叫上 `kill_parent`。

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_interruption_before_the_dispatch_record` | `residual("worker-start")`（Orca 已收到任務，`dispatch` 紀錄還沒寫）：`latest` 不變；`probes/` 有 `started`、`terminal`，沒有 `dispatch` 與 `closed` | 突變：在派出前先寫一份 verified receipt，`latest` 的比較不成立 | 通過 |
| `test_interruption_after_the_dispatch_record` | `residual("terminal wait")`：`latest` 不變；`probes/` 有 `started`、`terminal`、`dispatch`，沒有 `closed` | 同上的突變 | 通過 |
| `test_next_preflight_closes_the_residual_first` | 製造殘留後再跑一次（政策已核准）：在新的 `terminal create` 之前，先對殘留的 handle 呼叫 `terminal close`，並以 `ps` 確認；`probes/` 多一筆 `cleanup {marker, handle, confirmed: true}`；輸出的 `cleanup` 與新 receipt 的 `cleanup` 都列出它；之後照常探測 | 5.1 不處理殘留：呼叫順序的斷言不成立 | 通過 |
| `test_residual_that_will_not_stop_blocks_a_new_probe` | 殘留的程序在 `terminal close` 之後仍在：不呼叫新的 `terminal create`；寫一份 unverified receipt，`reasons` 含 `residual_not_stopped`，並列出殘留的 marker 與 handle；`probes/` 有 `cleanup {confirmed: false}` | 先記錄後照常探測：`terminal create` 的呼叫斷言不成立 | 通過 |
| `test_failed_cleanup_is_retried_until_it_stops` | 接上一列的情況再跑兩次：第二次仍停不掉，仍不派新的 worker，又多一筆 `cleanup {confirmed: false}`；第三次 `ps` 不再列出程序 → `cleanup {confirmed: true}`，之後照常探測 | 先把 `cleanup {confirmed: false}` 當成終態：第二次的 `terminal close` 呼叫斷言不成立 | 通過 |
| `test_cleanup_runs_even_without_an_approved_policy` | 參數化：殘留可以停止／停不掉，而且政策未核准。兩種都 exit 1、`policy_not_approved`；殘留都被嘗試關閉，`cleanup` 紀錄（`confirmed` 分別是 true／false）與輸出都有；沒有新的 receipt；停不掉的那一種，在政策核准後的下一次 preflight 仍會先處理它 | 先在政策檢查之後才清理：`terminal close` 的呼叫斷言不成立 | 通過 |

## 7. 政策檔、矩陣與 CI

- [ ] 7.1 `workflow.yaml` 的實際 profiles、能力證據矩陣、`test_ci.py` 調整；驗證：`uv run pytest tests/test_ci.py tests/test_policy.py`

**模式與 effort**：預設模式；medium／high。

**交付**：

- `workflow.yaml`：加入 DD-2 的 `profiles` 與 `preflight`。
- `tests/test_ci.py:45-55`：改成斷言頂層鍵是 `{schema_version, repo, g3, profiles, preflight}`。
- `tests/test_policy.py`：新增下表的第二個測試。
- `docs/validation/capability-matrix.md`：
  - 欄：Orca＋claude、Orca＋codex；
  - 列：DD-6 的 item；
  - `fake` 欄填對應的測試名稱，`profile-probe` 與 `real-E2E` 先標 `none`。真實 R1 之後由協調者更新（DD-11）。

**擁有路徑**：`workflow.yaml`、`tests/test_ci.py`、`tests/test_policy.py`（只新增）、`docs/validation/capability-matrix.md`。

**依賴**：6.1，從它取得：完整的 item 名稱與測試名稱。

**AC**：G19、D22（矩陣）。

**Commit**：

- `feat(policy): declare the Orca profiles in workflow.yaml`
- `docs(validation): add the capability evidence matrix`

| 測試 | 斷言的行為 | Red 失敗在 | Green |
| --- | --- | --- | --- |
| `test_ci.py` 的政策檔鍵（改寫既有斷言） | 頂層鍵是五個；`policy.load("workflow.yaml")` 的 `errors == []`，兩個 profile 的 `invalid` 都是空清單 | 先只改測試、不改 `workflow.yaml`：鍵集合的比較不成立 | 通過 |
| `test_policy.py::test_repo_policy_profiles_are_distinct_models` | repo 的 `workflow.yaml`：Reviewer 與 Implementer 的 model 不同，Reviewer 的 runtime 是 `codex`、Implementer 的是 `claude` | 突變：把 Reviewer 的 model 暫時改成 `claude-opus-5-5`，比較不成立 | 通過 |

矩陣文件沒有 Red：它是文件，由 Reviewer 對照測試名稱與 DD-6 核對。

## 驗收驗證

- **CI**：由測試證明的部分，在 G1（全新 clone、完整套件）與 PR 上的 `unit-linux` 通過。
- **文件**：能力證據矩陣由 G2 Reviewer 對照 DD-6 與測試名稱核對。
- **真實 receipt**：真實 R1 由協調者在 Orca terminal 內執行（DD-11），要 Project Lead 授權。receipt 存在 `docs/validation/orca-preflight/receipts/`，矩陣的 `profile-probe` 欄依它填。
  - 驗收條件：Implementer `verified`；Reviewer 如實記錄。
- **彙整**：to-pr 把結果彙整到 #44 的 PR Pass package。

| AC | CI 的測試（task） | 文件 | 真實 receipt | 通過代表 |
| --- | --- | --- | --- | --- |
| D01 | 5.1 `…status_reports_each_profile…` | — | — | 狀態檔的下一步只依 run 狀態；`status` 另顯示依 receipt 與版本判定的結果，等於 `next` |
| D18 | 3.1 `…readback_mismatch…`；4.1 `…turn_context…` | — | 兩份 | 讀回值不符、缺欄位、沒有 native turn、找不到或多於一份含 marker 的紀錄，都使對應項不成立 |
| D19 | 2.1 `…invalid_profile…`、`…malformed_approved_policy…`、`…missing_selected_tools…`；3.1 `…worker_done…`、`…process_info…`、`…worker_start_failure…` | — | — | 能力缺口具體 Blocked，不改用其他工具 |
| D22 | 2.1 `…separate_latest_receipts…`；5.1 `…each_profile…` | 矩陣 | 兩份 | 兩個 profile 分開保存，不共用成功標記 |
| D23 | 2.1 `…unselected_tools…`、`…missing_selected_tools…` | — | — | 未選用的接入不被呼叫；已選的工具不在就 Blocked |
| D26 | 5.1 前兩個測試 | — | — | 沒有適用的 receipt 就不派工；任一條件改變就要重跑 |
| D27 | 3.2 `…judgement_table…`、`…permission_rule…`、`…self_report…`、`…other_tasks…`；4.1 `…tied_to_the_call…` | — | Implementer | 只有「嘗試、runtime 拒絕、資源未變」才算被拒 |
| D28 | 3.2 `…excluded_settings…`、`…redacted…`；4.1 `…codex_settings_are_recorded…` | — | 兩份 | 記錄載入的設定；排除的設定被載入就不成立；不含憑證 |
| D29 | 3.2 `…full_probe_is_verified…`；5.1 `…dispatch_needs…`、`…reuses_the_receipt…`；2.1 `…never_changes_the_feature_state…` | — | Implementer（必須 verified） | 全部成立才 verified；同一 digest 的 run 共用；preflight 不改 feature 狀態 |
| D30 | 1.1 `…refuses_without…`；5.1 `…unapproved_policy…`、`…without_an_approved_policy_calls_no_tools…`；6.1 `…cleanup_runs_even…` | — | — | 政策未核准時不探測、不派工，殘留仍被清理 |
| D31 | 6.1 全部 | — | — | 中斷不產生 verified；下次先清殘留，停不掉就不派新的，並重試到停下 |
| G19 | 4.1 `…live_probe_shape…` | 矩陣 | 兩份 | 沒有真實證據的格子標 `none`，不宣稱 E2E |
| G23 | 2.1 `…same_model…` | — | — | 兩個角色同一 model 時 Reviewer 不可用 |
| G24 | 4.1 `…implementer_workspace…`、`…independent_clone…` | — | Reviewer（如實） | Reviewer 改得到 Implementer 的檔案或 branch、或不是獨立 clone，就不成立 |

## 範圍

本檔只涵蓋 proposal 的 What Changes。派工、assignment、結果匯入、卡住偵測與 orchestrate skill 在 Feature 2。Reviewer 的獨立 clone 是環境設定，由人做（design DD-12）。

## 環境

- 本機 macOS、Python 3.12、uv。
- CI 的 `unit-linux` 上沒有 Orca、Claude、Codex，所有測試都用 fake。
- 真實 R1 需要：
  - Orca 1.4.218 以上，以及已註冊的 loop-engineering（git）；
  - `preflight-engineer`、`preflight-reviewer` 工作區（研究時已建立）；
  - Claude Code、Codex CLI；
  - 一個 Orca terminal。

## 風險

- design「Risks / Trade-offs」的各項。
- 3.1 是最大的 task（DD-4 的 8 個步驟）。若超出一個 session，可以把「等待與逾時」的兩個測試與它們的實作切成 3.1b，其他不變。
- fake transcript 與 rollout 依 research 樣本寫成；真實格式若再改變，真實 R1 會以 unverified 暴露，再回到計畫修正。
- `loopctl_not_found`（DD-5）沒有自動測試：測試一定在 venv 裡執行，`Path(sys.executable).parent` 一定有 `loopctl`。這個分支只在真實環境可能發生，失敗時結果是 unverified。
- `terminal wait` 成功（idle）時的 JSON 沒有實際樣本（`samples/orca/README`），實作以 `ok: true` 判定。

## 執行界線

- 每個 task 最多 3 次 attempt（D69(2)）。
- Implementer 不碰真實工具：只在 worktree 內跑測試；工具隔離讓測試不會呼叫到真實的 `orca`、`claude`、`codex`；不讀 `~/.claude`、`~/.codex` 的真實紀錄。
- 真實 R1 由協調者在所有 task 完成後執行，需要 Project Lead 授權。
