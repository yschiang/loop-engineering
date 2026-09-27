# `delivery` CLI（S1）

S1 的命令直接呼叫 controller 核心並寫入真實狀態。需要外部 adapter（runtime、GitHub）的動作在 S1 不存在時以 exit 3 回報「adapter 不可用（S2）」，不嘗試任何外部操作、不假裝完成。

| 命令 | 用法 | S1 行為 |
| --- | --- | --- |
| `init` | `delivery init --repo R` | 建立 `workflow.yaml`（已存在則 exit 1，不覆寫）與 `.delivery/runs/` |
| `start` | `delivery start --repo R --feature F --run-id ID --branch B --tasks tasks.json --plan-version P --state-home H [--repo-id X]` | 先經主機層級 feature authority 取得控制權（另一 clone／run → exit 1 並輸出既有 state_dir）；同一 repo 已有 active run → 回 `resume`，不重建也不重置預算；新 run phase=`awaiting_approval` |
| `adopt` | `delivery adopt --repo R --feature F --run-id ID --facts facts.json --state-home H [--repo-id X]` | 匯入 facts 的 `tasks`、`plan_version`、`bindings`、`approval`（僅在 `d11` 為真時）、`branch` 與 owner handoff，再以 `route_intake` 決定 phase；缺口逐項列為 blockers |
| `status` | `delivery status --run-dir D` | 顯示 phase、版本、gates 理由、blockers、next action、預算；state 不可信 → exit 1 |
| `decide` | `delivery decide --run-dir D --kind K --actor A [--actor-kind human] --source S --reason R --subject JSON [--state-home H --feature F [--repo-id X]]` | 驗證後履行決策契約：approve_plan／revise／scope_change／adopt_binding／unblock／resolve_finding／waive_finding／policy_change／accept（登記 retro op）／return（ac_defect 建立 batch＋fix task）／budget_extension；缺資料或不合法 → exit 1。`abandon_run` 需 `--state-home --feature` 與 `subject.evidence`，經 feature authority 記錄 |
| `evidence run` | `delivery evidence run --kind red --task T --attempt A --cwd W --t0 SHA --scope src,tests --out DIR -- <cmd…>` | baseline＋overlay snapshot 後執行命令，以 exclusive create 寫 `DIR/<kind>.json` 與原始 stdout/stderr；同名已存在 → exit 1，不覆寫；snapshot 被拒 → exit 1 |
| `submit-result` | `delivery submit-result --inbox DIR --file result.json` | write-once 寫入 inbox；同 attempt 不同內容 → exit 1，保留雙方 |
| `reconcile` | `delivery reconcile --run-dir D` | 本機部分（信任檢查、pending history）執行；外部版本重讀需 GitHub adapter → exit 3 |
| `resume` | `delivery resume --run-dir D` | 本機 reconcile（含前一 process 遺留 activity 的 crash unknown interval 計入）；resting phase 回 exit 0；需派工時 runtime adapter 不可用 → exit 3 |
| `preflight` | `delivery preflight --repo R --profile implementer` | 輸出 runtime 可用性與 launcher 基本拒寫探測；runtime 不可用 → exit 3。完整 §10.4 負例在 `tests/os` |

主迴圈 `delivery.loop.step()` 在 S1 以 fake runtime／GitHub（`tests/fake_agents.py`）驗證完整路徑；真實 adapter 屬 S2（tasks 3.x／4.x）。
