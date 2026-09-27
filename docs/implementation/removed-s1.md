# 舊 S1 實作不在本 lineage

`delivery/thin-controller` 從 `main` 的 `8fb4f8d`（PR #3 merge，D53 採用的文件）出發。這條 lineage 不包含舊 S1 controller 的程式碼與測試；新程式依 D46 在 `src/loopctl/` 重建，只依 `docs/design-candidate/d45-04/cleanup-map.md` 選擇性提取行為。

| 舊成果 | 位置 | 狀態 |
| --- | --- | --- |
| S1 core `src/delivery/`、`tests/` | commit `4ce111011fde83c3a2784402cea111e52a954b3c`，branch `delivery/s1-controller-core` | [PR #2](https://github.com/yschiang/loop-engineering/pull/2) 仍 open、未 merge；17 項 blocking findings（S1-R01–R17）仍 open |
| 第一輪修正嘗試（未覆核） | commit `5d334d57a4950c057ce5bdc76ad1218a42e97539`，branch `feat/s1-fix-01`；只保存在本機 `.delivery/bootstrap/bootstrap-s1-20260927/snapshots/20260927T065840807230Z/s1-run/checkpoints/s1-fix-01-5d334d5.bundle`（sha256 `171c47c3bae9f5a1fdced2f9ea62a1ad54473867a448dc04c60fec19995b6cd2`），不在任何遠端 | 只作參考；14 項 fix_submitted、3 項未完成，沒有任何 finding 經獨立覆核關閉 |

- 讀舊碼用 `git show 4ce1110:<path>`；不 checkout 舊 branch 到本 worktree，不反向 import，也不建立 `legacy/`。
- 每次提取依 cleanup-map §1 記錄在 `docs/implementation/extraction-log.md`。
- 刪除或不帶入舊碼，不等於關閉任何舊 finding；舊測試的通過不算新證據。
