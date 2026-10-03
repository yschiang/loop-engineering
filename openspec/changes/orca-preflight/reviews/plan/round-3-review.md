已核對 `cf34c1e` 與本輪 diff。指定的原 finding 均已解決；本輪新增 **2 個 blocking**。全程唯讀，未執行測試或 orca／claude／codex，工作目錄未變更。

以下位置均指 `openspec/changes/orca-preflight/`。

**原 finding 核對**

| ID | 狀態 | 證據 |
|---|---|---|
| P-9 | resolved | design.md:53–63 列出跨 task 介面；tasks.md:111–116 明定型別、例外可匯入及 stub 回傳。 |
| P-11 | resolved | tasks.md:67、183 固定環境 scenario 在 terminal create 失敗，配合 design.md:145 提早結束，不需要後續修改 static 測試。 |
| P-15 | resolved | tasks.md:266 已具體覆蓋缺 native turn、零份、多份及檔名不符，並驗停止確認；先前缺少的 D18 路徑已補。 |
| P-16 | resolved | design.md:57–63 補結果型別、`Records.skipped`、錯誤值、例外及負例判定介面。 |
| P-19 | resolved | design.md:390、tasks.md:139–141 使用受控 sentinel PATH；解析斷言先於執行，不再依賴本機工具或安裝狀態。 |
| P-20 | resolved | tasks.md:203 將 records 放到 receipt 測試前；394 改從只判 verdict 開始；216、311 明標算法突變。 |
| P-21 | resolved | design.md:252 接受同呼叫的 `runtime_access_denied`；tasks.md:353 加入樣本格式，仍要求非零 exit。 |
| P-22 | resolved | design.md:144–149 明定 terminal 建立後仍判讀、停止及讀後版本；tasks.md:266 明列失敗 item 與原因。 |
| P-23 | resolved | design.md:237–242 改按 `turn_id` 配對；tasks.md:352 覆蓋前置 context、零／多筆及其他 turn；樣本保留了 marker。 |
| P-24 | resolved | design.md:278–281 補 marker、hook、skill、native version 與 turn 證據；tasks.md:314 逐類驗證摘錄內容。 |
| P-25 | resolved | design.md:371 與 tasks.md:398–399 統一五個欄位、null 及四種 `policy:<狀態>` 原因。 |
| P-26 | resolved | tasks.md:46 恢復受測模組 scope，僅共用骨架採跨 scope 例外。 |

**本輪改寫的 Red 核對**

「可成立」指靜態追蹤可抵達所寫的行為斷言，並非已執行測試。

| 測試 | 判斷 |
|---|---|
| `test_unexpected_call_fails_the_test_at_teardown` | 可成立：缺 teardown 檢查時，外層 error 數量斷言失敗。 |
| `test_real_tools_are_never_reached` | 可成立：autouse 尚未接上時，解析到 sentinel，內層及外層結果斷言失敗。 |
| `test_without_removes_the_tool_from_path` | 可成立：只刪 fake 會解析到 sentinel。 |
| `test_capture_substitution_and_effects` | 可成立：缺代換使 stdout 比較失敗；Green 另覆蓋 repeat 與版本預設回應。 |
| `test_records_are_write_once_and_ordered` | 可成立：現在先於 receipt 實作，確實可從不寫檔的 stub 開始。 |
| `test_reviewer_clone_with_the_same_remote_is_found` | 突變可成立：路徑篩選會漏掉 Reviewer clone。 |
| `test_readback_mismatch_fails_the_item` | 可產生行為 Red；Green 的欄位契約仍有 P-27。 |
| `test_other_tasks_in_the_run_do_not_affect_the_orca_check` | 突變可成立：計數算法會受其他 Task 影響。 |
| `test_receipt_keeps_fixed_excerpts_and_the_native_digest` | 可成立：保存整筆紀錄會違反欄位集合斷言。 |
| `test_codex_readback_comes_from_turn_context` | 可成立：尚未讀回時，正向列的 item 成立斷言失敗。 |
| `test_codex_denial_must_be_tied_to_the_call` | 可成立：全檔搜尋會錯用另一呼叫的拒絕標記。 |
| `test_receipt_stops_applying_when_anything_changes` | 可成立：只判 verdict 時，換版仍回 dispatch。 |
| `test_status_reports_each_profile_with_reasons` | 可成立：尚無 profiles 時，完整形狀比較失敗。 |
| `test_status_without_an_approved_policy_calls_no_tools` | 突變可成立：無條件讀版本會留下禁止的呼叫。 |

**P-27 — blocking｜design.md:63、148、275；tasks.md:214、266**

問題：新增的 item 契約混用 `pass` 與 `passed`，公開輸出與測試不能依同一形狀實作。

證據：

- DD-1 定義 `Item(passed, reason, required, actual, evidence)`；DD-4 也要求 `passed: false`。
- DD-6 的 receipt 仍定義 `{pass, reason, evidence}`。
- 同一套 CLI 測試中，`test_same_model_makes_the_reviewer_unverified` 讀 `.pass`，改寫後的 `test_readback_mismatch_fails_the_item` 則斷言 `.passed`。

即使內部 dataclass 使用 `passed`、序列化改成 `pass`，新版 readback 測試仍與公開輸出不符；目前沒有定義這層映射。

建議：統一 receipt／CLI 的欄位名稱及所有測試。若內部保留 `passed`，明定序列化映射，並確保 `required`、`actual` 也保存到 receipt。

**P-28 — blocking｜tasks.md:266、270；共同規則第 19、24–26 行**

問題：新增的逾時清理案例，讓後面的停止測試無法再從所寫的 Red 開始。

證據：改寫後的 `test_readback_mismatch_fails_the_item` 已要求四種案例以 repeat timeout 等到 60 秒，最後仍有 `stop.confirmed`。依 DD-7，這已要求逾時後關閉 terminal 並確認停止。

後面的 `test_probe_timeout_still_stops_the_worker` 卻仍寫「先在逾時時直接返回」，預期 `terminal close` 呼叫斷言失敗。這樣修改會破壞前一列已完成的 Green；若保留前一列實作，停止斷言會提前通過。該列沒有標示突變。

建議：將這一列改成明確的「逾時略過清理」突變；或重新安排順序與 Red，讓新增斷言驗證尚未交付的行為，例如 `probe_timeout` 原因，而非已被前列證明的關閉動作。

VERDICT: changes_required