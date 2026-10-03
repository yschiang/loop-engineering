你是獨立的計畫 Reviewer（loop-engineering D52）。唯讀：不要修改、建立或刪除任何檔案，不要 commit、push 或寫 GitHub，不要執行 orca、claude 或 codex。輸出用繁體中文。

## 審查對象

目前目錄是 `feature/orca-preflight` 的全新 clone，commit `81be2c0`。審查 OpenSpec change `orca-preflight`（Feature 2a，ticket #44）的計畫：
- `openspec/changes/orca-preflight/design.md`
- `openspec/changes/orca-preflight/tasks.md`

它們要實作的是已經確認、固定的 spec：同目錄的 `proposal.md`（範圍、不做、驗收條件、待決、Spec 確認）與 `specs/*/spec.md`（MODIFIED ORC-01、DUR-01、DUR-02；ADDED DUR-09、GAT-05、GAT-08；14 條 AC）。spec 本身不在審查範圍；若計畫與 spec 衝突，指出計畫的問題，或列為要交 Project Lead 的 spec 問題。

## 規則來源（請實際打開核對）

- `/Users/johnson.chiang/.claude/skills/spec-to-plan/SKILL.md` 第 2、3 節：垂直切片、一個 session、prefactor 與共用測試骨架先做、blocking edges 附介面與不變式、每個 task 的欄位、每個測試的 Red 斷言、D69 effort 表、D72 mode 表、red-flag 表、驗收驗證、範圍／環境／風險／界線。
- `AGENTS.md`（特別是「不為測試改 production 程式」與 commit 規範）、`openspec/config.yaml`、`docs/decisions.md` 的 D11、D52、D53、D57、D68、D69、D71、D72、D75、D76、D79。D80、D81 在 `git show origin/docs/split-orca-preflight:docs/decisions.md`。
- 現況研究與 live probe 結果：`docs/research/2026-10-03/orca-preflight/research.md`（文末「live probe 結果」是真實環境的觀察）、`docs/research/2026-10-03/orca-dispatch/verification.md`。
- 現有程式：`src/loopctl/`、`tests/`（Feature 1）。Feature 1 的 design 與 tasks：`openspec/changes/archive/2026-10-03-run-decisions/`。
- 參考實作（唯讀，不是證據）：`/Users/johnson.chiang/workspace/loop-engineering-thin`（`fcefecc`）。

## 請檢查

1. 切法：每個 task 是否垂直、可從公開入口單獨驗證、一個 session 做得完；共用測試骨架是否先做且有自己的測試；blocking edges 是否寫出介面、不變式、順序限制與錯誤情況；有沒有只做一層的 task。
2. D68：每個測試是否有名稱、斷言的可觀察行為、Red 應失敗的斷言、Green、指令；**逐一判斷每個列出的 Red 是否真的能失敗在所寫的斷言上**（不是停在 import、usage error、未實作的命令或 stub）。考慮 task 順序：前面 task 交付的東西會讓後面某個 Red 提前變綠嗎？標「突變」的是否合理？
3. 14 個 AC 是否都有對應的測試與驗收方式，測試是否真的驗到 scenario 的 THEN。真實 receipt 的驗收方式是否清楚。
4. owned paths、共用檔案的規則、effort（D69）與 mode（D72）是否正確；commit subject 與 scope 是否符合 AGENTS.md。
5. design 是否與 spec 一致、是否在高層設計與決策的邊界內；「刻意不同之處」是否都有理由；有沒有違反 AGENTS.md 的測試後門（只給測試用的設定、hook、accessor）。
6. 與現有程式的介面是否正確（檔名、函式、欄位、exit code、既有測試的行號），會被改到的既有測試是否列全。
7. 風險、環境、執行界線是否寫明；有沒有計畫沒定義、但實作一定會碰到的情況。

## 輸出

逐條列 finding：ID（P-1、P-2…）、`blocking` 或 `non-blocking`、位置（檔案與行或 task／測試名稱）、問題、證據、建議的改法。`blocking` 用在會讓實作照計畫做不出來、Red 無法成立、AC 沒被證明、或違反規則的問題。最後一行寫 `VERDICT: clean`（沒有 blocking）或 `VERDICT: changes_required`。
