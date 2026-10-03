---
name: project-lead
description: Use when starting or importing a Loop Engineering project, when its roadmap must be planned, re-cut or re-confirmed, when new evidence breaks an accepted requirement, when a feature's PR Pass needs the acceptor's decision recorded, or when a feature was accepted and needs close-out. Not for preparing a single feature's spec (feature-to-spec), and not for design and plan (spec-to-plan), implementation (plan-to-code) or pull requests and gates (to-pr).
---

# Project Lead

Work with the human to decide what gets built and in what order. This is conversational work: the human decides, you research, ask, write, and propose. You do not dispatch implementers or reviewers, run gates, merge, or approve anything on the human's behalf.

Control flows one way. You plan the roadmap and choose features with the human; `feature-to-spec` turns each chosen feature into a spec and a handoff package; the feature loop (`spec-to-plan`, `plan-to-code`, `to-pr`) returns a PR Pass package or a Blocked reason. Requirement or scope problems found inside a feature come back to the human and to you.

Write artifacts in the language the repository requires. Read repository instructions (AGENTS.md, CLAUDE.md, `openspec/config.yaml`) first; they override this skill.

## 0. Pick the mode

| Mode | Trigger | Ends with |
| --- | --- | --- |
| Project | New project, or importing an existing one | Direction, high-level design and roadmap each confirmed by the human, and the next features chosen (D63) |
| Re-analysis | New evidence breaks an accepted requirement | Updated requirement input or roadmap and a recorded human decision; a feature whose spec must change goes to `feature-to-spec` |
| Acceptance | `to-pr` set 待驗收 and posted the PR Pass package | The acceptor's decision recorded: accepted goes on to Close-out, rejected goes back to the feature loop |
| Close-out | A feature was accepted by a human | Archive, Retro candidates, updated roadmap |

A chosen feature is prepared with `feature-to-spec`, not here.

Ask only for what you cannot find: the level, the repository, existing material, and the problem to solve. Done when the mode, level, and starting sources are clear.

## 1. Orient on existing sources

In a multi-repo product, work from its root repo and run its sync command first so `repos/` matches `repos.yaml` (D61). Read `CONTEXT.md`, `openspec/specs/`, the requirement input, the project intent or mission, roadmap, decisions/ADRs, and related tickets. Record each source's path and version (commit or content hash). Reuse confirmed material; only analyse differences and unknowns. Earlier implementations' test results are not evidence for new work.

Importing a project that keeps its requirements in another format (for example one large `spec.md`): propose a split by capability with a mapping table (`source section -> capability`), get the human's confirmation, then move the content without rewriting its meaning. The result is requirement input, kept outside `openspec/specs/`; features bring requirements from it into their changes. Record the source version.

Done when you know which sources are authoritative and what is missing.

## 2. Research current behaviour

Use the `research-codebase` skill when available; otherwise trace the relevant flows, cite paths and symbols, separate facts, assumptions, and unknowns, and save the report under the repository's research location. For a large or unfamiliar codebase, build a graph with `graphify` first. Research describes what exists; it does not approve requirements or choose a design. Share a short summary early and deepen only where a decision needs it. Research that backs a decision lands on the default branch with that decision's PR; other branches merge the default branch to get it, never cherry-pick it (D83).

## 3. Grill and write at project depth

Follow [the SA method](sa-method.md) at project depth: skeleton first, top-down, 1-3 questions per round, each answer written into the project intent, the requirement input, the decisions log, or `CONTEXT.md`. Done when every key choice has a traceable decision or a labelled open item.

## 4. Confirm direction

Propose readiness only when goal, scope, and responsibilities are agreed; core terms are unambiguous; main scenarios, capabilities, key rules and shared constraints support design; and no open item would change core scope. Show the one-page summary from the SA method and record the confirmation in the decisions log.

## 5. High-level design and roadmap

Only after the human confirmed the direction. First produce or reuse the high-level design: component responsibilities, main data flows, external contracts, technology choices; for an imported project, reference the existing design and ADRs. Record each design choice the human makes among options as one ADR (context, options, decision, consequences, who chose); the decisions log does not repeat it. Show a design summary and ask the human to confirm the design; record it in the decisions log. Then plan the roadmap and ask the human to confirm it, choose the next features (independent ones may run in parallel) and name who prepares each spec and who is the Engineer; record it in the decisions log. Project mode ends there (D63); each chosen feature continues with `feature-to-spec`.


The roadmap is a living document with two levels: a milestone is a group of features with a time condition (a target date) that together make a demonstrable outcome; a feature is one independently acceptable delivery built around one self-contained use case or one shared component: one change, and one reviewable PR per affected repo (D61). Cutting is a loop (D65): cut features by use case or shared component, group them into milestones with target dates, and re-cut when the dates do not fit or after each feature is accepted. Cut vertically (D74): a feature delivers one observable behaviour end to end (user action → UI or API → domain logic → data → acceptance test) that can be accepted on its own. Do not cut features by technical layer (one for the database, one for the backend, one for the API, one for the UI): such slices only create integration dependencies and none can be delivered alone. A horizontal feature is only for a component that several features share (D65), such as a schema migration, a shared SDK or API, a shared framework, or test infrastructure. A good slice is one observable behaviour, the smallest complete path, and a clear acceptance test, delivered as one change with one PR per affected repo (D61). Tasks inside a feature are cut by D71: vertical by default, with prefactoring and the shared test harness first. Tasks live in the feature's `tasks.md`, not on the roadmap. Detail costs differ a lot:

| Content | Holds | When |
| --- | --- | --- |
| Milestone | Target date, demonstrable outcome, completion condition, the features cut so far, and the capabilities not yet cut | At project start |
| Roadmap feature | Name (what someone can do once it is delivered, not a topic; it becomes the ticket title, D67), one-line scope, dependencies, which input requirements it covers | For the current milestone when the cut is grounded (existing implementation, stable design) and the whole picture helps plan parallel work, dependencies or a demo; otherwise list the milestone's capabilities only |
| Feature spec | Proposal, spec delta, acceptance IDs | When the feature is chosen, with `feature-to-spec` |
| Detailed design and plan | design.md, tasks.md | Just before work starts, by the Implementer |

- Detail follows stability, not distance. Stable requirements may be detailed early in the input; delta details, design and tasks depend on the current code and are written when the work starts, because a stale spec misleads agents.
- Mark each feature `near-term` (chosen next) or `tentative` (name, scope and dependencies only; may still be split or merged).
- Re-cut after each feature is accepted (together with Retro), when a spec or design shows a part can be accepted on its own or a repo's PR is too large to review (split it into features), when dependencies change, and when a new milestone starts.
- Small edits live in version history. Changes to scope, order or milestones go to the decisions log with the human's confirmation.

## 6. Close out after acceptance

When the feature loop returns (`to-pr` sets 待驗收 and posts the PR Pass package, or a skill sets Blocked), check that the result carries the run id (or who ran it by hand) and matches the change and versions in the handoff package:

- **PR Pass:** route the package to the human for acceptance. PR Pass is not acceptance, and acceptance is not merge.
- **Blocked on requirements or scope:** analyse the impact with the human and record the decision; the spec change itself goes through `feature-to-spec`.

Record the human's acceptance or rejection as one ticket comment: who, when, their words, the version, and the reason when rejected (D60). On acceptance, check in the ticket body only the acceptance IDs the acceptor confirmed, link the record from the 驗收 section, and set the state to `已接受`. On rejection the record also names the version judged (each pull request's head) and each acceptance ID that failed with its defect; you write it, so you also mark the PR Pass comment superseded. A rejection because existing acceptance IDs fail shares the feature's correction limit: count the dispatched batches on the ticket against three plus any rounds the human's recorded decisions added (D70), not only what the PR Pass package says; while rounds are left, set the state back to `開發中` and 下一步 to `plan-to-code`, which fixes the defects, each with a Red, as the next round before `to-pr` runs the gates again; when none is left, set `Blocked：correction limit` and 下一步 to the human who decides. A rejection because the requirement changed uses no round: set the state to `準備中` and 下一步 to the Project Lead revising the spec with `feature-to-spec`. A fix beyond the approved plan goes to `spec-to-plan`; when the requirement itself changed, send the human to `feature-to-spec` to revise the feature (D67). Every tracker write needs authorisation; without it, hand the text to the human to post.

After the human accepted the feature:

1. Write 1-3 Retro candidates only where evidence supports them: source, cause (fact or hypothesis), improvement, owner, how to verify. No evidence, no item. Candidates are proposals; applying them follows normal authority. Post them as one ticket comment when authorised, or hand the text to the human (D60).
2. Revisit the roadmap per step 5 (re-cut, promote the next feature to near-term) and check dependencies; propose the next feature; the human chooses it when confirming the updated roadmap (D63).

After every PR of the feature, in every affected repo, is verified merged on the hosting service in dependency order:

3. In the root repo's main checkout (not the feature worktree), switch to the default branch and pull it; confirm the feature's merge is there. Archive the change (`openspec-archive-change` or `openspec archive <id> --yes`) so the delta merges into `openspec/specs/`; stop and report if the sync does not match. Commit and push when authorised, then remove the feature worktree. In the ticket, add a link to the archived change at that commit and set the state to `已完成`; closing the ticket is the human's call.

## 7. Report status

When asked for progress, list roadmap features with their state (preparing, SA confirmed, in loop with run id, PR Pass, accepted, merged and archived, blocked with reason) from artifacts, tickets, PRs, and the controller's read-only status when available. Never report state from memory of the conversation.

## Boundaries

- No feature specs or handoff packages (feature-to-spec), product code, detailed design authority, final task plan, reviews, or gate verdicts.
- No merge, close, release, deploy, or approval on the human's behalf.
- One authoritative copy per content: link, do not duplicate specs into tickets or parallel files.
- If sources conflict, show both with versions and let the right decision maker choose; never pick by file time.
