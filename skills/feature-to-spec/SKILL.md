---
name: feature-to-spec
description: Use when a feature chosen on the roadmap needs its OpenSpec change, spec and ticket before engineering starts, or when the spec of an existing feature must change, whether still in preparation, blocked on scope inside the feature loop, or sent back because the requirement changed. Used by the Project Lead or the Engineer. Not for project-level planning or close-out (project-lead), and not for design and plan (spec-to-plan), implementation (plan-to-code) or pull requests and gates (to-pr).
---

# Feature to spec

Turn one roadmap feature into an OpenSpec change (proposal and spec delta) and a ticket, get the spec confirmed, and hand the feature to the feature loop. The person you work with may be the Project Lead or the Engineer (D64); the spec confirmation always comes from the Project Lead, folded into the start-of-work approval when one person holds both roles (D59).

Read repository instructions (AGENTS.md, CLAUDE.md, `openspec/config.yaml`) first; they override this skill. Asking, writing and spec rules follow [the SA method](../project-lead/sa-method.md) at feature depth. `design.md` and `tasks.md` belong to the Implementer (D54); you may attach a task draft clearly marked as a draft.

## 0. Check the entry

- Multi-repo product: work from the root repo and run its sync command first (D61).
- Small work does not open a change: a fix that restores behaviour the spec already states, a dependency update, or missing tests. Write a self-contained ticket (goal, acceptance criteria, narrow scope) in the root repo's tracker and stop. A bug the spec never covered is a feature.
- The feature must be on the roadmap and chosen when the Project Lead confirmed it (D63). If not, stop and send the human to `project-lead`.
- If the feature's branch, change and ticket already exist, do not open new ones: follow **Revise an existing feature** below.

## 1. Open the branch, the change and the ticket

Ask the human to authorise pushing the branch and writing the ticket; without it, hand the commands and text to the human.

- First use in the repository: on an up-to-date default branch, run `openspec init --tools claude,codex`, then commit and push it before any feature branch exists.
- Pick a short English change id (`finalize-protocol`). In the root repo, `git fetch origin`, then create the branch and its worktree from the remote default branch: `git worktree add ../<root>-<id> -b feature/<id> origin/<default-branch>`. Record that base commit; every later step works in this worktree (D67).
- `openspec new change <id>`, commit, and push the branch.
- Create the ticket in the root repo's tracker (service repos only get PRs), or bring an existing one to this shape. Title: the feature name, no prefix; it says what someone can do once the feature is delivered (`loopctl：登記 run、記錄人工決策、查詢狀態與下一步`), not a topic (`人工決策與下一步`). If the roadmap name is only a topic, propose a concrete one and update the roadmap row when the human agrees. Label: `feature` (create it once per repository). Body, nothing else (D54, D67):

```markdown
**Milestone：** <milestone>　**狀態：** 準備中
**下一步：** <who> <does what>

## 目標
<one or two lines: after this, who can do what>

## Spec
- [change](<folder openspec/changes/<id>/ on branch feature/<id>; the root PR once it exists>)：範圍、不做、需求與驗收都以這裡為準
- 交接包：（交接時補上留言連結）
- spec 確認：（交接時補上：已確認 <commit>，或併入開工確認）

## 驗收
勾選＝驗收人已確認這一條；證據看驗收包與驗收紀錄的留言。
（交接時列出 AC）

## Blocked by
- #<n> <feature name>：<what releases it>；<owner>   （none: 無）
```

Scope, non-goals and acceptance text stay in the change. Records (handoff, start approval, acceptance) are ticket comments (D60). States and who sets them: 準備中 and 就緒 (you); 開發中 after the start approval (`spec-to-plan`) and 待驗收 after PR Pass (`to-pr`); 已接受, 開發中 after a rejection, and 已完成 (project-lead, which writes those records); `Blocked：<reason>` by whoever hits it. Whoever sets a state also updates 下一步.

Done when the branch is pushed, the change folder is on it, and the ticket links to it with state `準備中`.

## 2. Research

Read the feature's roadmap row, the requirement input it points to, the cross-feature constraints in the project intent, `openspec/specs/`, design documents and ADRs, and related tickets; record each source's path and version. Then research the code this feature touches with `research-codebase` (query `graphify-out/` first when it exists). Save the report under the repository's research location on the feature branch, separating facts, assumptions, and unknowns; commit it and note the commit. Commit research to one branch only: research that backs a project decision (`D<n>`) reaches the default branch with that decision's PR, and another branch that needs it merges the default branch after that PR merges; never cherry-pick it (D83).

Done when the next questions have evidence behind them.

## 3. Proposal and scope

Draft `proposal.md` first: Why, What Changes, a `不做` list, and a 「待決與依賴」 section (each item: whether it blocks design, owner). Ask about goal and scope before anything else; do not write requirements until the human agrees the scope. A new high-level boundary goes into the project's design documents or an ADR, referenced from the proposal.

Each decision has one home (D83):

- It revises an existing `D<n>`, affects more than this feature, or changes the process: a new `D<n>` in `docs/decisions.md`; the proposal only links to it.
- It affects only this feature: the proposal's 「待決與依賴」, marked decided with the human's words.
- A choice among high-level options: an ADR.
- The Implementer's own design choices: `design.md`, numbered `DD-<n>`.

Done when the human agreed goal, scope and non-scope and the proposal is committed.

## 4. Spec delta

Bring the requirements this feature delivers from the input into `specs/<capability>/spec.md` (ADDED or MODIFIED). Ask down the skeleton: flow, rules, exceptions, acceptance; write each answer in place as a requirement with ID-bearing scenarios. Check the cross-feature constraints this feature touches. Run `openspec validate <id>`, fix format errors, and commit.

Done when validation passes, every requirement has an ID and at least one scenario, the main flow and each exception have a scenario, and no open item would change scope, behaviour, or acceptance.

## 4b. Independent spec review

A model different from the spec's author reviews `proposal.md` and the spec delta in a fresh session, read-only (D52, D82), for example `claude -p --model claude-fable-5-1` with read-only settings, or `codex exec -s read-only`. Ask it to check:

- every SHALL of the input requirements this feature brings in is carried, deferred in the proposal, or changed by a cited decision;
- every scenario is observable and testable at a public entry point, with no vague verdict word left undefined;
- nothing contradicts the decisions or `openspec/specs/`; a MODIFIED requirement keeps the whole current text it replaces;
- new acceptance IDs collide with no existing ID;
- the main flow and each exception have a scenario;
- nothing belongs to a later feature or to the design.

Findings are blocking (they change scope, behaviour or acceptance, or leave a scenario unverifiable) or not. Fix them and re-review in the same reviewer session until clean, at most three rounds; a fix that needs a scope decision goes to the human first. Not clean after three rounds: show the open findings to the Project Lead, who decides how to proceed. Keep each round (prompt, result, and how each finding was handled) in `openspec/changes/<id>/reviews/`, commit, and push.

Done when the review is clean or the Project Lead decided on the open findings.

## 5. Confirm the spec

Show the one-page summary, naming the spec review result and what it changed. The Project Lead confirms the reviewed version; record it in a short section of `proposal.md`: who, when, their words, and the commit confirmed; commit and push. When one person holds both roles, record instead that the confirmation is folded into the start-of-work approval. This is not the start-of-work approval.

## 6. Hand off

1. Ask the Project Lead who approves the start of work (usually the Engineer) and who accepts the result: the Project Lead unless the requirement came from someone else, who then accepts (D62).
2. Assemble the handoff package: change id and file versions; the spec confirmation or the fold note; versions of the project intent, high-level design and roadmap it relies on; spec, acceptance IDs and design boundaries; for each affected repo its base branch, commit, and the PR to be opened (D61); dependencies with their version and state; open items with decision maker and next owner; the start approver and the acceptor.
3. Post the package as one ticket comment (D60). In the ticket body: link that comment on the 交接包 line; fill the spec confirmation line; list each acceptance ID under 驗收 as an unchecked checkbox followed by its scenario title copied from the spec (if a title drops a condition that changes the verdict, fix the title in the spec); set the state to `就緒（可設計）` and 下一步 to the Engineer checking the package.
4. The Engineer checks the package and either starts or returns specific questions; answer them by going back to step 3 or 4.

The feature loop continues on the same branch and worktree (design, tasks, code in the root; a branch of the same name in each affected service repo) with three skills in order, each ending at a stop: `spec-to-plan` (design and plan, stops at the start-of-work approval), `plan-to-code` (tasks with per-task review), `to-pr` (pull requests, whole-change review and CI, stops at 待驗收). The root PR is this branch; the ticket's Spec line then links it. Then one of:

- **Manual:** the Engineer starts `spec-to-plan` in the feature's worktree, and each next skill after the previous one stops.
- **Authorised:** only when the human explicitly authorised you for a named scope and the spec confirmation exists (or is folded), start `spec-to-plan` yourself. It stops at the start-of-work approval, which only the named human gives.

A feature that depends on another may be prepared now; its implementation starts only after the upstream is accepted and merged (D27).

## 7. Report what was opened

End by showing the human one short summary, in the chat, of what now exists:

- change id, branch, and the worktree path;
- the pushed commit, with links to the proposal and the spec delta at that commit;
- the ticket: link, state and 下一步;
- the handoff comment's link;
- acceptance IDs with their scenario titles;
- the spec confirmation: the confirmed commit, or the fold note;
- the start approver and the acceptor;
- open items and dependencies, each with who decides;
- the next step: after a manual hand-off, the prompt the Engineer pastes in the feature's worktree, ready to copy: `/spec-to-plan 準備〈change id〉的設計與計畫：讀交接包，寫 design.md 與 tasks.md，交另一個模型審到 clean，停在確認開工。`; when you started `spec-to-plan` yourself (authorised), where it stands and where it will stop instead.

Anything the summary cannot show (not pushed, no ticket, no confirmation yet) is said plainly, with what is missing.

## Revise an existing feature

Use this when the change already exists: a requirement changed while the feature was in the loop, the loop returned Blocked on scope, or the acceptor sent it back because the requirement changed.

1. Work in the feature's existing branch and worktree; update the default-branch base only if the Project Lead asks. Never open a second change or ticket.
2. Update the proposal and the spec delta (the `openspec-update-change` skill keeps them coherent when it is installed; leave `design.md` and `tasks.md` to the Implementer), run `openspec validate <id>`, commit, and name what changed. Review the changes as in step 4b.
3. The Project Lead confirms the new spec (or record the fold note); record the confirmed commit in `proposal.md`, then commit and push so the branch holds it.
4. Post a new handoff comment that carries the complete package of step 2 of the handoff at the new versions, lists what changed, names the pushed commit, and supersedes the earlier one; relink it from the ticket. Rebuild the ticket's 驗收 list from the new spec: add new IDs, remove deleted ones, update renamed titles, and untick every ID whose scenario changed.
5. A changed spec voids the start-of-work approval for the design and tasks it affects: set the state to `就緒（可設計）` and 下一步 to the Engineer, who revises the plan and gets a new start approval (D11).
6. End with the summary of step 7, adding what changed and which approvals it voided.

## Boundaries

- No design, final task plan, product code, reviews, or gate verdicts.
- No approval, merge, or close on the human's behalf.
- One authoritative copy: the spec lives in the change; the ticket links to it.
