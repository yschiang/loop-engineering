第 2 輪。計畫已依你第 1 輪的 P-1～P-18 修改，新版本是 `40b8411`（同一個 clone 已更新並 checkout）。`git diff 81be2c0 40b8411 -- openspec/changes/orca-preflight` 可看全部修改；design.md 改了 D1～D4、D6、D8～D10、D12，tasks.md 整份重寫。另外新增 live probe 的 native 紀錄樣本 `docs/research/2026-10-03/orca-preflight/samples/`（已去敏感化），作為 fake 的欄位範本。

處理摘要：
- P-1：紀錄終態改為只有 `closed`（停止已確認）或 `cleanup {confirmed: true}` 才結束；`stop_unconfirmed`、`cleanup {confirmed: false}` 不結束（design D8）。6.1 新增連續清理失敗、政策未核准時清理失敗的測試。
- P-2：Claude 只接受 `toolDenialKind == "permission-rule"`，以 `tool_use_id` 配對；Codex 要求該呼叫自己的 exit 非 0 且自己的輸出含 `Operation not permitted`（D6「拒絕的判準」）。3.2、4.1 新增對應測試。
- P-3：Codex profile 加 `exclude.plugins`，以 `turn_context.disabled_plugin_ids` 判定；其他觀察值記在 `observed`，hook 開關記成 configured／不可觀察（D2、D6）。4.1 新增測試。
- P-4：遮蔽規則擴充（`sk-`、`ghp_`、`github_pat_`、`Bearer`、URL userinfo、env 中鍵名含 TOKEN／SECRET／KEY／PASSWORD／AUTH 的值）；摘錄只取固定欄位（D6）。3.2 的測試加入非 `dcap_` 憑證。
- P-5：以 `gitRemoteIdentity.canonicalKey` 找所有相符的 Orca git repo，再找工作區；0 個／多個各有原因；git common dir 以 `--path-format=absolute` 與 realpath 比較（D4、D6、D12）。2.1、4.1 新增測試。
- P-6：orca 負例的資源改以 spec 等於 `probe <s>` 的 Task 識別，不比數量（D6）。3.2 新增測試。
- P-7：讀 agent CLI 版本的前值與後值，與 native 版本必須相同（`version.consistent`）；適用判定拿 native 版本與目前值比（D4 第 6、12a 步、D9）。3.1 新增測試。
- P-8：四個 Red 改寫（readback 改斷言 item；unapproved 以沒有 `--version` 呼叫證明順序並標突變；write commands 的突變走會讀版本的路徑；repo policy 測試標突變）。
- P-9：1.1 建立所有新模組的介面與 stub，以及 fake 的擷取、代換、write／state／snapshot／kill_parent，各有骨架測試；順序以 `snapshot` 證明。
- P-10：autouse 的工具隔離覆蓋整套測試，未預期的呼叫在 teardown 失敗；缺工具以受控 PATH 製造（D10）；政策未核准時 `status` 不呼叫工具。
- P-11：拿掉斷言 `not_implemented` 的測試；共用檔案表補 5.1 的 `preflight.py`、7.1 的 `tests/test_policy.py`、3.2 對 3.1 測試檔的擁有。
- P-12：中斷分兩個點（`worker-start` 時、`terminal wait` 時），每個測試自己製造殘留。
- P-13：live probe 的重現忠實保留 gh、loopctl 兩項缺口。
- P-14：負例改依 D6 的表，只展開適用的結果。
- P-15：補 D18 的缺欄位／找不到 marker、`status` 的具體值、跨 run 共用、preflight 不改 feature 狀態、新 receipt 含 cleanup；驗收表分 CI／文件／真實 receipt。
- P-16：補 `Policy`、`Profile`、`Completed`、`Unparseable` 的介面與錯誤分類，malformed／timeout 無效／不可解析的測試。
- P-17：1.1 改 xhigh／xhigh。
- P-18：5.1 改 `feat(cli)!:` 加 `BREAKING-CHANGE:`；所有 commit 加 `Refs: #44`。

請：
1. 逐條核對 P-1～P-18 是否已解決（`resolved`、`partly`、`not resolved`，附證據）。
2. 用第 1 輪的七項檢查，只看這次的修改有沒有帶進新的問題，新的 finding 從 P-19 起編號；特別再逐一判斷新寫或改寫的每個 Red 能否失敗在所寫的斷言上。不要重提已解決的事。

輸出格式同第 1 輪；最後一行寫 `VERDICT: clean` 或 `VERDICT: changes_required`。
