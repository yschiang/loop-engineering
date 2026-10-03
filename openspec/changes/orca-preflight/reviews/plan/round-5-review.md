已核對 `562d095` 與 `ad41ea7..562d095`。本輪新增 **2 個 blocking**。全程唯讀，未執行測試或 orca／claude／codex。

以下位置均指 `openspec/changes/orca-preflight/` 的 [design.md](/Users/johnson.chiang/workspace/loop-engineering-orca-preflight/.delivery/orca-preflight/plan-review-1/repo/openspec/changes/orca-preflight/design.md) 與 [tasks.md](/Users/johnson.chiang/workspace/loop-engineering-orca-preflight/.delivery/orca-preflight/plan-review-1/repo/openspec/changes/orca-preflight/tasks.md)。`resolved` 表示原設計缺口已補；新增 Red 的問題另列 finding。

| ID | 狀態 | 證據 |
|---|---|---|
| G-1 | resolved | design:239 區分 Orca／plugin hook，並以 plugin 名稱前綴檢查 skill；tasks:316 納入 13＋1 筆 hook。research:475 已更正。 |
| G-2 | resolved | design:367、391 定義版本正規化與真實格式的 fake；tasks:267 驗證 receipt 的版本值。 |
| G-3 | resolved | design:250–253 定義 JS 字面值、output 元素搜尋及拒絕標記；tasks:357 補三種 input。該測試的 Red 有 P-29。 |
| G-4 | resolved | design:181、tasks:266 明列絕對路徑權限規則及精確字串斷言。 |
| G-5 | resolved | design:183、199 定義 PATH quoting、loopctl 目錄來源及 `loopctl_not_found`；tasks:266 驗證 `$PATH` 保留展開。 |
| G-6 | resolved | design:193 定義 TOML 值；tasks:355 精確斷言兩個小寫 `false`。 |
| G-7 | partly | design:63、118、384 與 tasks:154、214、406 已補缺 profile 的介面及行為；但 tasks:374 仍寫 `current_versions(role)`，應同步為 `current_versions(runtime)`。這是非阻擋的殘留介面文字。 |
| G-8 | resolved | tasks:57、122 將既有 pytester `child` fixture 納入擁有路徑，要求一起複製 `tests/fakes/`。 |
| G-9 | resolved | tasks:56、110 明列 dev group 的 `types-PyYAML` 與 lock 更新。 |
| G-10 | resolved | design:59、384 定義 missing／corrupt object 的轉換及 status 回應；tasks:207、406 補測試。 |
| G-11 | resolved | design:372、tasks:402 統一為含 `blockers` 的 human next。 |
| G-12 | resolved | tasks:223 改成同程序另一個 fd 持鎖；既有 `cli_proc` 的 prelude 與 `runpy` 在同一程序執行，不再等待主測試解屏障。 |
| G-13 | resolved | design:323–325 固定先睡再查；tasks:272 驗證十輪及第三輪提早停止。 |
| G-14 | resolved | design:60、313 將非 timeout 錯誤歸為 `Problem`，立即停止等待；tasks:274 的 Red 有 P-30。 |
| G-15 | resolved | design:161 補 Implementer profile／工作區解析與三種錯誤；tasks:217 納入 Reviewer 案例。 |
| G-16 | resolved | design:59 禁止略過最新壞索引後退回舊 receipt；tasks:207(c) 明確驗證。 |
| G-17 | resolved | design:119、194 明定非空排除清單為 invalid；tasks:154 驗證拒絕，362 改驗空清單與 observed。 |
| G-18 | resolved | design:219 改用 `started` 檔案的 OS mtime；tasks:269 加入舊 transcript。 |
| G-19 | resolved | design:221 使用 UTC／本機日期聯集；tasks:358 加入跨日案例。 |
| G-20 | resolved | design:219–220 限定搜尋層級與 user marker 紀錄；tasks:269 加入 subagent、ai-title 案例。 |
| G-21 | resolved | design:138、161、185、222 定義 out／settings／使用者設定／native IO 失敗；tasks:217、221 補使用者設定及 out 測試。 |
| G-22 | resolved | 新增 Orca JSON 樣本；design:404 要求 fake 依樣本製作，232 補 branch 前綴處理。成功 idle 缺樣本已在 samples README:26 與 tasks:524 明列。 |
| G-23 | resolved | design:213 明定保留探測檔及記錄路徑；tasks:265 驗證檔案仍存在及 evidence。 |

本輪新增或改寫的 Red，逐項靜態推演如下。「可成立」不代表已執行測試；同一列新增的其他參數案例，也不因此自動取得獨立 Red 證據。

| 測試 | Red 判斷 |
|---|---|
| `test_missing_profiles_and_roles_are_not_errors` | 可成立：缺 `profiles` 被當成 mapping 錯誤時，`errors` 比較失敗。 |
| `test_tampered_receipt_is_reported_not_trusted` | 指定的 Red 仍是原有 (a)；新增 (b)、(c) 補 Green 覆蓋。 |
| `test_invalid_profile_is_unverified_without_calling_tools` | 可成立：空 reasons 與兩種預期原因不同。 |
| `test_missing_selected_tools_block_the_profile` | 可成立：只檢查政策時，不會產生指定的環境原因。 |
| `test_out_writes_the_same_receipt` | 可成立：未寫 out 時存在性斷言失敗；新增 IO 案例補 Green 覆蓋。 |
| `test_concurrent_preflight_for_one_role_is_refused` | 可成立：持鎖 fd 保持開啟；不取鎖的 stub 不會回預期拒絕。 |
| `test_probe_passes_launch_readback_and_stop_items` | 可成立：2.1 尚無探測 items；新增檔案保留斷言補 Green 覆蓋。 |
| `test_launch_command_and_settings_are_fixed` | 可成立：照抄全部 hook 會使數量斷言失敗。 |
| `test_versions_are_normalised_from_real_outputs` | 可成立：比較時正規化、receipt 仍保存原字串，可保持前列 Green，並讓本列版本欄位斷言失敗。 |
| `test_readback_mismatch_fails_the_item` | 原失配列可成立；新增三個正向搜尋案例不會因「一律成立」而 Red，屬本列新增的 Green 覆蓋。 |
| `test_stop_must_be_confirmed_by_process_info` | marker 仍存在的負例可使 item 斷言 Red；第三輪消失案例補提早停止的 Green 覆蓋。 |
| `test_wait_failure_stops_waiting_at_once` | 所寫的次數 Red 不保證成立，見 P-30。 |
| `test_excluded_settings_fail_the_item` | 指定突變可成立：忽略 skill listing，會錯放行 ponytail 案例。 |
| `test_codex_launch_avoids_interactive_prompts` | 可成立：尚不支援 Codex 時沒有啟動命令，命令斷言失敗。 |
| `test_codex_calls_are_parsed_from_the_js_input` | 會先遇到解析例外，見 P-29。 |
| `test_codex_rollout_is_found_across_date_boundaries` | 可成立：建立題述的本機時區與跨日情境後，只搜 UTC 日期會漏掉 rollout。 |
| `test_codex_settings_are_recorded` | 可成立：尚未保存 observed，欄位存在性斷言失敗。 |
| `test_unapproved_policy_comes_before_the_receipt` | 指定突變可成立：提前查 receipt／版本會留下禁止的版本呼叫。 |
| `test_status_with_policies_that_lack_profiles` | 可成立：沿既有空 Profile／runtime None 契約處理，但尚未判 invalid 時，可回到 `not_run`，使 reasons 比較失敗。 |

**P-29 — blocking｜tasks.md:357，`test_codex_calls_are_parsed_from_the_js_input`**

問題：所列 Red「先以 `json.loads(input)` 讀 cmd」會先拋解析例外，未定義如何抵達所寫的步驟、exit 與輸出比較。

證據：native 樣本第 13、27 行的 input 都以 `text(await …)` 開始。以標準庫唯讀驗證，兩者的 `json.loads(input)` 都得到 `JSONDecodeError: Expecting value: line 1 column 1`。即使 CLI 測試 helper 收住例外，這仍是 tasks:21 排除的「停在呼叫上的例外」。

建議：讓 Red 從「已能讀回 context，但 calls 尚未辨識、正常回空結果」開始；或明定錯誤 JSON 解析會轉成未辨識結果。先確認呼叫正常返回，再斷言前兩種命令應被辨識。

**P-30 — blocking｜tasks.md:244–246、274，`test_wait_failure_stops_waiting_at_once`；design.md:308–313**

問題：新增測試沒有安排未完成的 native turn，因此「把錯誤當 timeout」不保證使等待次數超過一次。

證據：`claude_probe` 在 terminal create 時就寫出完整 transcript。依 DD-7，即使把 wait 的錯誤當 timeout，接著讀到已完成的 native turn，仍會結束等待；呼叫次數同樣是 1。此時可能失敗的是 `wait_failed` 原因斷言，而非計畫指定的次數斷言。

建議：明定 transcript 始終未完成、wait 錯誤使用 `repeat: true`，並設定受控 timeout，讓錯誤實作確實等待超過一次；或把本列 Red 改為斷言缺少 `wait_failed:<reason>`。

VERDICT: changes_required