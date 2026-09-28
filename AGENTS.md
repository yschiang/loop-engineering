# AGENTS.md — 所有 agent 的共同規則

適用於在本 repo 寫碼、審查或跑迴圈的每個 agent，以及它們派出的 subagent。

## Commit 訊息

`scripts/hooks/commit-msg` 依本節檢查。每個 clone 執行一次 `git config core.hooksPath scripts/hooks` 啟用（各 worktree 共用）；CI 的 `unit-linux` 對 PR 的 commit 再檢查一次。不用 `--no-verify` 繞過。

本節約束的是含有「新增 `scripts/hooks/commit-msg`」那個 commit 的 commit。更早的 commit 維持原訊息、不改寫：它們的 SHA 綁著 TDD 證據（Red／Green、receipt）。舊分支合入該 commit 後，之後的新 commit 才受檢。

### 粒度

- 一個 commit 只做一件邏輯變更，通常是一個 task；每個 commit 自身 build 與測試全綠，`git bisect` 才可用。
- 先整理結構再改行為時，結構調整另成 `refactor` commit，放在行為變更之前。
- 隨程式一起變的文件（README、validation 紀錄）與程式放同一個 commit。

### 格式

```
<type>(<scope>)!: <description>

Why: <為什麼要改>

Behavior: <套用後什麼成立>

Tradeoff: <選填>

BREAKING-CHANGE: <不相容之處與遷移方式>
Refs: #<ticket>
```

- 全部用英文。
- Subject 用祈使句（`add`、`keep`、`reject`），不超過 72 字元，結尾不加句號。
- Body 每行不超過 72 字元（含 URL 的行除外）；標籤段落依 `Why` → `Behavior` → `Tradeoff` 順序，彼此空一行。

### Body

- `feat`、`fix`、`refactor` 必須有 `Why:` 與 `Behavior:`；其他 type 在 subject 已說清楚時可省略 body。
- `Why:` 是 diff 保存不了的部分，寫動機。`fix` 寫根因的機制，不寫症狀：寫不出根因，代表還沒修到根因。
- `Behavior:` 寫套用後成立的預期行為或不變式。`refactor` 寫 `Behavior: unchanged — <維持不變的行為>`。
- `Tradeoff:` 寫否決的做法與理由，或引用 D 編號；只寫已成立的事實，不寫「之後再補」。
- 不寫改了哪些檔案、逐步怎麼改（diff 已有），也不寫 ticket 的驗收清單（屬於 PR 與 validation 文件）。需要一長串條列時，通常該拆 commit。

### Type

| type | 用於 |
| --- | --- |
| `feat` | 新增外部可觀察的能力（loopctl 指令、輸出、狀態轉換） |
| `fix` | 修正與 spec 或 design 不符的行為 |
| `refactor` | 不改行為的結構調整，含 prefactor |
| `test` | 只動測試 |
| `docs` | 產品與設計文件 |
| `build` | `pyproject.toml`、`uv.lock`、`workflow.yaml`、`profiles/`、`scripts/dist-smoke.sh` |
| `ci` | `.github/workflows` |
| `chore` | 開發流程與工具，不影響 loopctl 本身 |

`revert` 用 git 產生的 `Revert "…"`，不另用 type。

### Scope

- 寫變更所在的 component，不寫 ticket、task 或 decision 編號：`T6.1`、`D53` 不當 scope，ticket 由 `Refs` 表達。
- 程式：`src/loopctl/` 的模組名（檔名去掉 `.py`，或子套件名），目前有 `store`、`state`、`decisions`、`writes`、`assignments`、`observe`、`budget`、`evidence`、`gates`、`preflight`、`cli`、`next`、`clock`、`tools`；新增模組即新增 scope。測試用受測模組的 scope，例如 `test(gates): …`。
- 文件與流程：

  | scope | 範圍 |
  | --- | --- |
  | `design` | `docs/design-candidate`、`docs/decisions.md`、`docs/project-intent.md`、`docs/harness`、`docs/implementation`、`docs/research`、`docs/references`、`docs/experiments`、`docs/reviews`、`CONTEXT.md` |
  | `validation` | `docs/validation` |
  | `openspec` | `openspec/` |
  | `readme` | `README.md`、`docs/README.md` |
  | `workflow` | `AGENTS.md`、`docs/workflow`、`docs/handoffs`、`scripts/hooks`、`.agents/`、`.claude/`（type 用 `chore`） |

- `build`、`ci` 與無法拆開的跨 scope 變更不填 scope。
- scope 粒度是專案層級的選擇，由 project lead 在本節調整。

### Trailer

- 放在最後一段，前面空一行，一行一個；git 才解析得到（`git log --format='%(trailers:key=Refs)'`）。
- `Refs: #N`：有對應 ticket 就必填，一行一張。
- `BREAKING-CHANGE:` 與 subject 的 `!` 同時出現。不相容包含 loopctl 的指令與 JSON 輸出、store／state 的持久化格式、decision 紀錄格式、`workflow.yaml` schema。
- 禁止：`Co-Authored-By` 或任何 AI 署名；closing keyword（`Closes`、`Fixes`、`Resolves #N`），關票屬於 PR。

### 範例

```
fix(state): generate claim tokens that never parse as an option

Why: secrets.token_urlsafe can start with '-' (about 1 in 64); argparse
read such a token as an option, so every writing command failed with a
usage error.

Behavior: state.new_token() returns secrets.token_hex(32), so
"--token <value>" always parses as a value; tokens keep 256 bits and are
still stored only as digests.
```
