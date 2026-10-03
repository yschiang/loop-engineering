# Spec 審查第 4 輪（Claude Fable 5.1 xhigh，同一 session）

- 受審版本：`05f8e37`（相對第 3 輪的 `d51f103`）。時間：2026-10-03T03:20:55Z ～ 2026-10-03T03:22:17Z。
- 提問：見 [spec-review-4-prompt.md](spec-review-4-prompt.md)。
- 結果：**`clean`**。第 3 輪的 S-20、S-26～S-30 全部 resolved；新增 S-31、S-32，都是 non-blocking。

## 處理

| Finding | 處理 |
| --- | --- |
| S-31 | DUR-01 改為「狀態檔的下一個動作與 `next` 不同時，以 `next` 為準」 |
| S-32 | AC 清單加入 D01（共 14 條），驗收條件表同步，並說明 D01 因 MODIFIED DUR-01 列入 |

## 四輪摘要

| 輪 | 版本 | blocking | non-blocking | 結果 |
| --- | --- | ---: | ---: | --- |
| 1 | `79bdb45` | 8 | 10 | changes_required |
| 2 | `f50b534` | 2 | 5 | changes_required |
| 3 | `d51f103` | 1 | 4 | changes_required |
| 4 | `05f8e37` | 0 | 2 | clean |

## 審查原文

第 4 輪完成。我讀了 `05f8e37` 的 durable-delivery delta 與 proposal、`spec-review-3.md` 的「處理」一節與 `git diff d51f103 05f8e37`，並把新增的 MODIFIED DUR-01 逐句對照現行 `openspec/specs/durable-delivery/spec.md` 的 DUR-01。

## 第 3 輪 finding 核對

| ID | 狀態 | 證據 |
| --- | --- | --- |
| S-20（剩餘） | resolved | durable-delivery L33「Transport 專有的識別（例如 Orca 的 Run、Task、Dispatch）」 |
| S-26 | resolved | 採建議 (a)。L45「清理結果記在 marker 與 handle 的持久紀錄與 preflight 的輸出」；AC-D30 L81「（殘留探測 worker 照 AC-D31 清理，結果記在持久紀錄與輸出）」；AC-D31 L85「清理結果記在持久紀錄與 preflight 的輸出，若這次有執行探測，也記進新的 receipt」。三處一致 |
| S-27 | resolved | L45「殘留的 worker 無法確認停止時，SHALL NOT 派新的探測 worker」；AC-D31 L85「政策已核准時，這次的 receipt 為 `unverified`，原因列出殘留的 marker 與 handle」；proposal L23 |
| S-28 | resolved | L47「目前的版本讀不到時不適用，原因為版本未知」；AC-D26 L72「或讀不到」；proposal L23 |
| S-29 | resolved | proposal L19「改不到 Implementer 探測工作區的檔案與 branch」；L23 加「脈絡 run」 |
| S-30 | resolved | MODIFIED DUR-01 L3-13：本文與 AC-D02 原樣保留，加入「狀態檔中的下一個動作只依 run 狀態計算；可不可以派工另依…receipt 與目前的 transport、agent CLI 版本判定」；AC-D01 L9 的 THEN 改為「依 run 狀態計算的下一步；`status` 另顯示依 receipt 與目前版本判定的結果，與 `next` 會回報的下一步一致」；proposal L41 列入 MODIFIED DUR-01 |

## 新的 finding

**S-31 · non-blocking · durable-delivery DUR-01 L5「兩者不同時以 `next` 為準」**
- 問題：「兩者」指涉不明。前半句講狀態檔的下一個動作，後半句講 `status` 與 `next` 都重新判定；讀成「`status` 與 `next` 不同時以 `next` 為準」會和 AC-D01 L9「與 `next` 會回報的下一步一致」矛盾。
- 證據：L5「`status` 與 `next` 每次都重新判定，兩者不同時以 `next` 為準」；L9「`status` 另顯示…與 `next` 會回報的下一步一致」。
- 建議：改成「狀態檔的下一個動作與 `next` 不同時，以 `next` 為準」。

**S-32 · non-blocking · proposal L43「AC（13 條）」、L55 驗收條件表**
- 問題：這輪 MODIFIED DUR-01 改了 AC-D01 的 THEN，`status` 多了一個可觀察結果（依 receipt 與目前版本判定的結果，與 `next` 一致）。AC-D01 沒有列進本 Feature 的 AC 清單，也不在驗收條件的 CI 列，交接時 ticket 的驗收清單會漏掉它。AC-D02、D03、O01、O19、O30 原樣保留、不列，是既有做法；D01 不同，它的 scenario 改了。
- 證據：L43 列 13 條，不含 D01；L55「全部 13 條」；durable-delivery L9 的 THEN 與現行 `openspec/specs/durable-delivery/spec.md` L14 不同。
- 建議：AC 清單改為 14 條加入 D01，驗收條件表的 CI 列同步；並在「和 roadmap 不同的地方」加一句說明 D01 因 MODIFIED DUR-01 而列入。

VERDICT: clean
