> 注意：這一輪以 `codex exec resume` 接續同一個 session，沒有帶 effort，實際是 GPT-6 Astra **high**（session 紀錄的 `turn_context.effort`），不是計畫的 xhigh。第 3 輪起明確指定 `-c model_reasoning_effort=xhigh`。

已核對 `81be2c0 → 40b8411` 的修改、新增 native 樣本及重寫後的 68 列測試。全程唯讀，未執行測試或 orca／claude／codex，工作目錄未變更。

以下位置除另註外，均指 `openspec/changes/orca-preflight/`。

**P-1～P-18 核對結果**

| ID | 狀態 | 證據與剩餘問題 |
|---|---|---|
| P-1 | resolved | design.md:297–305 明定只有確認停止才結束；tasks.md:433–434 補連續清理失敗及未核准政策案例。 |
| P-2 | resolved | design.md:221–224 加入呼叫配對及拒絕種類；tasks.md:307、351 測人工拒絕、中斷、exit 0 與其他呼叫的 EPERM。新增格式矛盾另列 P-21。 |
| P-3 | resolved | design.md:209、215 改用 `disabled_plugin_ids` 判定，分開 configured／observed；tasks.md:354 有排除項未生效的反例。 |
| P-4 | resolved | design.md:250–257 增加欄位白名單與多類憑證遮蔽；tasks.md:311 驗證非 `dcap_` 憑證。白名單造成的證據遺失另列 P-24。 |
| P-5 | resolved | design.md:137、211、387 改用 remote identity 搜尋及實體絕對 git common directory；tasks.md:213–214、353 補案例。 |
| P-6 | resolved | design.md:232 改按自己的 `probe <s>` 識別 Task；tasks.md:309 加其他 Task 增加的案例。 |
| P-7 | resolved | design.md:138、145、210、320 綁定前值、後值及 native 版本；tasks.md:265 補不一致案例。 |
| P-8 | resolved | 原四處已分別改成 item 斷言、呼叫端順序突變、完整管制路徑突變及明標政策突變，見 tasks.md:264、394、398、466。 |
| P-9 | partly | fake 能力與自測、snapshot 順序觀察已補；「所有介面先建立」仍缺可落實的契約，見下方 P-9／P-16。 |
| P-10 | resolved | design.md:348–351 覆蓋整套測試、受控 PATH 與 teardown；新版隔離自測自己的 Red 有問題，另列 P-19。 |
| P-11 | partly | 已補 5.1、7.1 擁有權並移除 `not_implemented` 斷言；早期環境 scenario 的後續維護仍無擁有者。 |
| P-12 | resolved | tasks.md:425、429–430 分開兩個中斷點，且每個測試自行建立殘留。 |
| P-13 | resolved | tasks.md:355 已保留 gh 與 loopctl 兩項缺口；新增拒絕判準與原始輸出的衝突另列 P-21。 |
| P-14 | resolved | design.md:227–235 明列各負例可用結果；tasks.md:306 不再展開不適用組合。 |
| P-15 | partly | status、跨 run、狀態不變、cleanup receipt 與驗收分類皆補齊；新增 D18 案例仍無法依流程得到要求結果，見 P-22。 |
| P-16 | partly | `Policy`、`Profile`、`Completed` 及 malformed policy 分類已補；native／Orca blocking edges 與部分回傳契約仍缺。 |
| P-17 | resolved | tasks.md:75、93 改成 xhigh／xhigh。 |
| P-18 | resolved | tasks.md:47–48、385 加入 `Refs: #44`、breaking subject 與 trailer。 |

**P-9 — blocking｜partly｜tasks.md:110–114、187**

問題：骨架仍未保證後續測試可以 import 並呼叫約定介面。

證據：1.1 要建立「D1 列出的函式」，但 design D1 只有模組圖及責任，沒有 `orca.py`、`native.py` 的函式簽名。`ReceiptCorrupt`、`Unparseable` 的可匯入契約也未列入骨架交付；2.1 卻限定只換實作、不改簽名。

建議：在 1.1 明列後續直接使用的函式、型別、例外及 stub 回傳值；共用能力自測部分可保留現案。

**P-11 — blocking｜partly｜tasks.md:58、181、206–219、240–244、330–332**

問題：早期測試的 scenario 在加入完整探測後會失效，但後續 task 仍沒有更新權限。

證據：2.1 的 static 測試統一使用 `environment(...)`；其中環境齊全、未選用工具及 run 綁定案例會繼續進入探測。3.1／4.1 加入 terminal、worker 與 native 流程後，原 scenario 沒有這些回應，會触發 unexpected 呼叫及 teardown 失敗。共用規則又禁止修改既有 generator 的預設輸出，後續 owned paths 沒有 `tests/test_preflight_static.py`。

建議：明列 3.1／4.1 對這些測試前置 scenario 的擁有權，改用完整探測 scenario，保留原行為斷言。

**P-15 — blocking｜partly｜tasks.md:264、350、481**

問題：D18 的案例名稱已補齊，但部分 THEN 仍無法由計畫中的執行路徑證明。

證據及建議：見新增 P-22；修正流程與測試交付後才能結案。其他原列覆蓋缺口已解決。

**P-16 — blocking｜partly｜tasks.md:111、169–170、234–236、334–338；design.md:296**

問題：新增錯誤分類仍未補完跨 task 的必要介面。

證據：

- `list_records(dir) -> list` 同時要求回傳紀錄及回報損壞檔名，卻未定義後者的通道與形狀。
- Orca 查詢函式只有名稱；成功回傳值與 `Unparseable` 的型別關係未定。
- native 判讀與三段式負例判定仍只有責任描述，沒有輸入、回傳形狀及缺值契約。

建議：補最小的正式簽名、結果型別及錯誤契約，讓後續 task 能依已固定的介面實作；不需要寫成實作碼。

**P-19 — blocking｜tasks.md:138–139、518**

問題：新增隔離自測的 Red 會接觸真實工具，且依賴本機安裝狀態。

證據：

- `test_real_tools_are_never_reached` 要先執行三個 `--version`，Red 卻要求「不建 autouse 隔離」。有安裝時會真的執行工具；沒安裝時可能先得到 `FileNotFoundError`，到不了 `which` 斷言。
- `test_without_removes_the_tool_from_path` 的 Red 預期在其他 PATH 目錄找到 Claude；CI 明定沒有 Claude，因此可能直接 Green。

建議：在 test sources 建立第二層、受控的 sentinel executable，用它模擬 PATH fallback；先斷言解析路徑，再執行。隔離失效也不能落到真實工具。若暫時移除已完成的隔離行為，須明標突變。

**P-20 — blocking｜tasks.md:19–26、203、392**

問題：兩個改寫後的 Red 依賴已被前面 Green 取代的 stub。

| 測試 | 證據 | 建議 |
|---|---|---|
| `test_records_are_write_once_and_ordered` | 前面的 receipt 測試已要求持久寫入索引並讀回最新 receipt；依 D1／2.1 的分工，不能仍保留「`append_record` 不寫檔」的 stub。 | 將 record 行為測試排在 receipt 測試之前，或指定可保留前面 Green 的增量缺陷。 |
| `test_receipt_stops_applying_when_anything_changes` | 前一列已要求 verified receipt 使 `next` 回 `dispatch`；`applicable` 不可能仍一律回 `(False, ["not_run"])`。 | 改成從「只判 verdict，尚未判版本」的實際增量狀態開始；若此前已完整實作，明標版本比較突變。 |

另外，tasks.md:214、309 的 Red 分別要求使用舊的路徑搜尋、Task 數量算法；前面已按新契約完成時會提前 Green。應調整測試順序，或明標回退算法的突變，不能要求 Implementer 違反第 26 行自行處理。

**P-21 — blocking｜design.md:224；tasks.md:351、355；Codex 樣本第 27、30 行**

問題：新的 Codex 拒絕判準與 live-probe 測試要求互相矛盾。

證據：樣本中的 `orca … task-create` 回 exit 1，輸出是結構化的 `runtime_access_denied`，`systemCode` 為 `EPERM`；沒有 `Operation not permitted`。照 D6 必須判 `executed`，但 `test_live_probe_shape_is_reproduced` 要求 `negative.orca` 成立，而且 reasons 恰好只有另外五項。

因此，即使該測試的突變能產生 Red，還原後也無法得到所列 Green。

建議：保留按 call 配對及非零 exit 的要求，另外明定如何辨識這種實際 Orca sandbox 拒絕；用原始結構補測，不能把 fake 輸出改成樣本沒有的字串。

**P-22 — blocking｜design.md:128、142–146、267–271；tasks.md:173、264、350**

問題：新增「没有 native turn／找不到或多份紀錄」案例，到不了測試要求的逐項判定。

證據：等待流程要求讀到完整 native turn；這些案例不能滿足，最後會 `probe_timeout`。D4 又要求失敗後停止並跳到 receipt，略過第 11 步；未判定的項目依 tasks.md:173 不放進 `items`。測試卻要求對應 item 明確為 `pass is False`，並保存要求／實際值，不能用不存在的 item 代替。

建議：明定逾時及 native 搜尋失敗後仍執行哪些證據判讀，如何產生失敗 item、原因及未知值；補齊 partial receipt 的契約，並以這條完整路徑驗 D18。

**P-23 — blocking｜design.md:199、361；tasks.md:330、350；Codex 樣本第 8–9 行**

問題：新版要求 fake 忠實保留樣本順序，但 Codex 讀回規則與該順序不相容。

證據：樣本的 `turn_context` 在第 8 行，探測任務的 user message 在第 9 行；D6 卻找「marker 之後第一筆 `turn_context`」。依樣本順序建立單一 turn，找不到所需 context；把 context 搬到 prompt 後面則違反新增的範本順序要求。

建議：用 native `turn_id` 將含 marker 的 user turn 與其 context 配對，明定零筆／多筆配對的結果；fake 保留實際順序並驗證這個關聯。

**P-24 — blocking｜design.md:250–252；tasks.md:312**

問題：新摘錄白名單刪除了部分判定所依據的證據，測試只檢查引用存在，無法證明引用內容足夠。

證據：白名單沒有 marker prompt 的必要內容、Claude `hook_success.command`，也沒有 Codex `session_meta.cli_version`。這些分別用於任務／turn 歸屬、設定排除及新增的版本一致判定。`observed` 或 `versions.native` 是判讀結果，不能代替被刪掉的 native 摘錄；原檔刪除後，只有 digest 也無法重看依據。

建議：增加最小、遮蔽後的證據欄位，例如 marker、turn 關聯、hook 來源與 native CLI version；逐類斷言 evidence 指向的摘錄確實包含該判定所需值，仍不保存完整 prompt 或設定全文。

**P-25 — blocking｜design.md:339–342；tasks.md:397；src/loopctl/state.py:105–115**

問題：新增的未核准 `status` 測試與設計的公開輸出契約不同。

證據：設計要求 profile 有 `verdict`、`receipt`、`versions`，且 reasons 是政策狀態；測試卻要求只有 `{status, reasons}`，原因固定為 `policy_not_approved`。現有政策狀態實際區分 `not_registered`、`not_approved`、`digest_mismatch`、`unreadable`。

建議：統一未核准時的完整欄位、未知值及原因格式，參數化這四種狀態；保留「不呼叫工具」的突變測試。照目前兩份契約實作，無法同時滿足。

**P-26 — non-blocking｜tasks.md:46；AGENTS.md:109–111**

問題：共同 commit 規則新增「`test` 不帶 scope」，與 AGENTS.md 不符。

證據：AGENTS.md 要求測試使用受測模組 scope；只有不可拆的跨 scope 變更等情況才省略。1.1 的共用骨架 commit 可以依跨 scope 例外判斷，但不能推廣成所有 `test` 都無 scope。

建議：改回 AGENTS.md 的規則，對共用骨架個別說明例外。

VERDICT: changes_required