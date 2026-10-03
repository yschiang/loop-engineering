已核對指定規則、固定 spec、研究與 live probe、Feature 1 程式及測試，逐列審查 50 個測試規劃。全程唯讀，未執行測試、orca、claude 或 codex。

以下位置均指 `openspec/changes/orca-preflight/`，其他來源另列。

**P-1 — blocking｜design.md:269–276；task 6.1**

問題：清理失敗的 worker 會在下次執行時被當成已處理。

證據：殘留定義是「有 `started`，沒有 `closed` 或 `cleanup`」。但停止確認失敗仍寫入 `cleanup {confirmed: false}`。第三次 preflight 因而不再辨識該殘留，可以派新 worker，違反 AC-D31。另 D4 第 12 步寫 `closed`，卻未限定確認停止成功；tasks.md:229 又要求失敗時寫未列入紀錄種類的 `stop_unconfirmed`。

建議：只有停止確認成功才解除殘留；統一紀錄種類與終態規則。補測連續兩次清理失敗、政策未核准期間清理失敗，以及之後仍不得派新 worker。

**P-2 — blocking｜design.md:194、203；tasks.md:267、308**

問題：兩種 runtime 的拒絕判準都可能把不符合 AC-D27 的結果判成通過。

證據：

- Claude 只要求「帶 `toolDenialKind`」。research.md:331 列出的值還包括 `user-rejected`、`interrupted`，不能全部等同權限設定拒絕。
- Codex 只搜尋整段輸出的 `Operation not permitted`。命令可能執行成功，但某個附帶操作失敗；例如 `git push --dry-run` 不改 ref，因此「輸出含 EPERM＋ref 未變」仍不能證明 push 本身被阻止。

建議：Claude 明列可接受的拒絕種類並配對 tool-use ID；Codex 必須把拒絕證據對應到受測操作，無法區分時判未驗證。補測中斷、人工拒絕，以及正常執行輸出混有 EPERM 的情況。

**P-3 — blocking｜design.md:76–85、199；task 4.1**

問題：Codex 的載入設定沒有實際判定，卻固定通過。

證據：`settings.excluded` 對 Codex 是「記錄 config 覆寫值，本項判定為通過」；profile 也沒有定義保留／排除的設定來源。這不符合 DUR-09、AC-D28。research.md:351 已列出可觀察的 `world_state`、`thread_settings_applied`、plugin／MCP 資訊。

建議：定義 Codex 的設定來源契約及可核對的觀察值；觀察到排除項目時必須失敗，不能以啟動參數代替實際載入證據。加入相應測試與 receipt 欄位。

**P-4 — blocking｜design.md:219–231；tasks.md:270**

問題：遮蔽規則只涵蓋 dispatch capability，沒有涵蓋 spec 要求的其他 credentials。

證據：唯一規則是替換 `dcap_[A-Za-z0-9_-]+`；測試也只注入 `dcap_abc123`。但 receipt 會保存設定、gateway 值及 native 摘錄，其中可能含其他 token、授權欄位或帶憑證的 URL。AC-D28 明確要求兩類憑證都不得保存。

建議：界定可保存的證據欄位及敏感欄位處理規則，加入非 `dcap_` 憑證案例，驗證 receipt、`--out` 與其他提交證據均不洩漏。

**P-5 — blocking｜design.md:128、200、348–352；tasks.md:310**

問題：工作區搜尋規則與獨立 clone 的設計互相矛盾。

證據：D4 只在「路徑等於 run 的 repo 根目錄」的 Orca repo 找工作區；D12 卻要求 Reviewer 註冊於另一個 clone。按前者搜尋，後者會先得到 `workspace_not_found`，到不了獨立 clone 判定。現有 run 狀態也只有 `owner/name`，沒有實體 repo 根目錄欄位。另 `git rev-parse --git-common-dir` 可以回相對值 `.git`，直接比較字串會把兩個獨立 clone 誤判為共用。

建議：明定實體 repo／工作區的識別與來源，允許核准的 Reviewer clone 被找到；將 git common directory 解析為絕對實體路徑後比較。以 CLI 完整驗證 linked worktree 與獨立 clone 兩條路徑。

**P-6 — blocking｜design.md:132、213、278**

問題：允許兩個 role 同時探測，但資源檢查無法區分它們建立的 Task。

證據：兩個 role 可以同時執行，且可使用同一 Orca Run；每次卻都斷言 Task 數只增加自己的探測任務。兩者在同一基準數量後各建立一個 Task，安全的探測也會因增加兩個而失敗。

建議：按 Task identity 歸屬比對，或明確序列化共享 Run 的探測。補測兩個 role 同時使用同一 Run。

**P-7 — blocking｜design.md:128、222、286–296**

問題：receipt 的版本適用判定未綁定實際被探測的 agent 版本。

證據：設計分別保存 `agent_cli` 與 `native`，但只拿前者和目前版本比較，沒有要求兩者一致。若 controller 的 PATH 讀到版本 B，自訂 terminal 實際啟動版本 A，receipt 仍可能以 B 通過適用判定；被驗證的是 A，放行的卻是 B。research 的 P9 特別做了這項交叉核對。

建議：定義 controller 讀到的版本、實際 native 版本及探測期間換版的處理規則；不一致時不得產生可用 receipt，並加入測試。

**P-8 — blocking｜tasks.md:227、350、353、417**

問題：下列 Red 無法保證失敗在指定斷言，或其實是未標記的突變。

| 測試 | 證據 | 建議 |
| --- | --- | --- |
| `test_readback_mismatch_is_unverified` | 3.1 明定 verdict 永遠是 `unverified`，因此「不比對讀回值」也不會讓 verdict 比較失敗。 | Red 改斷言對應 item 的 `pass` 與要求／實際值。 |
| `test_unapproved_policy_comes_before_the_receipt` | receipt 適用時，先檢查 receipt、再檢查政策，仍可回相同 `human` action。 | 以禁止版本呼叫的斷言證明順序，或精確定義會錯誤提早返回的突變。 |
| `test_write_commands_keep_the_state_next` | `effective` 是純函式；讓 `decide` 呼叫它不會產生 `--version` 呼叫。 | 突變實際的讀版本路徑，並設定會觸發該路徑的前提。 |
| `test_repo_policy_profiles_are_distinct_models` | 前一列完成後，D2 的正式設定已是不同模型；「先把 Reviewer 改成同模型」就是突變。 | 明標突變，避免觸發共同規則「提前 Green 就停下」。 |

**P-9 — blocking｜tasks.md:89–133、175–177、205、226**

問題：共用骨架尚未保證後續測試能抵達所列 Red。

證據：1.1 的自測只有固定回應、未知呼叫與時鐘；後續卻依賴動態 marker／UUID 的擷取與代換、寫 native 檔、資源變更、持久狀態及跨程序中斷。這些能力沒有自己的骨架測試。2.1 前三個測試又直接要求尚未交付的 `receipts.write/latest`、`store.append_record/list_records` 能執行；僅建立 preflight CLI stub 不會解決它們的 import／setup 問題。跨 `FAKE_LOG` 與 probes 的寫入順序，也不能只靠各自的編號證明。

建議：把必要介面骨架與共用 fake 能力放入第一個 task，逐項驗證；順序測試使用 test sources 的觀察點或同步屏障。明定後續測試開始時已存在的 API 與回傳契約。

**P-10 — blocking｜design.md:319–330；tasks.md:185、325–332**

問題：測試隔離沒有覆蓋「工具不存在」及既有 `status` 測試。

證據：把 fake 目錄加到 PATH 前面，不代表未安裝 fake 的工具不存在；本機仍可能找到真實 orca／claude。既有 `tests/conftest.py:264–270` 只隔離 `LOOPCTL_HOME`，大量既有 `status` 測試沒有使用新增 fixture；D9 卻要求 `status` 一定讀版本。這會違反「所有 pytest 用 fake」及 Implementer 不碰真實工具的執行界線。

建議：建立涵蓋整套測試的外部工具隔離預設，缺工具案例使用真正受控的 PATH；未安排的工具呼叫應立即由測試環境拒絕。不得依賴開發機剛好沒安裝工具。

**P-11 — blocking｜tasks.md:47–62、186、207、332、403**

問題：後續實作需要修改的檔案未列入 owned paths，且早期測試綁住會被移除的 stub。

證據：

- `test_unselected_tools_are_never_called` 要求走到 `not_implemented`；3.2 完成後該結果不再成立，但後續 task 不擁有 `tests/test_preflight_static.py`。
- 5.1 要新增 `preflight.current_versions`，共用擁有表卻漏列 5.1。
- 7.1 要新增 `tests/test_policy.py` 的測試，owned paths 沒有該檔。

建議：早期測試只斷言能長期成立的公開行為；需要更新 scenario／前置條件的 task 明列擁有權。補齊上述路徑及共用檔案順序。

**P-12 — blocking｜tasks.md:383–384；design.md:132**

問題：中斷測試的停止點與預期持久紀錄不一致，下一個測試還依賴前一個測試的狀態。

證據：`dispatch` 是 `worker-start` 返回後才寫入；fake 收到 `worker-start` 就 SIGKILL controller，不能保證存在 `dispatch` 紀錄。另「上一個測試之後再跑」不適用現有每個測試各自建立 `tmp_path`／home 的 fixture，也無法用指定的單一 `-k` 指令執行。

建議：區分「外部已接受、dispatch 尚未落盤」與「dispatch 已持久化」兩個中斷點，以同步屏障控制；每個清理測試在自己的前置流程製造殘留。

**P-13 — blocking｜tasks.md:311**

問題：重現 live probe 的 Green 與真實研究結果及前一列測試矛盾。

證據：research.md:477 的 P7 還包含 `gh` 網路錯誤及 `loopctl` exit 127；兩者都不是 runtime 拒絕。tasks.md:308 也明定網路錯誤不能通過。因此 `reasons` 不可能「恰好只有」git push、worker_done、independent_clone 三项。

建議：忠實重現 P7 並保留所有缺口。若要測 PATH 修正後的新情境，另列 scenario，不能稱為同一次 live probe 的結果。

**P-14 — blocking｜tasks.md:267；design.md:206–215**

問題：「五個負例 × 四種結果」包含無法依設計判定的組合。

證據：(d) 要求每個負例都能因「資源改變」而失敗，但設計對 `gh issue list` 與 `loopctl decide --help` 明定只看拒絕，沒有相應資源觀察值。fake 即使改了資源，產品也沒有該項輸入可以判斷。

建議：逐個負例列出實際可成立的情境及資源不變式；不要使用不適用的笛卡兒積。需要驗證的狀態 revision 等觀察值，應在正式設計與測試中一致定義。

**P-15 — blocking｜tasks.md:227、307、348–352、384、427–442**

問題：14 個 AC 雖都有列名，部分 THEN 尚未被測試證明。

證據：

- **D18**：缺 repo／branch 不符、完全找不到 marker、effort／cwd 缺欄位等案例。
- **D19、D26、D29**：主要驗 preflight／`next`；`status` 測試只驗欄位存在，沒有驗具體驗證狀態、版本、缺口與原因。
- **D29／DUR-09**：沒有驗另一個已核准相同 digest 的 run 可共用 receipt，也沒有驗 preflight 不改 feature 狀態。
- **D31**：清理測試驗紀錄與輸出，沒有驗新 receipt 保存清理結果。
- **G19**：矩陣只有人工文件核對，卻在驗收段宣稱全部 14 條由 CI 證明。

建議：補成具名測試與完整 Red／Green；驗收表分清 CI、文件核對與真實 receipt 各自證明的內容。

**P-16 — blocking｜design.md:57、90–96、112；tasks.md:159、209–214、292–296**

問題：blocking edges 與錯誤契約不足，實作必須自行決定會影響 CLI 行為的規則。

證據：`Policy`、`Completed`、負例判定介面的完整回傳形狀與錯誤情況未定義。已登記並核准的政策可能是 malformed YAML、非 mapping，或含無效 timeout；Feature 1 只核對 bytes digest，不會排除這些情況。現有 `guarded` 也只接 `store.IOFailure` 等特定例外，並非所有 YAML／檔案錯誤。

建議：補明必要介面、錯誤分類、exit／receipt 行為，以及缺值與提前停止時的欄位契約；至少加入 malformed policy、無效 timeout、工具輸出不可解析的測試。

**P-17 — blocking｜tasks.md:68、79、87、104**

問題：1.1 的 effort 不符合 D69。

證據：這個 task 不只是測試骨架，也實作「未核准政策不得探測」的授權界線，並決定被核准 bytes 的 digest／解析結果。出錯可能削弱安全，依指定 effort 表應為 Implementer／Reviewer 都 `xhigh`，不能以「一般行為加骨架」歸為 `high`。

建議：改成 `xhigh／xhigh`；或把純骨架與政策授權垂直切片分開，再各自依風險標示。

**P-18 — blocking｜tasks.md:40–45、342；design.md:375–379**

問題：已明定的不相容 CLI 行為變更，commit subject 沒有標示 breaking change。

證據：5.1 會讓原本回 `dispatch` 的既有 run 改回 `human`／`preflight`；Migration Plan 已明說此變化。但預定 subject 是 `feat(cli): …`，缺少 `!`。AGENTS.md:130–131 要求對應的 `BREAKING-CHANGE:`，且本票必須有 `Refs: #44`。

建議：5.1 使用 `feat(cli)!: …`，body 說明不相容處及政策核准／preflight 的遷移方式；共同 commit 規則補齊必要 trailer。

VERDICT: changes_required