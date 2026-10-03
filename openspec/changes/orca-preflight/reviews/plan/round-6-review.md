已核對 `cd0d408` 與本輪 diff。三項均已解決，未發現新增 blocking。全程唯讀；以下是計畫與 Red 的靜態核對，未執行測試。

| ID | 狀態 | 位置與證據 |
|---|---|---|
| P-29 | resolved | tasks.md:357：明定前列 Green 已讀回 `turn_context`，但 `calls` 仍為空且正常返回。前兩種命令無法對應步驟，能失敗在指定斷言；不再經過 `json.loads(input)` 的例外路徑，也不破壞前列讀回測試。 |
| P-30 | resolved | tasks.md:274：只有 prompt、沒有完成的 turn；wait 錯誤可 repeat，假時間上限為 60 秒。錯把錯誤當 timeout 時，會經 `sleep(2)` 推進時間並多次等待，使「只呼叫一次」的斷言失敗；正確實作則立即停止等待並完成清理。 |
| G-7 | resolved | tasks.md:374：已改為 `current_versions(runtime)`，與 design.md:63、367 的簽名及 runtime 取自 profile 的契約一致。 |

VERDICT: clean