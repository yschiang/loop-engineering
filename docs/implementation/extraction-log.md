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
