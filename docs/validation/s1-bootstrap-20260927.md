# S1 bootstrap verification

S1 is implemented by the authorized Opus session and coordinated manually under D39/D40. This is evidence for building the controller, not a claim that the future OpenCode adapter or end-to-end feature harness has already run.

- Feature issue: https://github.com/yschiang/orca-delivery/issues/1
- Approved feature baseline: `359ffcf6b439c054e6d5e61e2e80fc2e37944e6b`.
- Stopped implementation checkpoint: `384115884979cc3ef64f0990b82595442caf4a52`.
- Implementation attempts: `s1-impl-01`, `s1-impl-02`, `s1-impl-03`, each in a separate clone with retained commit history and immutable evidence. Earlier incomplete checkpoints were not accepted as gate passes.
- Worker regression at the implementation checkpoint: 227 passed, one Linux-only strace test skipped locally; macOS OS suite: six passed. Lint, type check and build succeeded. Coordinator current-head verification and fresh CI follow the evidence archive commit.
- Historical checkpoint CI: [run 36297940155](https://github.com/yschiang/orca-delivery/actions/runs/36297940155), head `f9fd941d0e9d3d41ea10bc04bc50cd9e6bee69f0`: Linux, macOS and required `test` succeeded. This is historical evidence, not a result for a later head.

## Evidence

[Historical evidence bundle](evidence/s1-bootstrap-20260927.tar.gz) and [checksum](evidence/s1-bootstrap-20260927.json) preserve 547 files, including original Red/Green output, committed snapshots, assignments, producer results, independent Red replays and CI JUnit. `MANIFEST.json` maps each original absolute path to its archive member and digest. Extract to a scratch directory; no credentials or execution environment are required to inspect the evidence.

The coordinator verified 102 evidence records against original stdout/stderr hashes, producer digests, clean committed trees and ancestor relationships. Red replays are additional verification; they do not replace historical test-first evidence. Earlier unsuccessful infrastructure probes and rejected early completion claims remain in the archive with their resolution.

All attempts use the approved Opus implementation session. Native transcript metadata reports `claude-opus-5-5`; the proxy's upstream model is not independently attested. The independent Reviewer uses a separate native Codex session with a verified restricted permission profile. Its final review will be published on the PR and summarized on issue #1, with exact reviewed head/base and input digests.

The attempt03 result has one stale summary note saying CLI `abandon_run` is not wired. Later commit `7a5c8c7` implements it. The coordinator preserved that result unchanged and recorded the discrepancy; review must inspect code and evidence, not trust the summary.

## Current limitations and completion boundary

- S1 verification covers the core through fake runtime/GitHub adapters and real git, plus native macOS OS probes. Real runtime/GitHub adapters are S2; orchestrate and real feature E2E are S3.
- GitHub returns HTTP403 for branch protection and rulesets on this private repo, asking for a plan upgrade. The controller still treats unreadable required-check rules as unknown. A bootstrap-only explicit-check policy was proposed to the user and remains pending; no exception or PR Pass is claimed here.
- Final gate conclusions must use the latest PR head. Review findings, fixes and CI updates are recorded on the PR and linked from the originating issue. No merge, issue closure, release or deployment is authorized by these results.
