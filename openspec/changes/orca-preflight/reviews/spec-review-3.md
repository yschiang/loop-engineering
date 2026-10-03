# Spec 審查第 3 輪（Claude Fable 5.1 xhigh，同一 session）

- 受審版本：`d51f103`（相對第 2 輪的 `f50b534`）。時間：2026-10-03T03:16:57Z ～ 2026-10-03T03:19:40Z。
- 提問：見 [spec-review-3-prompt.md](spec-review-3-prompt.md)。
- 結果：`changes_required`。第 2 輪的 S-13、S-19、S-21～S-25 resolved，S-20 partly；新增 S-26～S-30，其中 S-26 為 blocking。

## 處理

| Finding | 處理 |
| --- | --- |
| S-20（剩餘） | DUR-09 改為「Transport 專有的識別」 |
| S-26 | 採建議 (a)：清理結果記在 marker 與 handle 的持久紀錄與 preflight 的輸出；有執行探測時才另記進 receipt。AC-D30、AC-D31 與 DUR-09 本文一致 |
| S-27 | 殘留的 worker 無法確認停止時，不派新的探測 worker；政策已核准時 receipt 為 `unverified`，列出殘留的 marker 與 handle |
| S-28 | 目前版本讀不到時 receipt 不適用，原因為版本未知；AC-D26 的 WHEN 加「讀不到」 |
| S-29 | proposal 的 Reviewer 負例目標與 receipt 欄位（脈絡 run）同步 |
| S-30 | MODIFIED DUR-01：狀態檔的下一個動作只依 run 狀態；可不可以派工由 `status` 與 `next` 依 receipt 與目前版本重新判定，不同時以 `next` 為準；AC-D01 的 THEN 同步 |

## 審查原文

第 3 輪完成。我讀了 `d51f103` 的三份 spec delta 與 proposal、`spec-review-2.md` 的「處理」一節與 `git diff f50b534 d51f103`，並對照現行 `openspec/specs/`。

## 第 2 輪 finding 核對

| ID | 狀態 | 證據 |
| --- | --- | --- |
| S-13 | resolved | delivery-gates AC-G24 L12：目標改為「Implementer 探測工作區的檔案與它的 branch（包括移動 ref）」 |
| S-19 | resolved | delivery-orchestration L5「`preflight`、`status` 與 `next` 可以以固定的命令讀取 transport 與 agent CLI 的版本」；durable-delivery L33「transport（Orca）與 agent CLI 的版本」、L35、AC-D26 L60「transport 或 agent CLI 的版本」；proposal L26 |
| S-20 | partly | L23、L25、L27、L28、L48 都改成 transport；AC-D27 L15 改成「agent CLI 的權限設定或 sandbox」。剩 L21「Runtime 專有的識別（例如 Orca 的 Run、Task、Dispatch）」仍把 Orca 稱作 runtime，應改「Transport 專有的識別」。非阻擋 |
| S-21 | resolved | L23「Preflight 以一個 run（repo＋feature）為脈絡，依該 run 的政策核准判定」；L33 receipt 記「脈絡 run…該 run 已核准 `workflow.yaml` 的 digest」；L35「同一份 receipt 可被任何已核准同一 digest 的 run 採用」；AC-D30 L68 的 WHEN 加上 run；AC-D29 L41；proposal L17、L24 |
| S-22 | resolved | AC-G24 L12「（「被拒」與資源檢查依 AC-D27）」 |
| S-23 | resolved | L23「派出探測 worker 之前，SHALL 先持久記錄 marker 與 transport 的 handle」；L33「殘留探測 worker 的清理不受政策核准狀態影響」；AC-D31 L73「依先前持久記錄的 marker 與 handle 找出殘留…政策是否核准不影響這個清理」；proposal L17 |
| S-24 | resolved | AC-D29 L41「若該 profile 是 Implementer，已核准同一 digest 的 run 的 `next` 回報可以派工」；L26「Reviewer 另做 GAT-05 的隔離負例與不同模型的核對」；GAT-08 L17 矩陣加「載入的設定、兩個角色不同模型」 |
| S-25 | resolved | L23「Preflight 不需要協調權，也不寫 feature 狀態」；L33「Receipt 存在 run 狀態之外，帶自身內容的 digest；內容與 digest 不符的 receipt 不適用」；proposal L17、L24 |

## 新的 finding

**S-26 · blocking · durable-delivery AC-D30 L69 與 AC-D31 L73**
- 問題：這輪同時加進兩句互相衝突的 THEN。政策未核准而且有殘留探測 worker時，AC-D30 要求 preflight「也不寫 receipt（殘留探測 worker 的清理照 AC-D31 進行）」，AC-D31 卻要求「把處理結果記進新的 receipt」。這個交集是 spec 自己點名的情況，測試無論怎麼做都違反其中一條。
- 證據：L69「preflight 拒絕執行，不派新的探測 worker，也不寫 receipt（殘留探測 worker 的清理照 AC-D31 進行）」；L73「找出殘留的探測 worker 並停止它（以 process-info 確認），把處理結果記進新的 receipt；政策是否核准不影響這個清理」。
- 建議：二選一寫清楚。(a) 清理結果記在 L23 那份持久紀錄（marker 與 handle 的紀錄）與 preflight 的輸出，不寫 receipt；AC-D31 改成「記進持久紀錄；若這次 preflight 有執行探測，另記進新的 receipt」。(b) AC-D30 允許寫一份 verdict 為 `unverified`、原因為政策未核准的 receipt，清理結果記在裡面。

**S-27 · non-blocking · AC-D31 L73；AC-D19 L48**
- 問題：殘留的探測 worker 停不掉時（process-info 仍顯示它）怎麼辦沒寫。AC-D19 的「停止後 process-info 仍顯示探測 agent」講的是本次探測的 agent。殘留 worker 若還在同一個探測工作區，新探測的資源檢查（檔案不存在、ref 未變）會被它干擾。
- 建議：AC-D31 加一句「殘留 worker 無法確認停止時，不派新的探測 worker，本次 preflight 為 `unverified`，原因列出殘留的 marker 與 handle」。

**S-28 · non-blocking · delivery-orchestration L5；durable-delivery L35、AC-D26 L60**
- 問題：版本改由 `status` 與 `next` 自己讀之後，讀不到（transport 或 agent CLI 不在、命令失敗）時 receipt 算不算適用沒寫。AC-D26 的 WHEN 只有「版本和目前不同」，讀不到既不是相同也不是不同。
- 建議：L35 加「目前版本讀不到時 receipt 不適用，原因為版本未知」；AC-D26 的 WHEN 加「或目前版本讀不到」。之後 preflight 會依 AC-D23 以 Blocked 停下，路徑自然收斂到人。

**S-29 · non-blocking · proposal L19、L23**
- 問題：spec 這輪改了，proposal 兩處沒跟上。L19 仍寫 Reviewer 的負例目標是「代表作者的 branch 與 worktree」，AC-G24 已改成「Implementer 探測工作區」；L23 的 receipt 欄位清單沒有「脈絡 run」，L33 有。
- 建議：兩處同步成 spec 的用語。

**S-30 · non-blocking · delivery-orchestration L5；現行 `openspec/specs/durable-delivery/spec.md` AC-D01 L13-14**
- 問題：ORC-01 這輪明寫 `next` 會讀外部版本，加上 `next` 依賴 run 狀態之外的 receipt，現行 AC-D01 的 THEN「打開 run 的狀態檔…能看到…`next` 會回報的下一步」在狀態檔這條路徑不再嚴格成立：狀態檔存的下一步可能是 `dispatch`，實際 `next` 因版本或 receipt 改變而回 `preflight`。`status` 這條路徑不受影響，因為它會重算。Feature 1 的 design 已預告這個風險，但 2a 沒有 MODIFIED DUR-01。
- 證據：AC-D01 L14「不讀歷史就能看到…blockers 與 `next` 會回報的下一步」；archived design L277「本 Feature 的 `next` 只由狀態決定，所以存下的值與 `status` 重算的一致」；verification L107「這就把檔案與外部輸入帶進 `next`（F1 design L467 預告的風險）」。
- 建議：加一句 MODIFIED DUR-01 或在 proposal 的「需求原文沒有帶入的句子」說明：狀態檔顯示最後一次計算的下一步，`status` 與 `next` 以 receipt 與目前版本重算；或者 `next` 每次重算後把結果與依據寫回狀態，讓 AC-D01 繼續成立。

VERDICT: changes_required
