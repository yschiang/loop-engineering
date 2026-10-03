# 設計缺口檢查（D78）

- 檢查者：Claude Fable 5.1 xhigh（不同於計畫作者 Claude Opus 5.5 與計畫審查者 GPT-6 Astra），全新 session、唯讀、全新 clone，版本 `ad41ea7`。時間：2026-10-03T05:05:06Z ～ 2026-10-03T05:22:21Z。
- 結果：23 個缺口，都不需要改 spec。全部補進 design.md 與 tasks.md；G-22 另把 Orca CLI 的實際 JSON 存成 `samples/orca/`，G-1 更正了 research 對 hook 數量的描述。
- 計畫審查者的確認：見 `../plan/round-5-review.md`。

## 檢查原文

核對完成。以下是計畫（`design.md` DD-1～DD-12、`tasks.md`）沒定義、但實作一定會碰到的缺口。審查紀錄 P-1～P-28 已解決的事不重提。行號皆以目前 clone 為準；`樣本` 指 `docs/research/2026-10-03/orca-preflight/samples/`。

## 一、與真實樣本矛盾，會讓真實 R1 的 Implementer 變成 `unverified`（違反驗收條件）

### G-1 保留的 plugin 自己的 hook 會讓 `settings.excluded` 不成立
- **情境**：superpowers 在 `keep.plugins`，它的 SessionStart hook 會以 `hook_success` 記進 transcript，命令是 `"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start`，不含 `ORCA_AGENT_HOOK`。DD-6 規定「沒有一筆 `hook_success` 的命令不含 `keep.hooks_matching`」才成立 → 真實 Implementer 一定 unverified。fake 若忠實照樣本就到不了 3.2 的 Green；若略掉這筆，測試綠、真機紅。
- **證據**：樣本 `claude-probe-transcript.jsonl:6`（plugin hook）、`:5,28,38…`（13 筆 Orca hook）；`design.md:230`；`tasks.md:312`「只有 superpowers 與 Orca hook 時成立」；`research.md:475` 寫「`hook_success` 14 筆（Orca hook）」與樣本不符（13＋1）。
- **最小規則**（DD-6 `settings.excluded` 的 Claude 欄）：`hook_success` 的命令含 `keep.hooks_matching`，**或**含 `CLAUDE_PLUGIN_ROOT`（plugin hook，由 `skill_listing` 以 plugin 名稱判定）才算允許；plugin 名稱定義為 `enabledPlugins` 鍵 `@` 之前的部分，比對 `skill_listing.names` 的 `<name>:` 前綴。3.2 的 fake transcript 必須含樣本第 6 行那筆。

### G-2 `--version` 的輸出格式沒有正規化，`version.consistent` 與 `status.versions` 都比不過
- **情境**：真實輸出是 `2.1.288 (Claude Code)`、`codex-cli 0.157.0`，native 紀錄是 `2.1.288`、`0.157.0`。DD-6／DD-9 要求「相同」，但沒說怎麼從 `--version` 取值；DD-10 的 fake 回裸數字，所以這條路徑在 CI 完全沒測到。
- **證據**：`research.md:44-45`、`:479`（P9 是人比對的）；`design.md:231,349,354,378`；`tasks.md:263`（`versions.native == "2.1.288"`）、`:398`（`agent_cli: "2.1.288"`／`"0.157.0"`）。
- **最小規則**：DD-9「目前版本」加一句：取 stdout 第一個 `\d+(\.\d+)+`，取不到為 `None`（`version_unknown`）；DD-10 的 fake 預設改成印真實格式（`2.1.288 (Claude Code)`、`codex-cli 0.157.0`、`1.4.218`），讓 3.1／5.1 的斷言真的經過正規化。

### G-3 Codex 的 `custom_tool_call.input` 是一段 JS，不是含 `cmd` 欄位的 JSON
- **情境**：DD-6 說「`cmd` 等於任務文字」「`exit_code` 與輸出從 output 裡的 JSON 讀出」，但樣本的 `input` 是 `text(await tools.exec_command({cmd:"…",…}));`，引號依內容在 `"`／`'` 之間切換；`worker_done` 那筆更是用字串串接組出 `cmd`，根本沒有字面值。`output` 是兩個 `input_text` 元素，只有第二個是 JSON。Red／Green 若照「`cmd` 欄位」寫 fake，測的是不存在的形狀。
- **證據**：樣本 `codex-probe-rollout.jsonl:13`（雙引號）、`:27`（單引號）、`:57`（串接）、`:15`（output 第二元素）、`:30`（JSON 前多一行 electron 錯誤）；`design.md:241,249,280`；`tasks.md:353`。
- **最小規則**（DD-6「Codex 的 turn 配對」）：`cmd` 取 `input` 中 `cmd:` 後面的 JS 字串字面值（雙引號或單引號，解 JS 逸出）；沒有字面值的呼叫視為「沒嘗試該步驟」；`exit_code`／`output` 取 `output[]` 中第一個可解析成含 `exit_code` 的 JSON 的 `text`；拒絕標記以 `"code":\s*"runtime_access_denied"` 比對。4.1 的 `codex_probe` 必須產生這三種 `input` 形狀。

### G-4 `Edit(/<工作區路徑>/**)` 在 Claude Code 是專案相對路徑，不是絕對路徑
- **情境**：Claude Code 的權限規則以 `//` 表示絕對路徑、`/` 表示相對專案根目錄。照 DD-5 字面寫成 `Edit(/Users/…/preflight-engineer/**)`，`dontAsk` 下第 6 步會被拒 → `positive.inside_write` 不成立。3.1 的測試只斷言「含工作區的 `Edit(...)`」，錯的語法照樣綠。
- **證據**：`design.md:178`；`tasks.md:264`；`research.md:472`（P2 只說「要用 `Edit(path)`」，沒記規則全文）。
- **最小規則**：DD-5 寫死 `Edit(//<realpath(工作區)>/**)`；3.1 測試斷言這個精確字串。

### G-5 命令文字的 `shlex.quote` 會把 `$PATH` 變成字面值；「loopctl 所在目錄」沒有定義
- **情境**：DD-5「各段以 `shlex.quote` 處理」，`PATH=<dir>:$PATH` 整段被 quote 後 worker 的 PATH 只剩 `<dir>:$PATH` 字面，`claude`／`git` 都找不到。另外「loopctl 所在目錄」在 `python -m loopctl`（`cli_proc` 就是這樣跑）下 `sys.argv[0]` 是 `__main__.py`，沒有可執行檔；測試要斷言的目錄值也無從決定。
- **證據**：`design.md:180-181,187,192`；`tasks.md:264`；`tests/conftest.py:156-166,199`。
- **最小規則**：DD-5 改成「只 quote 值：`PATH=` + `shlex.quote(dir)` + `:$PATH`」；目錄定義為 `Path(sys.executable).parent` 若其中有 `loopctl`，否則 `shutil.which("loopctl")` 的目錄，兩者都沒有 → unverified 原因 `loopctl_not_found`（因為 `negative.loopctl` 將無法成立）。

### G-6 `config` 的值怎麼寫成 `-c k=v`（TOML）沒定義
- **情境**：YAML `false` 讀成 Python `False`；直接 `str()` 會變 `-c check_for_update_on_startup=False`，TOML 解析失敗，Codex 起不來 → `probe_timeout`。4.1 只斷言「profile 的每個 `-c` 覆寫」，大小寫錯也綠。
- **證據**：`design.md:100,187`；`research.md:295`（「parsed as TOML」）、`:477`（實際用 `=false`）；`tasks.md:351`。
- **最小規則**：DD-5 加「值以 TOML 字面值輸出：bool → `true`/`false`，字串 → 雙引號 basic string，數字裸寫」；4.1 斷言 `check_for_update_on_startup=false`、`features.hooks=false` 精確字串。

## 二、既有測試在 5.1 之後一定會踩到、但計畫沒定義的狀態

### G-7 已核准的政策沒有 `profiles`／沒有該 role 的 profile 時，`status`、`preflight`、`current_versions` 的行為
- **情境**：`REPO_FILES["workflow.yaml"]` 只有 `g3`（共用檔案表說不改）；`test_scope_policy.py` 多處在核准後呼叫 `status`。DD-9「政策已核准時，`status` 讀 receipt 與版本」→ 要讀哪個 agent CLI？`current_versions(role)` 只收 role，暗示寫死 role→runtime，與「runtime 由 profile 決定」矛盾。DD-2 只定義「缺欄位 → invalid」，沒定義「整個 role 不在 `profiles`」或 `profiles` 鍵不存在（算 `profiles_not_a_mapping`？）。`preflight --role reviewer` 在只有 implementer 的政策下原因無名。
- **證據**：`design.md:106-117,354,365-371`；`tests/conftest.py:298-305`；`tests/test_scope_policy.py:437-459,498-502,527-548`；`tasks.md:70`（5.1 只改兩處 dispatch 斷言）。
- **最小規則**：DD-2：`profiles` 鍵不存在視為 `{}`（不是 error）；role 不在 `profiles` → `Profile(invalid=["<profile_missing>"])`，preflight 原因 `profile_missing`。DD-9：`current_versions(role, runtime: str | None)`，runtime 取自 profile；runtime 未知只讀 `orca --version`，`agent_cli` 為 `null`；`status` 的 `profiles` 固定列 implementer、reviewer，profile 缺或 invalid 時 `{status: "not_applicable", verdict: <latest 或 null>, receipt: <ref 或 null>, versions: {transport, agent_cli: null}, reasons: ["profile_missing" | "profile_invalid:<field>" | "policy_invalid:<error>"]}`。

### G-8 `test_test_policy.py` 只複製 `conftest.py` 到 pytester 目錄，新的 autouse 隔離會在那裡找不到 `tests/fakes/`
- **情境**：`child` fixture 把 repo 的 conftest 複製到 pytester tmp 下的 `tests/`，以 in-process `runpytest` 跑。1.1 加的 autouse 工具隔離若以 `Path(__file__).parent / "fakes"` 找 fake 腳本，複製後指向不存在的路徑 → 每個子測試在 setup 錯誤 → 既有 4 個 test_test_policy 測試全壞。`tests/test_test_policy.py` 不在 1.1 的擁有路徑。
- **證據**：`tests/test_test_policy.py:54-66`；`tasks.md:57,102,121`；`design.md:377`。
- **最小規則**：1.1 擁有 `tests/test_test_policy.py`，`child` 同時複製 `tests/fakes/`；或 conftest 以 conftest 自己所在目錄下的 `fakes/` 為準並在 1.1 的「交付」寫明「複製 conftest 的測試也要複製 `fakes/`」。

### G-9 `mypy --strict` 對 `import yaml` 需要 stubs
- **情境**：pyyaml 沒附型別，`strict = true` 下 `src/loopctl/policy.py` 的 `import yaml` 會報 `import-untyped`，1.1 完成條件 `uv run mypy src` 過不了；計畫只說把 pyyaml 移到執行依賴。
- **證據**：`pyproject.toml:10,19,29-30`；`tasks.md:37,56,109`。
- **最小規則**：1.1 的 `build:` commit 同時把 `types-PyYAML` 加進 dev group 並更新 `uv.lock`（共用檔案表補一句）。

### G-10 receipt object 壞掉或遺失時 `status` 會以未攔截例外結束
- **情境**：`latest` 在 digest 不符時丟 `ReceiptCorrupt`；`applicable` 會吞掉，但 `status` 需要 `verdict`／`receipt` 必須呼叫 `latest`，而 `guarded` 不認得 `ReceiptCorrupt` → traceback。`store.get_object` 對檔案不存在丟 `ObjectError("object_missing:…")`，是否也算 `ReceiptCorrupt` 未定。5.1 (f) 只測 `next`。
- **證據**：`design.md:59,344`；`src/loopctl/cli.py:74-117`；`src/loopctl/store.py:527-539`；`tasks.md:394`。
- **最小規則**：DD-1 `receipts` 列：`latest` 把 `ObjectError`（missing 與 corrupt）都轉成 `ReceiptCorrupt(ref)`；DD-9 `status`：該 profile 為 `{status: "not_applicable", verdict: null, receipt: <ref>, versions: …, reasons: ["receipt_corrupt"]}`，不經 `guarded`。

### G-11 新的 `human` next 沒有 `blockers`，與 Feature 1 的 `human` 契約不一致
- **情境**：D7／高層設計把 `human` 定成「附 `blockers` 與 `decision_kinds`」，`derive` 的不變式是 `blockers == next.blockers`。DD-9 的 `{action: "human", decision_kinds: ["policy_change"], reason, policy}` 沒有 `blockers`，5.1 測試又以整個 dict 精確相等斷言，所以實作沒辦法補成一致形狀。
- **證據**：`design.md:359`；`tasks.md:396`；`src/loopctl/next.py:17,56-57`；`openspec/changes/archive/2026-10-03-run-decisions/design.md:276`；`docs/design-candidate/d45-04/design.md:68`。
- **最小規則**：DD-9 改成 `{action: "human", blockers: ["policy_not_approved"], decision_kinds: ["policy_change"], policy: <status>}`（用既有 `_human` 形狀），5.1 的預期 dict 同步改。

## 三、測試本身的可執行性

### G-12 `test_concurrent_preflight_for_one_role_is_refused` 照字面會死鎖
- **情境**：`cli_proc` 在 `communicate(timeout=60)` 阻塞到子程序結束；prelude「持有 lock、以檔案屏障等待主測試完成」時，主測試根本回不來跑第二個 preflight → 60 秒 `TimeoutExpired`。
- **證據**：`tests/conftest.py:208-217`；`tasks.md:221`。
- **最小規則**：改寫為「prelude 以另一個 fd `flock(LOCK_EX)` 該 lock 檔（先 `mkdir -p`＋`O_CREAT`），同一程序接著跑的 `python -m loopctl preflight` 就是第二個 preflight」（flock 以 open file description 為單位，同程序第二個 fd 也會 EWOULDBLOCK）；不需要屏障。

### G-13 停止確認的 `sleep` 次數與檢查順序沒釘死
- **情境**：DD-7「每 0.5 秒檢查一次，最多 10 次，第一次為 0 就確認」可以實作成「先查再睡」（10 查 9 睡）或「先睡再查」（10 睡 10 查）；3.1 斷言「`clock.sleep(0.5)` 被呼叫 10 次」，前一種合理實作會讓 Green 失敗。
- **證據**：`design.md:311-312`；`tasks.md:269`。
- **最小規則**：DD-7 寫成「`terminal close` 後，重複 10 次：`clock.sleep(0.5)`，再查 process-info；為 0 即確認」。

## 四、流程中沒定義的狀態與順序

### G-14 `terminal wait` 回 `exited` 或 `Problem` 時等待迴圈怎麼走
- **情境**：worker 啟動即崩潰（或 handle 失效）時，`terminal_wait` 回 `exited`／`Problem`；DD-7 只處理「沒完成就 sleep(2) 再等」，會空等到 `timeout_s`（真機 15 分鐘）才以 `probe_timeout` 結束。
- **證據**：`design.md:60,296-300`。
- **最小規則**：DD-7 加「`exited` → 立即進第 11 步，原因 `terminal_exited`；`Problem` → 立即進第 11 步，原因 `wait_failed:<reason>`」。

### G-15 Reviewer 的步驟 8、9 與 `isolation.independent_clone` 需要 Implementer 工作區，但第 5 步只解析所選 profile 的工作區
- **情境**：任務文字要代入 `<Implementer 工作區>` 與 `<它的 branch>`，資源檢查要 `git rev-parse <branch>`，隔離判定要兩個 `--git-common-dir`。Implementer 的 workspace 找不到／多於一個／implementer profile invalid 時，Reviewer 該怎麼辦沒寫。
- **證據**：`design.md:158,203-204,232,263`；`tasks.md:354-355`。
- **最小規則**：DD-4 第 5 步加「Reviewer 另以 implementer profile 的 `workspace` 在同一組 repo 中找工作區，0／多於 1 → `implementer_workspace_not_found`／`_ambiguous`，unverified；implementer profile invalid → `implementer_profile_invalid`」；`<它的 branch>` 取該工作區在 `worktree list` 的 `branch`。

### G-16 `receipts/` 最新的索引檔無法解析時，較舊的 `verified` 會重新適用
- **情境**：`append_record` 在 `O_EXCL` 建檔與寫入之間被 kill 會留下空的 `N.json`；`list_records` 把它放進 `skipped`，`applicable` 取「編號最大的 item」→ 前一份 verified 又變成最新。違反 DUR-09「較新的 unverified 取代較早的 verified」。
- **證據**：`design.md:325,344`；`tasks.md:203`（`skipped == ["4.json"]`、`items` 三筆）。
- **最小規則**：DD-9 適用判定加「`skipped` 中有編號大於所選 item 的檔名 → `receipt_corrupt`（附檔名）」，`status` 同。

### G-17 `exclude.plugins` 只用來判定，從未進入 Codex 的啟動參數
- **情境**：DD-5 的 Codex 命令只展開 `config`；`exclude.plugins` 非空時，`disabled_plugin_ids` 不會含它，`settings.excluded` 必定不成立。4.1 的 fake rollout 直接寫 `disabled_plugin_ids`，所以測試看不到這個斷鏈。
- **證據**：`design.md:101,109,187,230`；`tasks.md:356`；樣本 `codex-probe-rollout.jsonl:8`（`disabled_plugin_ids: []`）。
- **最小規則**：DD-5 寫明 `exclude.plugins` 對應的 `-c` 覆寫（依 Codex 設定鍵），或明寫「本 Feature 不套用，`policy.load` 把非空的 `exclude.plugins` 標 `invalid`」，矩陣對應格標 `none`。

### G-18 Claude transcript 的 mtime 篩選把注入時鐘和 OS 時鐘混用
- **情境**：`find_claude(..., since)` 以 `started`（`clock.now()`，測試裡是假時鐘）比對檔案 mtime（真實時鐘）。假時鐘起點若晚於真實時間，fake 寫出的 transcript 一律被篩掉 → `native_not_found`；`clock` fixture 的起點沒定義，這條篩選也沒有任何測試。
- **證據**：`design.md:61,212,393`；`tasks.md:144`；`tests/test_approval.py:381-398`（既有 Clock 起點 2026-10-02）。
- **最小規則**：DD-6 改成「`since` 取 `started` 紀錄檔自己的 mtime」（同一個 OS 時鐘），或 DD-10 寫明 `clock` fixture 起點 = 測試開始時的真實時間。

### G-19 Codex `sessions/YYYY/MM/DD` 的日期用哪個時區
- **情境**：`clock.now()` 是 UTC；Codex 以本機時區建日期目錄（研究未記明）。台北 00:00–08:00 之間探測，UTC 日期是前一天 → 目錄找不到 → `native_not_found`。
- **證據**：`design.md:213`；`research.md:347`；樣本 `codex-probe-rollout.jsonl:1`（`03:55Z` 對 `2026/10/03`，看不出時區）。
- **最小規則**：DD-6 寫「搜尋起訖時刻的 UTC 日期與本機日期的聯集」。

### G-20 Claude「含 marker 那筆紀錄」與檔案搜尋範圍要指定紀錄型別
- **情境**：marker 也出現在 `ai-title`、`last-prompt` 這類沒有 `cwd`／`permissionMode` 的紀錄；若實作取「第一筆含 marker 的行」，`placement.cwd`、`permission.mode` 會是 `actual: null`。subagent transcript 在 `<dir>/<uuid>/subagents/` 下，若遞迴搜尋會變 `native_ambiguous`。
- **證據**：樣本 `claude-probe-transcript.jsonl:8,21,25`；`design.md:212,220-224`；`research.md:325`。
- **最小規則**：DD-6 寫「marker 紀錄 = `type == "user"` 且 `message.content` 為字串且含 marker 的第一筆；檔案搜尋只看 `projects/*/*.jsonl` 一層」。

### G-21 非 store 的檔案 IO 失敗沒有對應
- **情境**：`--out` 路徑不可寫、`settings/<marker>.json` 寫不出、`~/.claude/settings.json` 不存在或不是合法 JSON（DD-5 的 `keep.*` 來源）、讀 native 檔時 `PermissionError`。`guarded` 只接 `store.IOFailure`，其餘會 traceback；使用者設定缺失時 hooks／env 為空要不要繼續探測也未定。
- **證據**：`src/loopctl/cli.py:74-117`；`design.md:126,135,173-176`；`tasks.md:219`。
- **最小規則**：DD-3 加「`--out` 與 settings 檔的 OSError → `io_error`（exit 6，`op` 為 `write_out`／`write_settings`）；receipt 已存入 store 時 `committed: true`」；DD-5 加「使用者設定讀不到或不是 JSON → unverified，原因 `user_settings_unreadable`，不派 worker」。

### G-22 fake 要模仿的 Orca JSON 欄位，研究裡沒有證據
- **情境**：第 5 步依 `gitRemoteIdentity.canonicalKey`、`worktree list` 的 `displayName`／完整 ID、`terminal create` 的 handle 欄、`terminal wait` 的 `idle|timeout|exited`、`worker-show` 的 `status` 判定；研究只記了 `terminal list` 欄位與「worktree id 是 `<repo-id>::<path>`」，`canonicalKey` 全 repo 只出現在 design。fake 照 design 寫，真機欄位不同時 Implementer 會在第 5 步 `repo_not_registered`。
- **證據**：`design.md:158,161,165`；`research.md:201-205,250-253`；`docs/research/2026-09-25/evidence/orca-command-schema.json:6096`。
- **最小規則**：2.1 的 `environment(...)` 與 3.1 的 `claude_probe(...)` 以 live probe 的去敏感化 JSON 輸出為範本，放進 `samples/`（同 native 樣本的做法），計畫在 DD-10 列出這些檔案。

### G-23 探測留下的檔案與 DD-3 的寫入範圍
- **情境**：第 6 步（與 Reviewer 第 8 步若 `resource_changed`）會在工作區留下 `preflight-probe-inside-<s>.txt`；每次 preflight 累積一個。實作者要麼刪掉（違反 DD-3「只寫 `$LOOPCTL_HOME`」），要麼留著不說。
- **證據**：`design.md:125,201,226`。
- **最小規則**：DD-5 加一句「preflight 不刪探測檔；`positive.inside_write` 只讀存在性，路徑記進 receipt 的 `evidence`」。

---

以上都不需要改 spec（沒有「要回 feature-to-spec」的項目）；全部可寫進 design.md 對應 DD 與 tasks.md 的對應 task。

缺口數量：23