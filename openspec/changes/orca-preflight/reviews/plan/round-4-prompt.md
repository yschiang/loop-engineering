第 4 輪（Project Lead 在 3 輪後決定「修，再審一輪」，見 #44 的留言）。新版本是 `c724a08`（同一個 clone 已更新並 checkout）。`git diff ddd7988 c724a08 -- openspec/changes/orca-preflight` 是這輪的全部修改：

- P-27：receipt 的 item 欄位統一為 `{passed, reason, required, actual, evidence}`，與 `preflight.Item` 相同；receipt、`--out`、CLI 輸出都用這個形狀（DD-6）；tasks.md 的 `.pass`／`pass` 全部改成 `passed`。
- P-28：`test_probe_timeout_still_stops_the_worker` 的 Red 改成明標的突變（逾時時略過第 11、12 步），並註明本列另外斷言 `probe_timeout`。

請只核對 P-27、P-28 是否已解決，以及這兩處修改有沒有帶進新的 blocking 問題（例如還有沒改到的 `pass`、突變是否真的會失敗在所寫的斷言上）。不要重新審整份計畫。輸出格式同前；最後一行寫 `VERDICT: clean` 或 `VERDICT: changes_required`。
