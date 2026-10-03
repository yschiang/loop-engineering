第 6 輪：確認第 5 輪的 P-29、P-30 與 G-7 的殘留。新版本是 `cd0d408`（同一個 clone 已更新並 checkout），`git diff 562d095 cd0d408 -- openspec/changes/orca-preflight/tasks.md` 是全部修改：

- P-29：`test_codex_calls_are_parsed_from_the_js_input` 的 Red 改成從「已讀回 turn_context、calls 仍是空清單、正常返回」開始，失敗在「對應到步驟」的斷言。
- P-30：`test_wait_failure_stops_waiting_at_once` 的 transcript 始終沒有完成的 turn，wait 錯誤以 `repeat: true` 回應，`timeout_s` 為 60；把錯誤當 timeout 的實作會呼叫 wait 多次。
- G-7：tasks.md 的 `current_versions(role)` 改成 `current_versions(runtime)`。

請只核對這三處是否已解決，以及修改有沒有帶進新的 blocking 問題。輸出格式同前；最後一行寫 `VERDICT: clean` 或 `VERDICT: changes_required`。
