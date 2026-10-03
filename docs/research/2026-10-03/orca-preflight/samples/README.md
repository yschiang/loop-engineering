# Live probe 的 native 紀錄樣本

2026-10-03 live probe（[research.md](../research.md)「live probe 結果」）的 Claude transcript 與 Codex rollout，作為 fake transcript／rollout 的欄位範本（design D10）。

- 處理：去掉 `file-history-*` 紀錄；`deferred_tools_delta`、`mcp_instructions_delta`、`agent_listing_delta`、`instructions`、`prompt_snapshot` 的內容換成 `<omitted from sample>`；`dcap_` 值、`organizationUuid`、`creator_account_id`、`creator_user_id` 換成 `<redacted>`；超過 2,000 字元的字串只保留頭尾各 1,000 字元，中間換成 `…<truncated>…`（marker 在 prompt 的尾段，因此保留）。其餘欄位與紀錄順序照原樣。
- `claude-probe-transcript.jsonl`：Implementer 探測（marker `PFM-13f596fbc076`，session `84626209-…`）。
- `codex-probe-rollout.jsonl`：Reviewer 探測（marker `PFM-a5fe22ea014a`）。
- 不是測試的預期值來源；測試的斷言以 spec 與 design 為準。

## `orca/`：Orca CLI 的 JSON 輸出

2026-10-03 live probe 與之後的唯讀查詢（Orca 1.4.218）。鍵名含 token、secret、capability、password、apiKey 的值與 `dcap_` 值換成 `<redacted>`。

| 檔案 | 命令 | 備註 |
| --- | --- | --- |
| `repo-list.json` | `orca repo list --json` | git repo 有 `gitRemoteIdentity.canonicalKey` |
| `worktree-list.json` | `orca worktree list --json` | `branch` 帶 `refs/heads/` 前綴；`id` 是 `<repo-id>::<path>` |
| `status.json` | `orca status --json` | `result.runtime.appVersion`、`reachable` |
| `run-current.json` | `orca orchestration run-current --json` | |
| `terminal-create.json` | `orca terminal create … --json` | `result.terminal.handle` |
| `worker-start.json` | `orca orchestration worker-start … --terminal … --json` | `state: ready`、`taskId`、`dispatchId` |
| `worker-show-completed.json` | `worker-show`：送了 `worker_done` 的 Claude 探測 | dispatch `status: completed` |
| `worker-show-failed.json` | `worker-show`：沒送 `worker_done`、terminal 已關的 Codex 探測 | `failed`、`process_exited` |
| `task-list.json` | `orca orchestration task-list --run <run> --json` | 含 spec 文字 |
| `terminal-close.json` | `orca terminal close --terminal … --json` | `ptyKilled: true` |
| `terminal-wait-shell.json` | `orca terminal wait --for tui-idle --timeout-ms 2000`（對一般 shell） | exit 1，`error.code: timeout`。成功（idle）時的 JSON 沒有取得，實作以 `ok: true` 判定 idle |
