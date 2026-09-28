# 舊碼提取紀錄

每個從 `4ce1110` 提取行為的 task 依執行順序追加自己的一節，只追加、不改其他 task 的內容（cleanup-map §1；tasks 共用檔案表）。

## T2.1 — `store`（attempt 1）

- **來源**：`4ce1110:src/delivery/store.py`，以 `git show` 讀取，未 import、未 checkout。
- **取用**：
  - 耐久寫入原語：`_full_fsync`（macOS 另做 `F_FULLFSYNC`）、`_fsync_dir`、以 `O_EXCL` 建立並 fsync 的暫存檔（`_write_tmp`）、`os.link` 的 write-once 協定、`os.replace` 的原子替換、`flock` 的 feature lock。
  - 載入時的信任核對：缺檔、壞 JSON、`schema_version` 不符都視為不可信。
- **改動與理由**：
  - 改為 history-first：先 write-once 寫入 `history/<rev>.json`（含 `prev_digest`、`state_digest`、`transition_id`），再原子替換 `feature.json`（design §3）。舊碼只有單一 `run.json`，中斷後無法分辨已提交與未提交。
  - 手改偵測：舊碼以程序內記住的 digest 比對，換程序就失效；新碼以 history 記錄的 `state_digest` 比對現行檔，跨程序有效（s3 的手改 gate）。
  - 物件引用改為 typed ref（`{"$object": "sha256:…"}`）：舊碼以正規式從任何字串抓 `sha256:`，會把文件 digest 誤當物件引用；新碼只核對 typed ref，文件 digest 欄位不受影響（s6，S1-R06）。
  - 新增 `transition_id` 冪等與衝突：同一 id 同內容回傳原 revision，內容不同 → 原件保存在 `conflicts/`、feature Blocked（`transition_conflict`）。
  - 新增 `expected_revision` 核對（兩個程序同時 commit，恰一方成功；s4）。
  - 不帶入：命名 blob（`put_blob(name=…)`）與 `BlobConflict` 的旁存檔；物件只以內容定址。
- **適用的舊 findings**：無直接對應；S1 findings 各自仍 open（cleanup-map §1）。
- **新的驗證**：M-STATE s1、s2、s3、s4、s6（`tests/test_state.py`）。

## T3.1 — G1 證據（attempt 1）

- **來源**：`4ce1110:src/delivery/runner.py`（`snapshot_worktree`、`_classify`、`_case_ids`）與 `4ce1110:src/delivery/gates.py`（`evaluate_g1`、`_red_problems`、`_task_g1`），以 `git show` 讀取，未 import、未 checkout。
- **取用**：
  - snapshot：暫存 index（`GIT_INDEX_FILE`）上 `read-tree HEAD` → `add -A` → `write-tree` → `commit-tree -p HEAD`，再以 ref 保存，工作區與真正的 index 都不變（`loopctl.tools.evidence.snapshot`）。
  - 分類：pytest exit 1 且 junit 至少一個 failure 才是 Red；其他 exit（2 收集錯誤等）不是（`loopctl.evidence.classify`）。
  - G1 狀態取最差者、逐單位列原因的形狀。
- **改動與理由**：
  - S1-R11：舊 `evaluate_g1([], …)` 以 `_worst([])` 回 passed；新碼任務集合為空 → `failed(task_set_empty)`（g4）。
  - 舊碼以 `snapshot.parent` 是 H 的祖先判定 lineage，兄弟 snapshot 也會通過；新碼要求三項各自成立（D51-R07）：scope（snapshot 變更與 attempt 範圍）、捕捉時的對應（provenance 的 attempt／worktree，加上 snapshot 在 attempt 自己的歷史上或失敗測試的 delta 出現在 attempt commit）、attempt commit 是 H 的祖先（g3b、g11）。
  - 舊碼缺 replay 時回 unknown（強制 replay）；新碼正常路徑不 replay，只在同一 tree 的另一次執行讓 Red 的失敗測試通過時才 replay，且 replay 從不成為 Red（g1、g2）。
  - junit 的 failure 若是 ImportError／ModuleNotFoundError／SyntaxError 類，不算行為失敗（tasks.md：ImportError 不算）。
  - 舊 runner 在 worker 的 worktree 以任意 argv 執行並以 `{junit}` 代入；新碼只執行已登記政策的 `evidence.commands`（`{junit_out}`），Green 與 replay 在 `$LOOPCTL_HOME` 下的 `worktree add --detach` 乾淨 checkout，並有 process group 時限與 `activities` 紀錄（g9、g14、g15）。
  - 不帶入：scope 在捕捉時拒絕（改由 G1 判定並列原因）、`snapshot_drift`、`env` digest、N/A 的 `diff_digest`（改為核對 Reviewer 審的 head 等於 attempt commit）。
- **適用的舊 findings**：S1-R01、S1-R11、S1-R13、S1-R15（仍 open，待獨立覆核）。
- **新的驗證**：M-G1 g1–g15、g3b（`tests/test_g1.py`）。
