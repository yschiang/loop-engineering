第 3 輪（最後一輪）。計畫已依第 2 輪修改，新版本是 `cf34c1e`（同一個 clone 已更新並 checkout）。中間另有 `465bca2`：design 的決策改名為 `DD-1`～`DD-12`（D83：`D<n>` 只指 `docs/decisions.md` 的專案決策），內容不變。`git diff 40b8411 cf34c1e -- openspec/changes/orca-preflight docs/research/2026-10-03/orca-preflight/samples` 可看全部修改。

處理摘要：
- P-9、P-16：DD-1 新增「跨 task 的介面」表，列出每個模組的函式簽名、結果型別、例外與錯誤契約（`Completed`、`Records`、`Versions`、`orca.Problem`、`orca.Started`、`native.Found`、`native.Session`、`native.Call`、`native.CallResult`、`preflight.Item`）；1.1 建立它們並給出 stub 的回傳。
- P-11：2.1 的 `environment(...)` scenario 對 `terminal create` 回失敗，之後的 task 加入探測時，static 測試仍停在第 8 步，斷言不變；共用檔案表寫明之後不改這個測試檔。
- P-15、P-22：DD-4 改寫跳躍規則。terminal 建立之後的任何問題都照樣執行第 11、12、12a 步，缺證據的 item 為 `passed: false`、`actual: null`，並有固定原因（`no_native_turn`、`native_not_found`、`native_ambiguous`、`native_name_mismatch`、`task_not_started`）。3.1 的 readback 測試依此改寫。
- P-19：骨架自測改用 `pytester` 子程序，外層 PATH 只有 `minbin/` 與 test sources 的 `sentinel/`；隔離失效時解析到 sentinel，不會碰到真實工具（DD-10）。
- P-20：receipts 測試把 records 排到最前面；5.1 的 `…stops_applying…` 改成從「只看 verdict」的實際增量開始；`…reviewer_clone…` 與 `…other_tasks…` 標成突變。
- P-21：Codex 的拒絕標記加入 Orca CLI 的 `runtime_access_denied`（樣本第 30 行），仍要求同一個呼叫、exit 非 0（DD-6）；4.1 加對應列。
- P-23：Codex 以 `internal_chat_message_metadata_passthrough.turn_id` 配對含 marker 的 user 訊息與同 turn 的 `turn_context`、`task_complete`、工具呼叫（DD-6「Codex 的 turn 配對」）；4.1 加 0／2 筆、跨 turn 的列。樣本改成保留長字串的頭尾，marker 不再被截掉。
- P-24：摘錄白名單加入 `marker_context`、`hook_success` 的事件與命令、skill 名稱清單、`session_meta.cli_version`、`turn_id`；3.2 逐類斷言 evidence 含判定的值。
- P-25：`status` 的 profile 形狀固定為 `{status, verdict, receipt, versions, reasons}`；未核准時 `reasons == ["policy:<狀態>"]`，四種狀態參數化（DD-9）。
- P-26：`test` 照 AGENTS.md 用受測模組 scope，1.1 的共用骨架依跨 scope 例外不帶 scope。
- 另外：fake 的 `--version` 預設回應在有 scenario 時仍有效；scenario 項目可標 `repeat: true`（DD-10）。

請：
1. 逐條核對 P-9、P-11、P-15、P-16、P-19～P-26 是否已解決（附證據）。
2. 只看這輪的修改有沒有帶進新的 blocking 問題，新的 finding 從 P-27 起編號；逐一判斷新寫或改寫的 Red 能否失敗在所寫的斷言上。不要重提已解決的事。

這是最後一輪：只有會讓實作照計畫做不出來、Red 無法成立、AC 沒被證明、或違反規則的問題才標 blocking。輸出格式同前；最後一行寫 `VERDICT: clean` 或 `VERDICT: changes_required`。
