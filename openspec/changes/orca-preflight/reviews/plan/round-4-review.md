已核對 `ddd7988 → c724a08`，僅審查指定修改。全程唯讀，未執行測試。

**P-27 — resolved｜design.md:63、148、275；tasks.md:214、263、266、307**

item 已統一為 `{passed, reason, required, actual, evidence}`，並明定 receipt、`--out`、CLI 使用相同形狀。搜尋 design／tasks 後，未發現遺漏的 item `pass`；剩餘 `user:pass@` 是 URL 遮蔽範例，無關欄位契約。

**P-28 — resolved｜tasks.md:270**

Red 已明標突變。逾時後保留 `probe_timeout`，略過第 11、12 步直接寫 receipt，會使「曾呼叫 `terminal close`」的斷言失敗；不再要求從前面已完成的 Green 自然產生 Red。還原突變後，仍須驗證停止確認及 `probe_timeout`。

這兩處修改未引入新的 blocking 問題。

VERDICT: clean