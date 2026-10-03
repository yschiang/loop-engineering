# Live probe 的 native 紀錄樣本

2026-10-03 live probe（[research.md](../research.md)「live probe 結果」）的 Claude transcript 與 Codex rollout，作為 fake transcript／rollout 的欄位範本（design D10）。

- 處理：去掉 `file-history-*` 紀錄；`deferred_tools_delta`、`mcp_instructions_delta`、`agent_listing_delta`、`instructions`、`prompt_snapshot` 的內容換成 `<omitted from sample>`；`dcap_` 值、`organizationUuid`、`creator_account_id`、`creator_user_id` 換成 `<redacted>`；超過 2,000 字元的字串截斷並標 `…<truncated>`。其餘欄位與紀錄順序照原樣。
- `claude-probe-transcript.jsonl`：Implementer 探測（marker `PFM-13f596fbc076`，session `84626209-…`）。
- `codex-probe-rollout.jsonl`：Reviewer 探測（marker `PFM-a5fe22ea014a`）。
- 不是測試的預期值來源；測試的斷言以 spec 與 design 為準。
