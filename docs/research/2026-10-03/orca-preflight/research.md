---
date: 2026-10-03T11:43:22+0800
researcher: Claude Agent SDK subagent（claude-opus-5-5），research-codebase 方法；另派兩個唯讀子代理（參考實作對照、native 紀錄欄位）
repository: yschiang/loop-engineering
topic: Feature 2a（orca-preflight）spec-to-plan 前的現況研究：loopctl 進入點、儲存、workflow.yaml、測試接縫、Orca 與 agent CLI 介面、native 紀錄、process-info、參考實作
tags: [research, loopctl, orca, preflight, feature-2a, orca-preflight, receipt, native-records]
git_commit: b278378ebaa68ebf8964b6a4b66cefb59dd0f9eb
branch: feature/orca-preflight
base: main@458ab7777b5cae15a34e265e55710da893303d9c（`src`、`tests`、`pyproject.toml`、`uv.lock`、`workflow.yaml`、`scripts`、`.github` 與 main 無差異）
working_tree: clean（寫入本報告前）
status: complete
last_updated: 2026-10-03
last_updated_by: Claude Agent SDK subagent（claude-opus-5-5）
---

# Feature 2a（orca-preflight）現況研究

## 研究問題

spec-to-plan 寫 design 與 tasks 之前，用現有程式與本機工具回答十個問題：loopctl 的進入點與 `next` 管制要改哪裡；receipt 與 marker／handle 紀錄放哪裡；`workflow.yaml` 的 `profiles` 怎麼讀；測試怎麼放 fake `orca`；Orca 與 agent CLI 實際提供哪些介面；native 紀錄有哪些欄位；怎麼以 process-info 確認停止；參考實作能用多少；以及只有 live probe 能回答的事。

spec 已確認（[proposal](../../../../openspec/changes/orca-preflight/proposal.md)、三份 spec delta），本文不改 spec，也不做設計決定；寫到「選項」的地方只列證據，由 design 決定。

## 摘要

1. **`next` 的管制點在 `cli`，不在 `derive`。** `derive` 是純函式，每次提交時算出狀態檔的 `next`（[`next.py:10-18`](../../../../src/loopctl/next.py)），核准後回 `dispatch`（`next.py:69-73`）。`status`、`next` 都只把狀態檔的 `next` 放進 envelope（[`cli.py:190-224`](../../../../src/loopctl/cli.py)）；政策狀態只在 `status` 讀取時算（`cli.py:203-218`、[`state.py:100-123`](../../../../src/loopctl/state.py)），不影響 `next`。MODIFIED DUR-01 正好對應：狀態檔照舊，`status`／`next` 在 `cli` 讀檔、讀 receipt、讀版本後重算。會跟著改的測試至少有 `test_approval.py:606-633`、`test_scope_policy.py:254-257`、`test_ci.py:45-55`（後者斷言 `workflow.yaml` 剛好只有三個鍵）。
2. **探測工作區已建好，但 Reviewer 的工作區不是獨立 clone。** Orca 現在有 git 類型的 repo `loop-engineering`，以及兩個工作區 `preflight-engineer`、`preflight-reviewer`（branch `yschiang/preflight-engineer`、`yschiang/preflight-reviewer`）。兩者都是 `/Users/johnson.chiang/workspace/loop-engineering` 的 linked worktree，共用同一個 `.git`。GAT-05 要求「獨立的 clone」，待決 7 交給 design；AC-G24 的負例（移動 Implementer 工作區的 ref）在這個佈局下只能靠 sandbox 擋。
3. **自訂 terminal 只吃一段 shell 文字。** `orca terminal create --command <text>` 會把文字「typed into whatever shell the host started」（help），沒有 argv、cwd 或 env 參數；cwd 由 `--worktree` 決定。`worker-start --terminal` 不能和 `--model`／`--effort` 並用，要給 `--worktree`（2026-09-25 實測要用 terminal 的完整 workspace ID）。對外部 terminal，`worker-stop` 會回 `stop_unknown`，`worker-release` 也不關「reused or pre-existing terminals」。所以停止只能由 preflight 自己關 terminal 或結束程序，再以 process-info 確認。
4. **Orca 沒有任何地方給出 agent 的 pid。** `terminal list`／`terminal show` 只有 `handle`、`ptyId`、`incarnationId`、`agentIdentity` 等欄位；`status --json` 的 `app.pid` 是 Orca app 本身。可行的 process-info 有兩種：Claude 用 loopctl 自己給的 `--session-id <uuid>` 在 argv 裡找；或在 macOS 用 `ps -Eww` 找環境變數，Orca 的 PTY 會帶 `ORCA_TERMINAL_HANDLE`（實測可見）。後者會讀到其他程序的 token，不能保存輸出。
5. **Claude 的 native 紀錄足以讀回，Codex 的拒絕只有文字。** Claude transcript 路徑是 `~/.claude/projects/<cwd 非英數字元換成 ->/<sessionId>.jsonl`，以 `--session-id` 指定時檔名就是該 uuid（Feature 1：18/18）。`assistant` 頂層有 `effort`、`perTurnEffort`，`message.model` 有 model，每筆紀錄有 `cwd`、`gitBranch`、`version`，`user` 有 `permissionMode`；被拒的工具呼叫是 `user` 紀錄帶 `toolDenialKind`（`permission-rule` 等）加 `tool_result.is_error: true`。Codex rollout 的 `turn_context` 有 `model`、`effort`、`cwd`、`sandbox_policy`、`approval_policy`、`permission_profile`、`disabled_plugin_ids`，但 sandbox 拒絕沒有結構化標記，只能從 stderr／output 的 `Operation not permitted` 判斷，而且 exit code 可能仍是 0。
6. **「保留 Orca hook、排除 caveman／Herdr hook」做不到一個開關完成。** 使用者 `~/.claude/settings.json` 有 13 個 Orca hook、11 個 caveman hook、1 個 Herdr hook，都寫在 user 來源，另有 `enabledPlugins`（含 ponytail、ralph-wiggum、superpowers）與 gateway 的 `env`。Feature 1 用的 `disableAllHooks: true` 會連 Orca hook 一起關掉。CLI 的現成選項有 `--setting-sources`（只能列 user、project、local）加 `--settings`、`--bare`、`--safe-mode`；哪一種組合能「只留 Orca hook、gateway、superpowers」，要 live probe 確認。Interactive 模式的 transcript 沒有 plugin 清單，只能從 `attachment` 的 `hook_success`、`skill_listing` 間接看到載入了什麼。
7. **產品程式目前不讀 YAML。** `dependencies = []`；pyyaml 6.0.3 只在 dev group（[`pyproject.toml:10,15-21`](../../../../pyproject.toml)）；Feature 1 design D1 以「產品程式不讀 YAML」為不採用 pyyaml 的理由。讀 `profiles` 要 design 擇一：把 pyyaml 改成執行依賴（`uv.lock` 已有）、把 `workflow.yaml` 寫成 JSON 相容的 YAML 再用 `json` 讀，或其他做法。
8. **測試接縫現成，但等待不能用「測試專用的短間隔」。** in-process 的 `cli` 會繼承 `os.environ`，所以 `monkeypatch.setenv("PATH", …)` 就能放 fake `orca`、`claude`、`codex`、`ps`（參考實作 `tests/conftest.py:72-104` 就這樣做）。參考實作把 timeout 與 poll 設成 0；AGENTS.md §1 明文禁止「縮短重試間隔」這類只給測試的設定。Orca 本身有阻塞式等待（`check --wait --timeout-ms`、`terminal wait --for exit|tui-idle`），等待交給 Orca 時，fake 立即回應即可，不需要 sleep 接縫。目前 171 個測試（69 個 `test_` 函式）在本機約 12.6 秒跑完。

## 0. 來源與快照

| 來源 | 位置 | 版本／狀態 |
| --- | --- | --- |
| Feature worktree | `/Users/johnson.chiang/workspace/loop-engineering-orca-preflight` | `feature/orca-preflight@b278378`；程式與 main `458ab77` 相同；`src` 1,715 行、`tests` 3,984 行 |
| Spec | [`openspec/changes/orca-preflight/`](../../../../openspec/changes/orca-preflight/) | proposal 與三份 spec delta，確認於 `07a4861` |
| 先前研究 | [orca-dispatch/research.md](../orca-dispatch/research.md)、[verification.md](../orca-dispatch/verification.md) | 兩者衝突時以 verification 為準；本文只補新事實 |
| Feature 1 design | [archive/2026-10-03-run-decisions/design.md](../../../../openspec/changes/archive/2026-10-03-run-decisions/design.md) | D1 L34-48、D2 L50-101、D3 L103-135、D7 L254-277、D8 L279-288、D11 L359-385、D12 L387-414、D13 L416-434、Risks L460-470 |
| Orca | `/usr/local/bin/orca` → `/Applications/Orca.app/Contents/Resources/bin/orca` | `1.4.218`（`--version` 與 `status --json` 的 `runtime.appVersion`）；`skills get orchestration --full` 795 行，sha256 `708b665f…40b23d7`，與先前研究同一份 |
| Claude Code | `~/.local/bin/claude` → `~/.local/share/claude/versions/2.1.288` | `2.1.288 (Claude Code)` |
| Codex CLI | `~/.local/bin/codex` → `~/.codex/packages/standalone/current/bin/codex` | `codex-cli 0.157.0`（原生 Mach-O arm64） |
| 參考實作（不是證據，D75） | `/Users/johnson.chiang/workspace/loop-engineering-thin` | `fcefecc`，工作樹乾淨 |
| Feature 1 人工派工工具 | `/Users/johnson.chiang/workspace/loop-engineering-run-decisions/.delivery/run-decisions/loop/` | 不受 git 追蹤；只讀 `dispatch.sh` 與 `settings.template.json` 的結構 |

Orca 只執行了唯讀命令：`--version`、`--help` 與各子命令的 `--help`、`status --json`、`skills get orchestration --full`、`repo list --json`、`worktree list --json`、`terminal list --json`，以及對既有 terminal 的一次 `terminal show --json`。沒有啟動 claude 或 codex session（只跑 `--help`、`--version`）。測試是在 scratchpad 以 `git archive HEAD` 解出的副本上跑，沒有在 worktree 建立 `.venv` 或快取。

## 1. loopctl 的進入點、`status`／`next` 與管制點

### 1.1 CLI 結構

- **派送**：`main(argv)` 先以 `parse` 解析，再查 `HANDLERS[args.command]` 取得 `(exit code, envelope)`，印成一行 JSON（[`cli.py:476-487`](../../../../src/loopctl/cli.py)）。`HANDLERS` 在 `cli.py:342-351`：`init`、`claim`、`status`、`next`、`register`、`decide` 都包在 `guarded` 裡；`adopt`、`delegate` 回 `unsupported`。
- **Parser**：`build_parser`（`cli.py:403-454`）。每個 run 命令都經 `_run_options` 加 `--repo`（`owner/name`，`repo_name` 核對）與 `--feature`（單一路徑段，`feature_id` 核對）（`cli.py:380-400`）。`Parser` 把 argparse 錯誤改成 `UsageError`，最後回 exit 2 `usage`（`cli.py:366-377`、`481-483`）。
- **Envelope**：`envelope()` 固定 6 個鍵 `ok`、`revision`、`result`、`blocked`、`next`、`safety`；`safety` 永遠是 `None`（`cli.py:27-43`）。拒絕走 `refusal(code, error, **fields)`（`cli.py:50-51`）。
- **Exit code**：`guarded` 把例外轉成 envelope（`cli.py:74-117`）：

  | code | 來源 |
  | --- | --- |
  | 0 | 成功 |
  | 1 | `run_not_found`、`run_exists`、`transition_rejected:<cid>`、`unknown_target`、`already_claimed`、`decisions.Rejected` |
  | 2 | `usage`（`EXIT_USAGE`）、`unsupported` |
  | 3 | 只用在 transition 衝突（`EXIT_BLOCKED`，`cli.py:24`、`97-103`、`195-199`） |
  | 4 | `not_owner` |
  | 5 | `untrusted_state` |
  | 6 | `io_error`（`op`、`errno`、`committed`） |

  `blocked` 欄位目前永遠是 `null`（archived design D2 L78）。參考實作的 preflight 在 unverified 時回 exit 3，並把原因放在 `blocked.reasons`（參考實作 `src/loopctl/cli.py:522-530`）；main 的 3 目前只代表衝突，preflight 的 Blocked 用哪個碼、`blocked` 放什麼，由 design 決定（verification §三也列了這件事）。
- **讀取命令不寫狀態**：`status`、`next` 只呼叫 `store.load`（`cli.py:213-224`）；`store.load` 的契約是「reading never writes」（[`store.py:155-158`](../../../../src/loopctl/store.py)）。

### 1.2 `preflight` 怎麼接進來

- 新增子命令的現成模式：`build_parser` 加一個 subparser 並呼叫 `_run_options`，`HANDLERS` 加一列並包 `guarded`。`--repo`／`--feature` 的格式核對沿用，所以輸入跳不出 `$LOOPCTL_HOME`（archived design D2 L97）。
- spec 要求 preflight 不需要協調權、不寫 feature 狀態（DUR-09）。所以它只能用 `store.load` 讀 run，不能走 `commit_latest`／`store.commit`，也不需要 `owner_token`。`guarded` 會照常把 `RunNotFound` 轉成 exit 1、`UntrustedState` 轉成 exit 5。
- 政策核准的判定已經存在：`_policy_digest(st)` 唯讀重讀登記的 `path`（`cli.py:203-210`），`state.policy_view(state, current_digest)` 依序判 `not_registered`、`unreadable`、`not_approved`、`digest_mismatch`、`approved`（`state.py:100-123`）。AC-D30 的「沒有綁定目前 digest 的人工 `policy_change`」對應 `policy_view(...)["status"] != "approved"`。
- 「該 run 已核准的 digest」就是 `st["policy_approval"]["digest"]`（由 `decisions._policy_approval` 寫入，[`decisions.py:199-212`](../../../../src/loopctl/decisions.py)）。只有 `status == "approved"` 時，它才等於登記的 digest 與檔案目前的 digest。
- `_policy_digest` 會讀一次檔案，算出 digest 後就丟掉內容。preflight 要解析 `profiles`，而 receipt 要綁 digest；如果讀兩次（一次算 digest、一次解析），中間檔案可能被改。比較穩的做法是讀一次 bytes，同時用來算 digest 與解析（design 細節）。

### 1.3 `status` 與 `next` 現在怎麼產生

- `next.derive(state)`：重算 `plan.superseded_by`、`phase`、`blockers`、`next`（`next.py:10-18`）。store 在 `create` 與每次 `_commit` 的寫入前呼叫它（`store.py:263`、`405`、`435`）。所以狀態檔的衍生欄位永遠等於由其他欄位算出的值（archived design D7 L256）。
- `_next` 依序取第一個成立的條件：未解衝突 → 沒有 owner → 有 `approval` 回 `{"action": "dispatch", "plan": …, "approval": …}` → 沒有 plan → plan 有阻擋 → 等 `approve_plan`（`next.py:60-79`）。
- `cli.reading()` 把狀態檔的 `st["next"]` 原樣放進 envelope 的 `next`；有未解衝突時回 exit 3（`cli.py:190-200`）。
- `status` 的 `result` 是 `state.view(revision, st, _policy_digest(st))`（`cli.py:213-218`、`state.py:64-84`）；`--human` 以 `state.human(result, st["next"])` 輸出逐行文字（`state.py:134-161`）。
- `next` 命令的 `result` 只有 `phase` 與 `blockers`（`cli.py:221-224`）。
- archived design D7 L277：「本 Feature 的 `next` 只由狀態決定…`policy` 的狀態在讀取時計算，不影響 `next`」；Risks L467 預告「之後加入時間或外部輸入的 Feature 要在自己的 design 重新界定」。verification §三 L107 指出：`workflow.yaml` 沒登記、沒核准或 digest 不符時，`next` 仍回 `dispatch`。

### 1.4 加上 AC-D26／D30 管制與 DUR-01 註記要動的地方

MODIFIED DUR-01 規定：狀態檔的下一步只依 run 狀態，可不可以派工由 `status`、`next` 每次重算，兩者不同時以 `next` 為準。對照現有程式：

| 位置 | 現況 | 2a 要做的事（依 spec，做法由 design 定） |
| --- | --- | --- |
| `next.derive`／`_next`（`next.py:10-79`） | 核准後回 `dispatch` | 依 DUR-01，狀態檔照舊只依 run 狀態，可以不改。若想維持 D1「`next` 不讀檔」，管制可以寫成另一個純函式，輸入狀態的 next、政策狀態與 receipt 判定結果 |
| `cli.reading`（`cli.py:190-200`） | envelope 的 `next` = `st["next"]` | 改放重算後的 next：政策未核准 → `human` 加 `policy_change`；Implementer 沒有適用的 receipt → `preflight` 動作，附 profile 與原因 |
| `cli.status`、`cli.next_step`（`cli.py:213-224`） | 只讀狀態與政策檔 | 另外讀 receipt store 與目前版本（ORC-01 允許的固定命令） |
| `state.view`（`state.py:64-84`）、`state.human`（`state.py:134-161`） | 沒有 profile 欄位 | AC-D01：同時顯示依 run 狀態算的下一步，以及依 receipt 與版本判定的結果；DUR-09：每個 profile 的驗證狀態、版本與原因 |
| `cli.decide`、`cli.register` 的 envelope（`cli.py:258`、`334`） | `next=st["next"]` | spec 只要求 `status`、`next` 重算。寫入命令的 envelope 是否也重算（每次寫入都要讀版本），還是明確標示為狀態檔的值，由 design 決定 |

AC-D30 的前提「這個 run 已核准 plan」對應 `_next` 回 `dispatch` 的那一列。在它之前的列（衝突、未 claim、未核准）不受影響，所以 `test_scope_policy.py:451-459`「The policy never changes next (D7)」在未核准的 run 上仍成立，但這句註解的範圍要寫清楚。

**會改到的既有測試**（已讀斷言，未逐一模擬）：

| 測試 | 斷言 | 為什麼會變 |
| --- | --- | --- |
| `test_approval.py:606-633` `test_next_after_approval_reports_dispatch` | `next`、`status` 的 envelope `next` 與狀態檔的 `next` 都等於 `dispatch`、exit 0 | 這個測試沒登記或核准政策，2a 之後 envelope 會回需要 `policy_change`；狀態檔仍是 `dispatch` |
| `test_scope_policy.py:254-257` | 重新核准後 `next` 的 action 是 `dispatch` | 同上 |
| `test_ci.py:45-55` | `workflow.yaml` 剛好等於 `{schema_version, repo, g3}` | 加 `profiles` 就不成立 |
| `tests/conftest.py:298-305` `REPO_FILES["workflow.yaml"]` | 範例政策只有 `g3` | preflight 的測試要有 `profiles` |
| `test_state.py:630` | 不可信狀態時 action 不是 `dispatch` | 不受影響 |

## 2. 儲存

### 2.1 現有佈局與 helper

```
$LOOPCTL_HOME/                        預設 ~/.loopctl（store.py:30-31）
  runs/<owner>/<name>/<feature>/      run_dir（store.py:34-36）
    feature.json                      唯一現行狀態
    history/<rev>.json                write-once，os.link 建立（store.py:603-620）
    lock                              只有 init 建立；_locked 不會重建（store.py:341-354）
  objects/<sha256 hex>                content-addressed，write-once（store.py:39-40、506-539）
```

- `put_object(data) -> "sha256:<hex>"`：寫暫存檔、fsync、`os.link` 到 digest 名稱，已存在就略過（`store.py:506-521`）。`get_object(ref)` 讀回後核對 sha256，不符丟 `ObjectError("object_corrupt:…")`（`store.py:527-539`）。所以「內容與 digest 不符就不適用」直接對應現成的核對。
- 可用的原子寫入 helper 都在 `store.py`，但都是私有的：`_write_new`（`O_CREAT|O_EXCL`，`store.py:588-589`）、`_write_tmp`（`store.py:592-600`）、`_sync_file`（darwin 加 `F_FULLFSYNC`，`store.py:567-570`）、`_sync_dir`（`store.py:573-578`）、`_link_history` 的 `os.link` write-once（`store.py:603-620`）、`_replace_state` 的 `os.replace`（`store.py:623-636`）、`_reporting` 把 `OSError` 包成 `IOFailure` 並標 `committed`（`store.py:143-152`）。新模組要重用，就得把它們公開，或由 store 提供新函式。
- 狀態檔的頂層欄位「讀取時缺欄位視為空」，`schema_version` 只在不相容時遞增（archived design D3 L135）。preflight 不寫 feature 狀態，所以 receipt 不放進 `feature.json`，也不影響 `schema_version`。

### 2.2 repo 層級的 receipt 與 marker／handle 紀錄可以放哪裡

spec 的限制：receipt 在 run 狀態之外、帶自身內容的 digest、每個 profile 以最新一份為準、任何已核准同一 digest 的 run 都可採用（DUR-09）；marker 與 handle 要在派出 worker 之前持久記錄，清理結果也記在那裡（DUR-09、AC-D31）。

- **鍵**：receipt 不屬於任何 feature，但屬於某個 repo 的政策。不同 repo 的 `workflow.yaml` 有自己的 `repo:` 欄位，digest 本來就不同；若只以 profile 名稱當鍵，A repo 的 preflight 會蓋過 B repo 的「最新一份」。和現有佈局一致的選項是放在 `$LOOPCTL_HOME` 下、以 `<owner>/<name>` 為層級，與 `runs/<owner>/<name>/` 並列，再分 profile。
- **自身 digest**：receipt 存成 object（`put_object`），object 名稱就是它內容的 sha256；讀回時 `get_object` 核對。「最新一份」需要一個每個 profile 的有序索引，可以照 history 的做法，以 `os.link` 寫 write-once 的編號紀錄，取最大號為最新。
- **marker／handle 紀錄**：派工前先寫（write-once）。terminal 的 handle 要等 `terminal create` 回應才知道，所以至少有兩個時間點：(1) 產生 marker（以及 Claude 的 `--session-id` uuid）後立刻寫；(2) 拿到 handle 後追加。清理結果也要追加。用「每次追加一份 write-once 紀錄」可避免改寫既有檔；用 `os.replace` 改寫單一檔也可以。
- **鎖**：run 的 `lock` 只由 `init` 建立、不重建（`store.py:181-183`、`347-349`）。preflight 不拿 run 的鎖，也不應該拿；兩個 preflight 同時跑同一個 profile 時要不要互斥、用哪個鎖檔，是新的設計點。
- **遮蔽後的摘錄**：DUR-09 要求摘錄存在 receipt 裡（transcript 約 30 天會被清掉，verification §三 L90）。摘錄可以放在 receipt 本體，或另存 object 再由 receipt 以 `{"$object": …}` 引用。注意 store 的 `_references` 只在提交 run 狀態時核對引用（`store.py:477-481`、`542-551`）；receipt 不經 `commit`，引用要由 receipt 自己的讀取路徑核對。
- **提交到 repo 的真實 receipt**：proposal 要求兩個 profile 的真實 R1 receipt 存進 repo。現有可放證據的位置是 `docs/validation/`（已有 `evidence/` 目錄）；`.delivery/` 在 `.gitignore`。路徑由 design 定。

## 3. `workflow.yaml` 的解析

- **現況**：產品程式完全不 import yaml（`grep -rn yaml src/` 沒有結果）。`register policy` 與 `status` 只讀 bytes 算 sha256（`cli.py:203-210`、`269-299`）。`workflow.yaml` 只有 `schema_version`、`repo`、`g3`，`g3.required_checks` 用 flow mapping 寫法（[`workflow.yaml`](../../../../workflow.yaml)）。
- **依賴**：`[project] dependencies = []`；`[dependency-groups] dev` 有 `pyyaml`（`pyproject.toml:10`、`15-21`）。`uv.lock` 鎖 `pyyaml 6.0.3`，有 sdist 與 cp312 的 macOS、Linux wheel（`uv.lock:196-203`）。唯一讀 YAML 的是 `tests/test_ci.py:13`、`41`（`yaml.safe_load`）。
- **歷史依據**：archived design D1 L46-48：「執行期零依賴…參考實作把 pyyaml 列為執行依賴；本 Feature 不採用，因為產品程式不讀 YAML」。Goals 也寫「不解析 `workflow.yaml` 的結構，G3 在 Feature 3」（L28）。2a 讀 `profiles`，這個前提就不成立了。另外，「與高層設計刻意不同之處」的表把「pyyaml 為執行依賴」列為不採用（L457）。
- **參考實作**：pyyaml 是唯一的執行依賴（`pyproject.toml:6`），以 `yaml.safe_load` 讀（`preflight.py:420`）；`profiles` 的形狀是 `{implementer|reviewer: {transport, runtime, provider, model, effort, settings}}`（參考實作 `workflow.yaml:28-30`）。
- **選項**（由 design 決定，不在本文判定）：

  | 選項 | 證據與影響 |
  | --- | --- |
  | A. pyyaml 改成執行依賴 | `uv.lock` 已有，build 不需要新的來源；推翻 D1 的理由，需在 2a design 寫明；`dist-smoke.sh` 的安裝步驟會把它裝進 venv |
  | B. `workflow.yaml` 只用 JSON 相容的 YAML（整檔是 JSON），產品以 `json` 讀 | 零依賴；`test_ci.py` 的 `yaml.safe_load` 仍讀得懂；DUR-01 要求「人可閱讀的 JSON／YAML」，兩者都符合；但現有的 block 寫法要改，以後的人工編輯也受限 |
  | C. 自寫 YAML 子集 parser | 要自己處理邊界情況，與 AGENTS.md「修根因」及 ponytail 的「stdlib 先」都不合，列出只是為了完整 |
- 不論選哪個：profile 欄位要分欄保存 transport、runtime、provider、model、effort（DUR-09），每次改動都要新的 `policy_change`（archived design D12 L407）。`test_ci.py:51-55` 的整檔相等斷言要一起改。

## 4. 測試 harness

### 4.1 現有 fixture（[`tests/conftest.py`](../../../../tests/conftest.py)）

- `PolicyPlugin`（L25-81）：只有 `only_on(<platform>)` 在非所屬平台可以 skip；其他 skip、xfail、xpass，以及 `LOOPCTL_EXPECT_PLATFORM` 與實際平台不符，都讓 session 失敗。
- `cli(*argv)`（L129-149）：in-process 呼叫 `loopctl.cli.main`，回 `Result(code, out, stdout, stderr, exc)`；未攔截的例外放在 `exc`，`code` 為 `None`。
- `cli_proc(*argv, prelude="")`（L208-217）與 `cli_proc_many(n, …)`（L226-261）：以 `python -m loopctl` 跑子程序，`prelude` 先執行；barrier 讓 n 個程序一起開始。子程序繼承 `os.environ`（`subprocess.Popen` 沒指定 `env`，L199-205）。
- `home`（autouse，L264-270）：`LOOPCTL_HOME` 指到 `tmp_path/home`。
- `started_run`（L273-286）、`repo`（L309-317，含 `workflow.yaml` 範例，L298-305）。
- **時鐘**：不在 conftest。各測試模組以 `monkeypatch.setattr` 替換 `loopctl.clock.now`；可前進的 Clock 在 `test_approval.py:381-398`（verification §二 L68）。

### 4.2 fake `orca`／`claude`／`codex`／`ps` 的注入方式

- in-process 的 `cli` 與子程序都繼承 `os.environ`，所以 `monkeypatch.setenv("PATH", f"{fakebin}:{PATH}")` 就能讓產品以裸名稱呼叫到 fake，產品不必加任何測試開關。前提是產品以裸名稱經 PATH 找執行檔，不寫死 `/usr/local/bin/orca` 或 `/bin/ps`。PATH 是平台本來就有的注入點，符合 AGENTS.md §1。
- **參考實作的做法**（子代理讀出，抽查了 `tests/conftest.py:72-104`）：
  - `Fakes` fixture 建 `tmp/fakebin`，`setenv("PATH", …)`，另設 `FAKE_LOG`、`FAKE_SCENARIO` 兩個只給 fake 讀的環境變數；`install(*tools)` 把每個工具 symlink 到同一支 fake 腳本 `tests/fakes/bin/herdr`（97 行，`#!/usr/bin/env python3`，以 basename 判斷是哪個工具）。
  - scenario 放在 `tests/fakes/scenarios/herdr/preflight-{implementer,reviewer}.json`，頂層 `{description, calls: [{id, tool?, match, capture, stdout, stderr, exit, sleep, effects: [{write, text|json|jsonl} | {run}]}]}`，支援 `{var}` 與 `{env:NAME}` 代換；依呼叫順序嚴格比對，每次呼叫以 `{tool, argv, vars, unexpected?}` 追加到 `FAKE_LOG`。
  - fake 的 native 紀錄：`prompt` 步驟的 effect 寫 `{env:HOME}/.claude/projects/fake-project/{sid}.jsonl`，`sid` 從 `--session-id` capture；`repo` fixture 把 `HOME` 設到 tmp。`Path.home()` 在 POSIX 讀 `HOME`，所以這個注入對產品也是透明的。
  - f2 的測試另裝 `codex`、`orca` 的 fake，再斷言它們從未被呼叫，可以照搬到 AC-D23（Herdr、OpenCode 不被呼叫）。
- **等待與時間**：參考實作在測試裡把 timeout 與 poll 設成 0（`probe` fixture，test 103-114）。AGENTS.md §1 禁止「縮短重試間隔」這類只為測試存在的設定，所以這一點不能照搬，除非那個值本來就是政策檔裡給運維調整的正式設定。Orca 有阻塞式等待：`orchestration check --wait --types … --timeout-ms`、`terminal wait --for exit|tui-idle --timeout-ms`（help）。等待交給 Orca 時，fake 立即回應即可，不需要 sleep 接縫。這是 design 的選項，live probe 要確認這些 wait 在 preflight 的情境可用（§10）。
- **Codex 的家目錄**：Codex 讀 `CODEX_HOME`（預設 `~/.codex`）。fake 的 rollout 可以寫在 tmp 的 `CODEX_HOME` 或 `HOME/.codex` 下，兩者都是 Codex 本來的設定。

### 4.3 CI 與 dist-smoke

- [`.github/workflows/loopctl-ci.yml`](../../../../.github/workflows/loopctl-ci.yml)：只有 `unit-linux`（ubuntu-24.04、15 分鐘），步驟為 `uv sync --frozen` → `uv run pytest`（`LOOPCTL_EXPECT_PLATFORM=linux`）→ `ruff check` → `mypy src` → `scripts/dist-smoke.sh`（L51-66）。CI 上沒有 Orca、Claude、Codex，所以所有 pytest 都要用 fake（proposal 驗收表也這樣寫）。
- [`scripts/dist-smoke.sh`](../../../../scripts/dist-smoke.sh)：build wheel、裝進新 venv，檢查 `help`、`envelope`（`status` 的 stdout 剛好一行 JSON、鍵剛好是 6 個，L34-45）、`isolation`（`import delivery` 必須失敗）。archived design D12 L414：「不檢查 `loopctl.tools`，那屬於 Feature 2」。2a 若新增子套件，要不要在 dist-smoke 加一項，由 design 決定。
- `ps -E`（§8）是 macOS 的寫法，Linux 的 `ps` 不同；只要 CI 用 fake `ps`，就不影響 CI，但產品在 Linux 上的行為要另外界定（M1 只在本機 macOS 用 Orca）。

### 4.4 數量與時間（執行證據）

在 scratchpad 以 `git archive HEAD` 解出副本，跑 `uv run --frozen pytest -q -p no:cacheprovider`：

- 收集 171 項（69 個 `test_` 函式，參數展開後）；
- 第一次 170 passed、1 failed：`test_ci.py::test_pytest_policy_has_one_source` 呼叫 `git ls-files`，而副本不是 git repo；
- 在副本 `git init && git add -A` 後重跑：171 passed，12.59 秒。

## 5. Orca CLI 介面（1.4.218）

以下用法行都是 `--help` 的原文。

### 5.1 自訂 terminal

| 命令 | 用法 | 重點 |
| --- | --- | --- |
| `terminal create` | `orca terminal create [--worktree <selector>] [--title <name>] [--command <text>] [--shell <shell>] [--focus] [--json]` | `--command <text>`：「Command to run in the terminal on startup」；「`--command` is typed into whatever shell the host started」；「macOS and Linux execution hosts spawn the login shell」。沒有 argv、cwd 或 env 參數；cwd 由 `--worktree` 決定。selector 有 `identity:`、`id:<repo-id>::<path>`、`name:<displayName>`、`branch:`、`path:`、`active/current` |
| `terminal list` | `orca terminal list [--worktree <selector>] [--limit <n>] [--include-visual-layouts] [--json]` | 欄位：`handle`、`title`、`agentIdentity`、`ptyId`、`incarnationId`、`connected`、`orphaned`、`writable`、`worktreeId`、`worktreePath`、`branch`、`lastOutputAt`、`preview`、`tabId`、`leafId`、`executionHostId`。**沒有 pid** |
| `terminal show` | `orca terminal show [--terminal <handle>] [--json]` | 同上，另有 `paneRuntimeId`、`rendererGraphEpoch`。**沒有 pid** |
| `terminal close` | `orca terminal close ([--terminal <handle>] [--tab] \| --worktree <selector> --all) [--json]` | 「`--worktree <selector> --all`, stops every terminal process owned by that workspace」。09-25 實測的 receipt 有 `ptyKilled: true`（[runtime-probe.md](../../2026-09-25/runtime-probe.md) L36） |
| `terminal wait` | `orca terminal wait [--terminal <handle>] --for exit\|tui-idle [--timeout-ms <ms>] [--json]` | 可等 terminal 結束或 TUI 閒置 |
| `terminal read` | `orca terminal read [--terminal <handle>] [--cursor <n>] [--limit <n>] [--screen] [--json]` | 讀 terminal 輸出，不是 native 紀錄 |

`agentIdentity` 在跑 claude 的 terminal 會顯示 `claude`（本機 `terminal list` 實測）；`--title` 可設成 marker，之後用 `terminal list` 找殘留的探測 terminal（design 選項）。`status --json` 列出 capability `terminal.create-idempotency.v2`，但 `terminal create` 的 help 沒有對應的 request ID 參數，能否冪等建立未知。

### 5.2 Supervised worker

- **`worker-start`**：`orca orchestration worker-start (--task <task_id> | --spec <text>) [--on <saved-environment>] [--worktree <current|selector|new-child|new-top-level>] (--agent <agent> | --terminal <handle>) [--task-title <text>] [--deps <json_array>] [--parent <task_id>] [--model <id>] [--effort <level>] [--name <name>] [--repo <selector>] [--base-branch <ref>] [--display-name <text>] [--comment <text>] [--setup <run|skip|inherit>] [--retry-of <dispatch_id>] [--timeout-ms <n>] [--run <run_id>] [--from <handle>] [--retry-request <id>] [--json]`
  - 「When reusing --terminal, pass --worktree for that terminal」；「`--model` … `--effort` requires `--model`. Neither can combine with `--terminal`」。
  - 「How the worker runs follows the user's own setting for new agent tabs; there is no flag for it」（verification §二：指執行模式，不是權限）。
  - 「The start receipt records which one ran」；「The call exits 0 only for ready. Failed or outcome_unknown exits 1 and JSON includes stage/failedStage, setup, effects, residualResources, and recovery commands」。
  - 有 `--run <run_id>`，可以不靠 terminal 綁定指定 Run。
  - 09-25 實測（runtime-probe.md L22、L25）：`worker-start --worktree current --terminal …` 因 workspace suffix 不同被拒，改用 terminal receipt 的完整 workspace ID 才成功；Codex 以自訂 argv（`--sandbox workspace-write --ask-for-approval never`）加 `worker-start --terminal` 成功 ready。
  - skill 的 low-level topology（L364-386）：`terminal create … --command "<agent_command>"` 之後，要擁有 lifecycle 就用 `worker-start --terminal <handle>`；`dispatch --inject` 只建 context、不擁有程序。
- **`worker-show`**：`--dispatch <dispatch_id> [--json]`。「`observation.agentWait` names a worker parked on a prompt only a human can answer…A waiting worker is healthy, not failed」。先前實測的 `dispatch` 欄位有 `assigneeHandle`、`processIncarnation`、`lastHeartbeatAt`、`terminationReason` 等（research §4），沒有 pid。
- **`worker-list`**：`[--run <run_id>] [--terminal-state <active|reclaimable|retained|release_pending|release_unknown|released>] …`。「Terminal state is process accounting and is reported separately from Task status」；`projection.liveness` 為 `live`／`unverifiable`／`exited`（skill L57-58、L581-601）。
- **`worker-read`**：`--dispatch <id> [--source <auto|transcript|terminal>] [--cursor] [--limit]`。「The default auto source uses an exact hook-reported transcript when available」。正規化後只有 text、tool-call、tool-result 三種 block（verification §二 L41），所以不能取代 native 紀錄。
- **`worker-stop`**：`--dispatch <id> [--retry-request <id>]`。「Never deletes the worktree, setup terminal, configured tabs, or unrelated processes」。外部 terminal 會回 `stop_unknown`（runtime-probe.md L36）。
- **`worker-abandon`**：「Retains all possibly-live resources and performs no process or filesystem action」。
- **`worker-release`**：「Never closes setup terminals, configured tabs, reused or pre-existing terminals, user-taken-over terminals, or unproven identities」。

所以在自訂 terminal 這條路上，停止探測 worker 的實際動作是 preflight 自己的 `terminal close`（或對程序送 signal），之後由 process-info 確認（待決 1 已接受這個代價）。

### 5.3 Worker 必須能執行的命令

- **`send`**：`orca orchestration send --subject <text> [--to <run:id|dispatch:id|legacy_handle>] [--run <run_id>] [--from <handle>] [--body <text>] [--type <type>] … [--task-id <id>] [--dispatch-id <id>] [--outcome <succeeded|failed>] [--files-modified <csv>] [--report-path <path>] [--phase <text>] [--retry-request <id>] [--json]`。選項另列 `--dispatch-capability`（usage 行沒列）。「worker_done requires --outcome succeeded or --outcome failed」；「A worker_done with the active task/dispatch IDs completes that task only from the dispatched pane」。
- **`check`**：`orca orchestration check [--terminal <handle>] [--run <run_id>] [--ack <delivery_id>] [--unread | --peek | --all] [--types <type,...>] [--format] [--wait] [--timeout-ms <n>] [--retry-request <id>] [--json]`。worker 端用 `check --terminal <handle>`（skill L758），協調者端可用 `--wait`。
- **`ask`**：`orca orchestration ask (--question <text> | --resume <message_id>) [--to <run:id>] [--run <run_id>] [--options <csv>] [--timeout-ms <n>] [--from <handle>] [--retry-request <id>] [--json]`，也有 `--dispatch-capability`。
- skill 的 worker contract（L719-795）：preamble 是權威；「Copy its command rather than reconstructing flags…preserve the exact executable, worker handle, Dispatch capability, Task ID, and Dispatch ID」。worker 會執行 `ORCA orchestration send --from <worker_handle> --dispatch-capability <capability> --type worker_done …`。
  - 影響一：worker 的 Bash 命令列會帶 `dcap_` 值，native transcript 的 `tool_use` 也會原樣記錄，receipt 的摘錄必須遮蔽（verification §三 L91）。
  - 影響二：Claude 的 allow 規則要符合 preamble 實際用的執行檔寫法（可能是 `orca`、`/usr/local/bin/orca` 或 app bundle 路徑），只能由 live probe 讀 preamble 確認。

### 5.4 其他

- **`status --json`**：`result.runtime.appVersion`、`runtime.capabilities[]`（102 項，含 `orchestration.worker-stop-verdict.v1`、`orchestration.worker-launch-preferences.v1`、`orchestration.contract.v1`、`agent.launch.v2`、`terminal.create-idempotency.v2`）、`runtime.state`、`runtime.reachable`、`runtime.connectionState`、`graph.state`、`app.running`、`app.pid`（Orca app 自己的 pid）。
- **`run-create`**：`--objective <text> [--from <handle>] [--retry-request <id>]`，「Create and bind a lightweight orchestration Run」；「A Run is a namespace and home inbox. It never schedules or places workers」。會綁定呼叫者的 terminal（research §4：`run-create`／`run-use` 會解除其他綁定）。preflight 若從協調者的 Orca terminal 呼叫，可能改到協調者自己的 Run 綁定。
- **`run-current`**：`[--from <handle>]`，「Show the Run bound to this coordinator terminal」。
- **`request-show`**：`--request <request_id>`。「absent means this runtime holds no receipt for that request under your caller identity…Absent is not proof that nothing happened」。
- **`dispatch-show`**：`--task <task_id> [--preamble] [--from <handle>]`，可讀實際注入的 preamble（verification §三 L81）。
- **版本讀取成本**（本機計時）：`orca --version` 0.13 秒、`orca status --json` 0.18 秒、`claude --version` 0.17 秒、`codex --version` 0.04 秒。

### 5.5 探測工作區的現況（與先前研究不同）

| 項目 | 現況（`repo list`、`worktree list`、`git -C … rev-parse`） |
| --- | --- |
| Orca repo | `loop-engineering`，`kind: git`，`path: /Users/johnson.chiang/workspace/loop-engineering`，id `51c06003-80e7-43a0-9ced-35894a995a97`；另一個是 `cross-node-xfer`（folder） |
| 工作區 | `preflight-engineer`：`/Users/johnson.chiang/orca/workspaces/loop-engineering/preflight-engineer`，branch `yschiang/preflight-engineer`；`preflight-reviewer`：同目錄下的 `preflight-reviewer`，branch `yschiang/preflight-reviewer`。兩者 `baseRef: main`，HEAD `458ab77`，`cliProvenance.kind: created-by-cli` |
| git 佈局 | 兩者的 `--git-common-dir` 都是 `/Users/johnson.chiang/workspace/loop-engineering/.git`（linked worktree），不是獨立 clone |
| terminal | 兩個工作區各有一個 `Terminal 1`（`agentIdentity: null`，shell） |

先前研究寫「loop-engineering 沒有註冊、沒有 `engineer`／`reviewer` 工作區」（research §4、§9 事實 4），那是當時的快照；待決 6 的一次性設定已由人完成，名稱是 `preflight-engineer`／`preflight-reviewer`，不是 D76(1) 的 `engineer`／`reviewer`。

## 6. Agent CLI 的旗標

### 6.1 Claude Code 2.1.288（`claude --help`）

| 旗標 | help 原文（節錄） |
| --- | --- |
| `--model <model>` | 「Model for the current session. Provide an alias…or a model's full name」 |
| `--effort <level>` | 「Effort level for the current session (low, medium, high, xhigh, max)」 |
| `--settings <file-or-json>` | 「Path to a settings JSON file or a JSON string to load additional settings from」 |
| `--setting-sources <sources>` | 「Comma-separated list of setting sources to load (user, project, local)」 |
| `--permission-mode <mode>` | choices：`acceptEdits`、`auto`、`bypassPermissions`、`manual`、`dontAsk`、`plan` |
| `--session-id <uuid>` | 「Use a specific session ID for the conversation (must be a valid UUID)」 |
| `--allowedTools`／`--disallowedTools <tools...>` | 「Comma or space-separated list of tool names to allow/deny (e.g. "Bash(git *) Edit")」 |
| `--bare` | 「skip hooks (those defined in settings and by installed plugins…), LSP, plugin sync…CLAUDE.md auto-discovery…Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and keychain are never read)」 |
| `--safe-mode` | 「Start with all customizations (CLAUDE.md, skills, installed plugins, hooks, MCP servers…) disabled…permissions work normally」 |
| `--restricted` | 移除會執行命令的內建工具，並「ignores user, project and local settings files (managed settings and --settings still apply…)」 |
| `--plugin-dir <path>` | 「Load a plugin from a directory or .zip for this session only」 |
| `--strict-mcp-config`、`--mcp-config` | 只用指定的 MCP |
| `--dangerously-skip-permissions` | Orca 目前的預設（verification §一 1） |
| `--include-hook-events` | 只在 `--print` 加 `stream-json` 時有效 |

- `claude plugin enable|disable` 會改使用者的全域設定，不適合 preflight（proposal「不做」：不改使用者的 Orca 全域設定，同理也不該改 Claude 的）。
- 使用者設定的結構（只讀鍵名）：`~/.claude/settings.json` 頂層有 `effortLevel`、`enabledPlugins`、`env`、`extraKnownMarketplaces`、`hooks`、`language`、`model`（目前是 `opus`；verification 當時記為 haiku）、`modelSettings`、`skipDangerousModePermissionPrompt`、`statusLine` 等。
  - `enabledPlugins`：`ralph-wiggum@claude-code-plugins`、`clangd-lsp@claude-plugins-official`、`gopls-lsp@claude-plugins-official`、`superpowers@claude-plugins-official`、`ponytail@ponytail`、`frontend-design@claude-plugins-official`，全部是 `true`。
  - `env` 的鍵：`ANTHROPIC_BASE_URL`（本機 gateway）、`ENABLE_TOOL_SEARCH`、`_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`。
  - hooks：Orca 13 個（`PermissionRequest`、`PostCompact`、`PostToolUse`、`PostToolUseFailure`、`PreToolUse`、`SessionEnd`、`SessionStart`、`Stop`、`StopFailure`、`SubagentStart`、`SubagentStop`、`TeammateIdle`、`UserPromptSubmit`）；caveman 11 個；Herdr 1 個（`SessionStart`）。Orca 的 hook 是 inline shell，只在有 `ORCA_AGENT_HOOK_PORT`／`ORCA_AGENT_HOOK_TOKEN` 時才回報。
  - 沒有 `settings.local.json`。
- **待決 2 的效果怎麼組**（只列可用的機制，不判定）：
  - `disableAllHooks: true`（Feature 1 的做法，`settings.template.json` 只有 `disableAllHooks` 與 `permissions` 兩個鍵）會連 Orca 的 hook 一起關掉，Orca 的 liveness 與 hook 回報的 transcript 都會失效（verification §一 1、§三 L76）。
  - 不同設定來源的 `hooks` 是合併，以 `--settings` 無法移除 user 來源的 caveman、Herdr hook。要排除它們，看起來只能不載入 `user` 來源（`--setting-sources project,local`），再用 `--settings` 補回 Orca hook、gateway 的 `env` 與 `enabledPlugins`。但 plugin 是裝在 user 層級，user 來源被排除時 `--settings` 的 `enabledPlugins` 能不能啟用 superpowers，沒有文件證據，要 live probe。
  - `--bare` 與 `--safe-mode` 會關掉所有 hook 與 plugin，也不符合待決 2。
  - ponytail、ralph-wiggum 的作用主要來自它們自己的 hook（本 session 收到的 ponytail 指示就是 SubagentStart hook 注入的）；`enabledPlugins` 設成 `false` 才會連 skill 一起拿掉。

### 6.2 Codex CLI 0.157.0（`codex --help`）

| 旗標 | help 原文（節錄） |
| --- | --- |
| `-m, --model <MODEL>` | 「Model the agent should use」 |
| `-c, --config <key=value>` | 「Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`. Use a dotted path…parsed as TOML」。effort 的設定鍵是 `model_reasoning_effort`（`~/.codex/config.toml` 第 2 行） |
| `-s, --sandbox <SANDBOX_MODE>` | `read-only`、`workspace-write`、`danger-full-access` |
| `-a, --ask-for-approval <APPROVAL_POLICY>` | `on-request`、`never`（「Execution failures are immediately returned to the model」） |
| `-p, --profile <CONFIG_PROFILE_V2>` | 「Layer $CODEX_HOME/<name>.config.toml on top of the base user config」 |
| `-C, --cd <DIR>`、`--add-dir <DIR>` | 工作根目錄、額外可寫目錄 |
| `--dangerously-bypass-approvals-and-sandbox` | Orca 目前的預設 |
| `--dangerously-bypass-hook-trust` | Codex 有自己的 hook 機制與信任紀錄 |
| `--no-daemon` | 「Run without the shared background server, even if it is already running」 |
| `--strict-config` | 設定檔有不認得的欄位就報錯 |

- **沒有指定 session ID 的旗標**；session ID 由 Codex 產生，等於 rollout 檔名裡的 uuid（§7.2）。
- **Unix socket**：`--allow-unix-socket` 只在 `codex sandbox` 這個工具命令（`codex sandbox [OPTIONS] [COMMAND]...`，另有 `-P, --permission-profile`、`--log-denials`）。interactive 的 `codex` 沒有這個旗標。09-25 證明 `codex sandbox -P :read-only --allow-unix-socket <socket>` 能連上 Orca，但「單一 socket allowance 只限制連線目標，不限制 RPC 方法」（[integration-gaps.md](../../2026-09-25/integration-gaps.md) L7-9）。interactive TUI 用什麼設定鍵放行 socket，沒有查到。
- **Shared daemon**：`codex agents` 是「Browse all agent sessions on the shared local app-server daemon」，`~/.codex/app-server-daemon/` 存在；本機目前有 4 個 `codex app-server` 程序，父程序是 Cursor。若 interactive codex 的 turn 跑在共享 daemon 裡，關掉 TUI 不一定停止 agent，process-info 的對象要重新界定（§10）。
- **使用者 Codex 設定**（只讀鍵名）：頂層 `model = "gpt-6-astra"`、`model_reasoning_effort = "high"`、`notify`；11 個 `[plugins.*]`（documents、spreadsheets、presentations、pdf、template-creator、chrome、browser、computer-use、codex-app-tools、unified-computer-use、visualize）；`[features] hooks、js_repl`；`[mcp_servers.node_repl]`、`[mcp_servers.computer-use]`；`[hooks.state]` 的信任紀錄。`~/.codex/hooks.json` 有 8 種事件、9 個 hook 指令，都含 orca 字樣（其中一處也出現 herdr 字樣）。
- **Orca 的 Codex 家目錄**：`~/Library/Application Support/orca/codex-runtime-home/home/` 有 `config.toml`、`hooks.json` 等，但**沒有 `sessions/`**。Orca 設定沒有啟用的 managed account（`activeCodexManagedAccountId` 為 null、`codexManagedAccounts` 為空），所以自訂 terminal 裡的 codex 很可能用 `~/.codex`；要 live probe 確認。

### 6.3 Orca 的全域 agent 設定（只讀）

`~/Library/Application Support/orca/profiles/local-default/orca-data.json` 的 `settings`：

- `agentDefaultArgs.claude = "--dangerously-skip-permissions"`、`agentDefaultArgs.codex = "--dangerously-bypass-approvals-and-sandbox"`；
- `agentCmdOverrides = {}`、`agentDefaultEnv` 沒有鍵；
- `agentStatusHooksEnabled = true`、`openAgentTabsInChatByDefault = false`、`defaultTuiAgent = "claude"`。

與 verification §一 1 相同；待決 1 已決定不改這些。

## 7. Native 紀錄（只讀欄位名稱）

### 7.1 Claude Code

- **路徑規則**：`~/.claude/projects/<dir>/<sessionId>.jsonl`。`<dir>` 是把 cwd 的每個非英數字元換成 `-`（`re.sub(r"[^A-Za-z0-9]", "-", cwd)`；子代理比對 23 個含特殊字元的目錄，全部相符）。這個轉換有損，不同 cwd 可能撞名。subagent 另存在 `<dir>/<sessionId>/subagents/agent-<id>.jsonl`。探測工作區的 `<dir>` 依此規則是 `-Users-johnson-chiang-orca-workspaces-loop-engineering-preflight-engineer`（推得，尚無檔案）。
- **`--session-id` 的證據**：Feature 1 的 `dispatch.sh` 以 `uuid4` 產生 SID，寫進 `attempt-N/session-id`，再以 `claude -p … --session-id $SID` 啟動（`dispatch.sh:7`、`12`）。18 個 attempt 的 SID 全部找得到 `<SID>.jsonl`，transcript 裡的 `sessionId` 只有一個值，且等於檔名。這些都是 `-p`；interactive 模式下 `--session-id` 是否同樣決定檔名，要 live probe（參考實作的設計假設它成立）。
- **欄位**（`user`、`assistant`、`attachment`、`system` 共同）：`cwd`、`gitBranch`、`sessionId`、`version`（Claude Code 版本）、`userType`、`entrypoint`（`cli` 為互動、`sdk-cli` 為 `-p`）、`isSidechain`、`parentUuid`、`uuid`、`timestamp`。
  - model：`assistant.message.model`。
  - effort：`assistant` 頂層的 `effort` 與 `perTurnEffort`（不在 `message` 裡）；見過 `medium`、`high`、`xhigh`、`max`。我抽查了一個 Feature 1 檔案，`effort`、`perTurnEffort`、`cwd`、`gitBranch`、`sessionId`、`version` 都在 `assistant` 頂層。
  - 權限模式：`user` 的 prompt 紀錄有 `permissionMode`；另有獨立的 `permission-mode` 紀錄。見過 `default`、`auto`、`bypassPermissions`、`dontAsk`。
- **被拒的工具呼叫**：`type: user`，頂層 `toolDenialKind`（`permission-rule`、`user-rejected`、`interrupted`），`message.content[0]` 為 `{type: tool_result, tool_use_id, content, is_error: true}`，`toolUseResult` 是以 `Error: ` 開頭的字串。措辭形如「Permission to use <Tool> has been denied because Claude Code is running in don't ask mode…」（我抽查了一筆 `permission-rule`，鍵與 `is_error` 都相符）。
  - 對 AC-D27：「被 agent CLI 的權限拒絕而沒有執行」可以從 `toolDenialKind` 判定，比參考實作的文字 regex（`DENIAL`，參考實作 `preflight.py:47`）更有結構。
  - 「worker 嘗試了」可以用 `tool_use.id` 對到 `tool_result.tool_use_id`，比對 `tool_use.input` 的命令。
- **stream-json（只在 `-p`）**：`system/permission_denied` 事件（`decision_reason_type`：`mode`、`subcommandResults`），結束時 `result.permission_denials[]`；`system/init` 有 `plugins[]`（`{name, path, source, version}`）、`mcp_servers[]`、`tools`、`skills`、`permissionMode`、`model`、`claude_code_version`、`apiKeySource`。Orca 的 worker 是 interactive，不會有這些事件。
- **載入的設定**：interactive transcript 沒有 plugin 清單，也沒有 settings 來源清單。間接證據有：
  - `attachment.type = hook_success`（`hookName`、`hookEvent`、`command`、`exitCode`…），以及 `hook_additional_context`、`hook_cancelled`、`hook_system_message`；
  - `system/stop_hook_summary`（`hookInfos[{command, durationMs}]`）；
  - `skill_listing`（`names`、`skillCount`）：plugin 的 skill 名稱帶 `<plugin>:` 前綴；
  - `instructions.files[{path, type}]`；
  - `mcp_instructions_delta.addedNames`。
  - gateway（`ANTHROPIC_BASE_URL`）在 transcript 是否有紀錄，沒有查到；`attachment` 有 `environment.snapshot` 一類，內容未讀。
- **API 錯誤**：`system/api_error` 的鍵有 `level`、`error{…}`、`retryInMs`、`retryAttempt`、`maxRetries`、`source`（verification §二 L52 已說明判定方式）。
- **保留期**：約 30 天（verification §三 L90）。

### 7.2 Codex

- **路徑規則**：`$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<YYYY-MM-DDTHH-MM-SS>-<uuid>.jsonl`；第一筆 `session_meta.payload.id` 等於檔名的 uuid（341/341）。另有 `rollout-<ts>-<uuidA>_<uuidB>.jsonl`（14 檔）。一個檔可能有多筆 `session_meta`。subagent 的 rollout 也在同一目錄，`source` 為 `{subagent: …}`，`session_id` 是根 session 的 id（verification §三 L82：要選 root thread）。本機共 355 個 rollout、1.2 GB。
- **`session_meta.payload`**：`id`、`session_id`、`cwd`、`cli_version`、`originator`（`codex_exec`、`codex-tui`、`Codex Desktop`…）、`source`、`model_provider`、`git{commit_hash, repository_url}` 等。
- **`turn_context.payload`**：`model`、`effort`、`cwd`、`workspace_roots`、`approval_policy`（`never`、`on-request`、`{granular}`）、`sandbox_policy`（`type`：`read-only`、`workspace-write`（另帶 `writable_roots`、`network_access`…）、`danger-full-access`）、`file_system_sandbox_policy`、`permission_profile{type, file_system, network}`、`active_permission_profile{id, extends?}`、`disabled_plugin_ids`、`turn_id`。我抽查了最新一份 rollout：`gpt-6-astra`、`xhigh`、`read-only`、`never`。
- **sandbox 拒絕**：沒有結構化標記（找不到 `sandbox_denied`、`exec_approval_request`、`exec_command_end`）。命令執行記在 `event_msg/item_completed` 的 `CommandExecution`（`command`、`cwd`、`exit_code`、`status`、`stderr`、`stdout`、`aggregated_output`、`process_id`…）與 `response_item/custom_tool_call(_output)`。拒絕只能從 stderr 或 output 的 `Operation not permitted`（EPERM）看出，而且有時 `exit_code` 仍是 0。AC-D27「被 sandbox 拒絕而沒有執行」對 Codex 的判定方式，要由 live probe 的實際紀錄決定。
- **載入的設定**：沒有 hook 或 MCP 清單。間接證據：`world_state.state`（`skills`、`plugins_instructions`、`permissions{approved_command_prefixes, …}`…）、`thread_settings_applied.thread_settings`（`model`、`reasoning_effort`、`approval_policy`、`permission_profile`、`disabled_plugin_ids`）、`McpToolCall` 的 `server`、`pluginId`。

### 7.3 「恰好一份含 marker」的搜尋範圍

- 本機 `~/.claude/projects` 有 365 個 jsonl、516 MB；`~/.codex/sessions` 有 355 個、1.2 GB。全掃可行，但每次 preflight 都要讀上 GB 的資料。
- 協調者自己也可能是一個 Claude 或 Codex session。preflight 的輸出（含 marker）一旦印給協調者，協調者的 transcript 也會含 marker。同一次執行中，輸出是在讀回之後才印，所以不影響這次判定；但「恰好一份」的定義（只算 `user` prompt 裡的 marker？排除 `tool_result`？只看探測 cwd 對應的目錄？）要由 design 寫清楚，否則下一次讀回可能把協調者的紀錄算進去。

## 8. process-info

- **Orca 不給 agent 的 pid**：`terminal list`／`terminal show` 沒有 pid（§5.1）；`worker-show` 只有 `processIncarnation` 等（research §4）；`status --json` 的 `app.pid` 是 Orca app。skill 也說「The execution host owns process, filesystem, transcript, stop, and cleanup facts」（L538），但沒有對外的 pid 欄位。
- **Claude**：loopctl 自己產生 `--session-id <uuid>`，所以 uuid 在 claude 程序的 argv 裡。`ps -axo pid,command` 或 `pgrep -f <uuid>`（`/usr/bin/pgrep` 存在）就能確認程序在不在。這個 uuid 在派工前就能持久記錄，AC-D31 的殘留清理也能用它。子代理看到 Feature 1 的 `-p` 程序在執行中確實帶 `--session-id`；目前沒有這類程序在跑。
- **Codex**：沒有 session-id 旗標，可行的 argv 標記要另外設計。
- **Orca PTY 的環境變數**：本 terminal 的環境有 `ORCA_TERMINAL_HANDLE`、`ORCA_PANE_KEY`、`ORCA_TAB_ID`、`ORCA_WORKTREE_ID`、`ORCA_AGENT_HOOK_*`、`ORCA_AGENT_LAUNCH_TOKEN` 等。在 macOS 上，`ps -Eww -axo pid=,command=` 會列出同一使用者程序的環境；實測以本 terminal 的 handle 比對，找到 5 個程序（shell 與其子孫）。所以「環境裡帶探測 terminal 的 `ORCA_TERMINAL_HANDLE`」可以找出 terminal 內的所有程序，Claude 與 Codex 都適用。限制：
  - `ps -E` 的輸出含其他程序的 token（例如 `ORCA_AGENT_HOOK_TOKEN`），只能在記憶體比對，不能寫進 receipt 或紀錄；
  - 這是 macOS 的 BSD `ps` 寫法；Linux 要讀 `/proc/<pid>/environ`；
  - `--command` 打進的是 login shell，所以 shell 本身也帶同一個 handle。判定「探測 agent 已不存在」要排除 shell，或在 `terminal close` 之後確認整組都不存在。
- **另一種標記**：`--command` 是 shell 文字，可以在前面加一個環境變數（例如 `LOOPCTL_PROBE=<marker> claude …`），讓 agent 程序帶一個 loopctl 自己的標記。這是 design 選項，可行性要 live probe。
- **參考實作**：完全靠 Herdr 的 `pane process-info`（前景程序全部是 `shell_pid` 才算停止），沒有用 `ps` 或 `pgrep`（子代理讀出：參考實作 `preflight.py:214-216`、`tools/herdr.py:210-214`）。
- **Codex 的 shared daemon**：若 turn 跑在 `codex app-server` daemon 裡，terminal 內的程序消失不代表 agent 停了（§6.2）；`--no-daemon` 可能避開，要 live probe。

## 9. 參考實作（`fcefecc`）的對照

參考實作只作參考（D75）；子代理讀出各行號，我抽查了 `preflight.py:1-11`、`83-92`、`361-373`、`workflow.yaml:28-30`、`tests/conftest.py:72-104`。

| 參考實作 | 內容 | 2a 可借用的做法 | 不能沿用的部分 |
| --- | --- | --- | --- |
| docstring `preflight.py:1-11` | 「Never reads or writes feature state」；只 import `clock`、`tools`、`herdr` | 與 DUR-09「不寫 feature 狀態」一致 | — |
| `_claude_native` `preflight.py:83-116` | glob `~/.claude/projects/*/{session_id}.jsonl`；以第一筆含 marker 的 `user` 為起點；`cwd`、`version` 取起點；`model` 取 `message.model`；`effort` 取頂層或 `message.effort`；`end_turn` 判定完成；`tool_use.id` 對 `tool_result.tool_use_id` | 起點、欄位與工具呼叫配對都能照抄思路 | 沒有核對「恰好一份含 marker」；不讀 `gitBranch`；不讀 `permissionMode`、`toolDenialKind` |
| `_opencode_native` `preflight.py:119-148` | OpenCode export | — | OpenCode 專屬。參考實作**完全沒有讀 Codex rollout**，要新寫 |
| `_location` `preflight.py:158-168` | 由 cwd 以 git 讀 `remote get-url origin`、`rev-parse --show-toplevel`、`symbolic-ref --short -q HEAD` | DUR-09「再讀出該目錄的 repo 與 branch」 | requested 的 repo 取自 `policy["repo"]`；2a 要和探測工作區比對 |
| `_negatives` `preflight.py:171-182`；判定 `361-373` | 五個基本負例（每個有 `name/command/resource`）；reviewer 加 `write_author_worktree`。`denied` = 原生 `calls` 中 input 含 resource、`is_error`、output 符合 `DENIAL` regex；`resource_unchanged` = 前後 `_digest` 相同；`verified = denied and resource_unchanged` | 「嘗試＋被拒＋資源不變」三者都要，正好是 AC-D27 | `herdr` 負例換成 `orca` 子命令；遠端 ref、Orca 物件、`gh` 寫入、狀態 revision 的資源檢查要新寫；`DENIAL` 上方有一行 `ponytail:` 註解（L46），AGENTS.md §2 不允許 |
| `_review_clone` `preflight.py:185-199` | `git clone --no-hardlinks` 後重設 origin | GAT-05 的獨立 clone（待決 7） | 2a 的探測工作區由人預先建立（待決 6），是 linked worktree |
| `_prompt` `preflight.py:202-211` | 要 agent 逐條嘗試、不繞過，最後以 marker 結尾 | 任務內容 | 2a 的任務經 Orca 交付，要讓 worker 把它當任務並送 `worker_done` |
| `static_reasons` `preflight.py:243-265`；`_claude_settings_reasons` `227-240` | `profile_missing:`、`profile_model_missing:`、`models_identical:`、`profile_settings_missing:`；設定檔要有 `disableAllHooks: true` | `models_identical` 對應 AC-G23；`profile_model_missing` 對應 AC-D19 | 要求 `disableAllHooks` 與待決 2 衝突（要保留 Orca hook） |
| `_probe` `preflight.py:268-407` | marker `LOOPCTL-PF-{token_hex(6)}`；臨時 probe 目錄與 bare repo；派工前取版本；以 `clock.now()` 加 timeout、`time.sleep(poll_worker_s)` 輪詢 | marker 形式、先取版本 | Herdr 的開 worktree、啟動、送 prompt 步驟；sleep 輪詢（§4.2）；沒有「派工前先持久記錄 marker 與 handle」 |
| stop `preflight.py:375-395` | `RUNTIMES` 的 ctrl+c 鍵，接著 `herdr pane process-info` 讀回 | 有界的讀回次數 | 全部是 Herdr 的機制 |
| reason 字串 | `workflow_unreadable:`、`herdr_version_unsupported:`、`herdr:<step>:<code>`、`native_record_missing`、`no_native_turn`、`runtime_version_missing`、`model_mismatch`、`effort_mismatch`、`native_cwd_missing`、`location:<item>`、`negative_not_denied:<n>`、`negative_resource_changed:<n>`、`stop_unconfirmed` | 命名風格 | Herdr／OpenCode 專屬的幾個 |
| receipt（`run` `preflight.py:410-440`） | `role`、`observed_at`、`herdr_session`、`workflow_digest`、`profile`、`profile_digest`、`settings_digest`、`marker`、`probe_dir`、`agent_name`、`review_clone`、`herdr_version`、`runtime_version`、`native_session_id`、`model{requested,observed,verified}`、`effort{…}`、`effort_verified`、`location{requested,actual,items}`、`negatives[]`、`stop{…}`、`verdict`、`reasons`；寫到 `--out` 指定的路徑 | 欄位骨架 | 沒有 receipt 自身 digest、沒有遮蔽、沒有脈絡 run、沒有 transport 版本以外的 agent CLI 版本來源（只從 native 紀錄取 `version`）、沒有固定的儲存位置與「最新一份」 |
| `tools/__init__.py:14-31` | `run(argv, timeout_s, cwd=None)`：不經 shell、繼承 env、stdout 寫 TemporaryFile；非 0、OSError、timeout 都丟 `ToolError` | 有時限的子程序呼叫 | — |
| `tools/herdr.py` | `op_call` 回 `{outcome, reason, receipt, facts}`；`readback` 回 `{result: confirmed\|pending\|absent\|mismatch\|transport_error}`；`kind == "stop"` 固定回 `unknown/stop_unconfirmed`，因為只有 process-info 能證明 | 回傳形狀；「stop 只有 process-info 能證明」的原則 | 全部 argv 與錯誤碼 |
| `profiles/implementer.claude-settings.json` | `disableAllHooks: true`、`permissions.defaultMode: dontAsk`；allow 有 `Read`、`Edit(./**)`、`Write(./**)`、`uv run …`、`git status|diff|log|show|add|commit|rev-parse *`；deny 有 `git push *`、`gh *`、`herdr *`、除 `evidence red` 外的每個 `loopctl` 子命令、`WebFetch`、`WebSearch` | allow／deny 的形狀；測試強制 Bash 規則寫成 `Bash(<prefix> *)` | `disableAllHooks`；`Bash(orca *)` 不能整個拒絕（worker 要送 `worker_done`）；沒有 Codex 的 reviewer profile |
| 依賴 | `pyyaml>=6.0` 是唯一執行依賴 | — | main 的 D1 不採用（§3） |
| store | `store.load(feature)` 以 feature 為鍵 | — | preflight 本來就不用 store；main 以 repo＋feature 為鍵 |
| 測試 | `test_preflight.py` 36 個 `test_`（展開約 87 項）；fake scenario 與 PATH 注入 | §4.2 | timeout／poll 設 0 的做法 |

## 10. 風險與只有 live probe 能回答的事

### 10.1 已知風險（有證據）

1. **Reviewer 的工作區不是獨立 clone**（§5.5）。GAT-05 的文字是「SHALL 使用獨立的 clone」；現在的 `preflight-reviewer` 與 `preflight-engineer` 共用 `.git`，Reviewer 只要能寫 `.git/refs` 就能移動 `yschiang/preflight-engineer`。AC-G24 若靠 Codex sandbox 擋下，負例會成立，但「獨立 clone」這句仍不成立。待決 7 交給 design。
2. **`run-create` 會綁定呼叫者的 terminal**（§5.4）。preflight 若在協調者的 Orca terminal 裡建立 Run，會解除協調者原本的綁定。
3. **AGENTS.md §1 與輪詢**（§4.2）：不能為了測試把 poll／timeout 設成 0，除非那是正式的政策值。
4. **worker 的命令列帶 `dcap_`**（§5.3），native 紀錄也會有；receipt 的摘錄要遮蔽，`ps -E` 的輸出不能保存（§8）。
5. **Feature 1 的設定範本不能照搬**（§6.1）：`disableAllHooks` 會關掉 Orca hook，`Bash(orca *)` 整個拒絕會擋掉 `worker_done`（verification §一 1）。
6. **版本會自己更新**：Orca 09-25 是 1.4.209、10-01 是 1.4.215、10-03 是 1.4.218；Claude Code 從 2.1.285 到 2.1.288，Codex 從 0.153.4 到 0.157.0（verification §二 L49）。這正是 D81 的「換版就重跑」；receipt 的適用判定每次 `status`／`next` 都要讀版本，本機成本約 0.2 秒（§5.4）。

### 10.2 只有 live probe 能回答的事

整理成可授權的探測步驟，見文末「live probe 清單」。

## 事實／假設／未知

### 事實（本次以原始來源查證）

1. `status`、`next` 的 envelope `next` 都直接來自狀態檔（`cli.py:190-224`）；`derive` 是純函式，核准後回 `dispatch`（`next.py:60-79`）；政策狀態只在 `status` 讀取時計算（`state.py:100-123`）。
2. 產品程式不讀 YAML，執行期零依賴；pyyaml 6.0.3 只在 dev（`pyproject.toml`、`uv.lock:196-203`）。`test_ci.py:51-55` 斷言 `workflow.yaml` 剛好三個鍵。
3. `store.py` 有 content-addressed 的 `put_object`／`get_object`（讀回時核對 digest），以及私有的 write-once、fsync、`os.link`、`os.replace` helper；run 的 `lock` 只由 `init` 建立。
4. 171 個測試在本機 12.59 秒全過（scratch 副本，含 `git init`）。
5. Orca 1.4.218 的 `terminal create --command` 是打進 login shell 的文字；`terminal list`／`show` 沒有 pid；`worker-start` 的 `--model`／`--effort` 不能和 `--terminal` 並用；`worker-release` 不關 pre-existing terminal；`send` 與 `ask` 有 `--dispatch-capability`。
6. Orca 已註冊 git repo `loop-engineering`，並有 `preflight-engineer`、`preflight-reviewer` 兩個 linked worktree，共用同一個 `.git`。
7. Claude Code 2.1.288 有 `--session-id`、`--settings`、`--setting-sources`（user、project、local）、`--permission-mode`、`--effort`、`--bare`、`--safe-mode`；Codex 0.157.0 有 `-m`、`-c`、`-s`、`-a`、`-p`、`--no-daemon`，沒有 session-id 旗標；`--allow-unix-socket` 只在 `codex sandbox`。
8. 使用者 Claude 設定有 13 個 Orca hook、11 個 caveman hook、1 個 Herdr hook，以及 ponytail、ralph-wiggum、superpowers 等 plugin；Orca 的全域預設是跳過權限（`agentDefaultArgs`）。
9. Claude transcript 的 `assistant` 頂層有 `effort`、`perTurnEffort`、`cwd`、`gitBranch`、`version`；被拒的工具呼叫帶 `toolDenialKind`。Codex `turn_context` 有 `model`、`effort`、`sandbox_policy`、`approval_policy`；sandbox 拒絕沒有結構化標記。
10. macOS 的 `ps -Eww` 看得到 Orca PTY 程序的 `ORCA_TERMINAL_HANDLE`。

### 假設（未驗證）

1. interactive 模式下 `claude --session-id <uuid>` 同樣以 `<uuid>.jsonl` 為檔名（只在 `-p` 驗證過 18/18）。
2. 自訂 terminal 裡的 Claude 仍會執行 Orca 的 hook（login shell 帶 `ORCA_AGENT_HOOK_*`），Orca 因此能把 `worker-start --terminal` 的 Dispatch 對到它。
3. 自訂 terminal 裡的 codex 使用 `~/.codex`，rollout 寫在 `~/.codex/sessions`（Orca 沒有啟用 managed account）。
4. Codex 的 `read-only` 或 `workspace-write` sandbox 會擋下對 linked worktree 共用 `.git`（探測工作區以外）的寫入。
5. `--settings` 的 `enabledPlugins` 可以按鍵覆寫 user 設定中的同名鍵。

### 未知

1. 「只保留 Orca hook、gateway、superpowers；排除 ponytail、ralph-wiggum、caveman、Herdr」的 Claude 啟動參數組合，以及 receipt 能從哪裡讀到實際載入的 gateway、plugin 與 hook。
2. Orca 經 `worker-start --terminal` 怎麼把任務送進已在執行的 Claude／Codex TUI，worker 是否把它當成任務（09-25 曾被當成注入）。
3. preamble 裡 `orca` 執行檔的實際寫法，以及 Claude allow 規則要怎麼寫，才能只放行 `send`、`check`、`ask`。
4. interactive codex 在 sandbox 內怎麼放行 Orca 的 Unix socket；放行後能否只允許必要的子命令（integration-gaps 認為不能）。
5. Codex interactive 是否在 shared app-server daemon 裡執行 turn，以及 process-info 要看哪個程序。
6. Orca 能否在不改協調者 terminal 綁定的情況下建立或使用 preflight 專用的 Run；哪個讀取方式能看到 `worker_done`（`worker-show`、`task-list`、`check --peek`），而不消耗協調者的 mailbox。
7. `terminal close` 是否結束 terminal 內所有程序（含 agent）；關閉之後 process-info 多久看得到程序消失。
8. Codex sandbox 拒絕在 rollout 中的實際樣子，能否區分「被 sandbox 擋下沒有執行」與「執行了但失敗」。
9. `--setting-sources` 去掉 `user` 之後，Claude 的登入方式（OAuth／keychain）與 gateway 是否照常。

## live probe 清單

這些步驟會改變 Orca 狀態（建立 terminal、Run、Task、Dispatch），依待決 8 需要 Project Lead 授權。每一步都在 `preflight-engineer`／`preflight-reviewer` 進行，不改 Orca 或 Claude、Codex 的全域設定，結束時關閉自己建立的 terminal 並以 process-info 確認。

| # | 步驟 | 回答的未知 | 判讀方式 |
| --- | --- | --- | --- |
| P1 | 在不綁定協調者 terminal 的前提下取得 Run：比較在非 Orca 環境（unset `ORCA_TERMINAL_HANDLE` 等）執行 `run-create`，與 `worker-start --run <id>` 的行為；之後以 `run-current` 確認協調者的綁定沒變 | 未知 6；風險 2 | `run-current` 前後相同；`worker-start --run` 可用 |
| P2 | `terminal create --worktree id:<preflight-engineer 的完整 ID> --title <marker> --command "<環境標記> claude --model claude-opus-5-5 --effort <e> --session-id <uuid> --settings <檔> --setting-sources <組合> --permission-mode dontAsk"`，記下回傳的 handle | 假設 1、2；未知 1、9 | `~/.claude/projects/<dir>/<uuid>.jsonl` 出現；`terminal list` 的 `agentIdentity` 為 `claude`；`ps` 以 uuid 與環境標記找得到程序 |
| P3 | `worker-start --task/--spec <含 marker 的探測任務> --terminal <handle> --worktree <完整 ID> --run <id> --json`；之後 `dispatch-show --task <id> --preamble` | 未知 2、3 | worker 開始執行探測任務，而不是把它當注入；preamble 中 `orca` 執行檔與 `--dispatch-capability` 的寫法 |
| P4 | 探測任務逐一嘗試：寫出可寫範圍、`git push`、`gh` 寫入、一個會改 Orca 狀態的子命令（例如 `orchestration task-create`）、`loopctl decide`；最後 `check`，再 `send --type worker_done` | AC-D27 的判讀；`worker_done` 能否送出 | transcript 中每項都有 `tool_use` 與帶 `toolDenialKind` 的 `tool_result`；資源未變；`worker-show` 或 `task-list` 看得到完成 |
| P5 | 從 transcript 讀 `hook_success`、`skill_listing`、`instructions.files`、`environment` 類 attachment；比對 P2 的設定組合 | 未知 1 | 看得到 Orca hook，看不到 caveman／Herdr hook 與 ponytail、ralph-wiggum 的 skill；確認 gateway 的證據在哪裡 |
| P6 | `terminal close --terminal <handle>`，接著重複 `ps` 檢查 uuid、環境標記與 `ORCA_TERMINAL_HANDLE` | 未知 7 | 程序消失的時間與方式；`worker-show`／`worker-list` 對這個 Dispatch 的回應（預期 `stop_unknown` 或 unsupervised） |
| P7 | Reviewer：在 `preflight-reviewer` 以 `codex -m gpt-6-astra -c model_reasoning_effort="xhigh" -s read-only -a never [--no-daemon]` 建 terminal，`worker-start --terminal` 派同樣的探測任務，另加「修改 `preflight-engineer` 的檔案並移動 `yschiang/preflight-engineer`」 | 假設 3、4；未知 4、5、8 | rollout 位置與 `turn_context`；sandbox 拒絕在 rollout 中的樣子；`git -C <engineer> rev-parse yschiang/preflight-engineer` 前後相同；`worker_done` 是否因 socket 被擋而送不出；codex 程序是否在 daemon 裡 |
| P8 | 中斷情境：P2 或 P3 之後中斷 preflight 程序，再以持久紀錄的 marker、uuid、handle 找出殘留並關閉 | AC-D31 的可行性 | 由紀錄能找到殘留的 terminal 與程序，並以 process-info 確認停止 |
| P9 | 版本：探測前後各讀一次 `orca --version`、`orca status --json` 的 `runtime.appVersion`、`claude --version`、`codex --version`，並和 native 紀錄的 `version`、`session_meta.cli_version` 比對 | receipt 的版本欄位來源 | 四個值是否一致；不一致時哪一個是 D81 要比對的「目前值」 |

P2～P6 是 Implementer 的最小路徑（AC-D29 要求 Implementer 必須 `verified`）；P7 是 Reviewer（可以是 `unverified`，缺口寫進矩陣）；P1 是前置；P8、P9 可以併入前面的步驟。

## live probe 結果（2026-10-03，Project Lead 授權）

由協調者（Claude Opus 5.5）依上表執行。原始輸出在協調者 scratchpad，不提交；以下只記結論與可公開的欄位，不含 `dcap_` 值或 token。執行前後 Orca、Claude、Codex 的全域設定都沒有改。

| # | 結果 |
| --- | --- |
| 前置 | Project Lead 授權後，協調者以 `orca repo add` 把 loop-engineering 註冊成 git repo（id `51c06003…`），並以 `orca worktree create --setup skip --no-parent --base-branch main` 建立 `preflight-engineer`、`preflight-reviewer`（§5.5）。這兩項保留，等於完成待決 6 的一次性設定 |
| P1 | `run-create` 一定要有呼叫者自己的 Orca terminal：去掉 `ORCA_TERMINAL_HANDLE` 等變數時回 `no_active_sender_terminal`；以 `--from <另一個 terminal>` 呼叫時回 `consumer_fenced`（「This terminal is attested as … and cannot act as …」）。所以 preflight 不能替別的 terminal 建 Run，只能用呼叫者 terminal 已綁定的 Run（`run-current`），或在呼叫者 terminal 上建立。本次用協調者 terminal 既有的 scratch Run `run_b6098d2f6bed`，`worker-start --run` 不改綁定（前後 `run-current` 相同） |
| P2 | `terminal create --worktree id:<完整 ID> --title <marker> --command "PREFLIGHT_MARKER=<marker> claude --model claude-opus-5-5 --effort high --session-id <uuid> --setting-sources project,local --settings <檔> --permission-mode dontAsk"` 正常啟動（Opus 5.5、high、Claude Max 登入照常）。設定檔只含 user 設定的 `env`、13 個 Orca hook、`enabledPlugins` 的 superpowers、`permissions`。Claude 警告 `Write(path)` 規則不會被檔案權限檢查採用，要用 `Edit(path)`。transcript 在 `~/.claude/projects/<cwd 轉成的目錄>/<uuid>.jsonl`（假設 1 成立）。啟動畫面顯示 Claude Code 自動更新過（D81 的重跑依據） |
| P3 | `worker-start --spec <含 marker 的任務> --terminal <handle> --worktree id:<完整 ID> --run <id>`：`state: ready`、`stage: input_accepted`、`launch` 的 requested／effective 都是 null、`mode: terminal`。任務以 `<pasted_content>` 送達，外層一句「Please carry out this task from my Orca coordinator…」；Opus 5.5 把它當成任務執行，沒有當成注入（未知 2）。preamble 的 `worker_done` 寫法是 `orca orchestration send --from <worker handle> --dispatch-capability <dcap> --type worker_done …`（相對路徑的 `orca`，未知 3） |
| P4（Claude） | 5 個負例都被拒：寫出可寫範圍（Write）、`git push --dry-run`、`gh issue list`、`orca orchestration task-create`、`loopctl decide`。每一項的 `tool_result` 都是 `is_error: true`，所在紀錄帶 `toolDenialKind: permission-rule`。資源未變：範圍外的檔案不存在、遠端沒有 `preflight-probe-*` ref、Run 的 Task 只多了探測任務本身。可寫範圍內的寫入與 `git status` 照常。`Bash(orca orchestration send *)` 放行 `worker_done`，`worker-show` 顯示 dispatch `completed`、`stage.activity: done`、liveness `live` |
| P5 | assistant 紀錄的 `model: claude-opus-5-5`、`effort: high`、`cwd`、`gitBranch: yschiang/preflight-engineer`、`version: 2.1.288`；user 紀錄的 `permissionMode: dontAsk`。transcript 中 `ponytail`、`ralph`、`caveman`、`herdr` 都出現 0 次，`superpowers` 出現在 `skill_listing`，`hook_success` 14 筆（13 筆 Orca hook，1 筆是 superpowers plugin 自己的 SessionStart hook，命令是 `"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start`）。gateway 在 native 紀錄中沒有痕跡（`ANTHROPIC_BASE_URL`、`8787` 都是 0 次），只能由啟動設定證明（未知 1 的一部分） |
| P6 | `terminal close` 回 `ptyKilled: true`；以 argv 中的 session uuid（`pgrep -f`）與 `ps -E` 的 `PREFLIGHT_MARKER` 檢查，1 秒內程序消失。之後 `worker-show` 的 observation 為 `exited`，liveness 為 `unverifiable`（`missing_status`）（未知 7） |
| P7（Codex） | 啟動被兩個互動提示擋住：「Update available」與「Hooks need review：1 hook is new or changed」。Orca 不讓 `terminal send` 對 agent 的提示輸入（`agent_prompt_blocked`），所以只能在啟動參數避開：`-c check_for_update_on_startup=false` 有效；hook 信任改用 `-c features.hooks=false`（不寫入信任紀錄，但 Orca 拿不到 Codex 的 hook）。最後的命令：`codex -m gpt-6-astra -c model_reasoning_effort="xhigh" -c check_for_update_on_startup=false -c features.hooks=false -s read-only -a never --no-daemon`。`worker-start --terminal` 的 `turnStart: observed`。rollout 在 `~/.codex/sessions/2026/10/03/`，以 marker 搜尋恰好一份（假設 3 成立）；`turn_context` 有 `model: gpt-6-astra`、`effort: xhigh`、`sandbox_policy: read-only`、`approval_policy: never`、`cwd`；`session_meta.cli_version: 0.157.0`。sandbox 擋下：寫出範圍、寫入 `preflight-engineer` 的檔案、`git update-ref` 移動 `yschiang/preflight-engineer`（都是 `Operation not permitted`，ref 前後都是 `458ab77`），以及所有 `orca` 命令（連不上 Orca，EPERM），所以 `worker_done` 送不出，dispatch 在關閉後為 `failed`（`process_exited`）。**沒有擋下**：`git push --dry-run` 以 exit 0 連到 GitHub。`gh` 以「error connecting to api.github.com」失敗。`loopctl` 不在 PATH（exit 127），所以這一項沒有測到拒絕。沒有 app-server daemon 參與（`--no-daemon`），關閉 terminal 後 codex 與它的子程序 1 秒內消失，liveness `exited`（`source: execution_host`）（未知 4、5、8） |
| P8 | 沒有另外模擬中斷；P7 中兩次以 handle 與 marker 找到前一個 Codex terminal、關閉並以 `ps -E` 確認消失，同一套作法可用於殘留清理 |
| P9 | `orca --version` 與 `status --json` 的 `appVersion` 都是 1.4.218；`claude --version` 2.1.288 等於 transcript 的 `version`；`codex --version` 0.157.0 等於 `session_meta.cli_version` |

**對設計的影響**

1. Implementer 的權限設定可以由自訂 terminal 帶入，五個負例都能以 `toolDenialKind` 判定，AC-D29 的路徑在真實環境走得通。
2. Reviewer 照目前的 Codex 參數會是 `unverified`：`git push` 沒有被 sandbox 擋下，`worker_done` 也送不出。依 proposal 的驗收條件，這可以接受，但要寫進能力矩陣；之後要在 Feature 4 前解決。
3. Codex 必須以啟動參數避開所有互動提示（更新、hook 信任）；Orca 不能代答。
4. `loopctl decide` 的負例要在 PATH 上有真的 `loopctl` 才測得到；preflight 要把自己的執行檔放進探測 worker 的 PATH。
5. preflight 必須在呼叫者自己的 Orca terminal 裡執行，使用它綁定的 Run。
6. gateway 只能以啟動設定為證，native 紀錄看不到。
