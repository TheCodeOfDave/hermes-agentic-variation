# Phase 1 — One Bounded Child Step

## Goal

Exercise Hermes' public subagent lifecycle once without granting the child filesystem, command, repository, credential, or network authority.

Phase 1 is a control-path canary, not autonomous software engineering.

## Authority boundary

- Backend setting `phase1_enabled` defaults to `false` and is the only execution gate.
- Hermes Desktop cannot enable execution; its settings remain presentation-owned planning defaults.
- The plugin owns the target: `plugin://agentic-variation/phase1-fixture`.
- The RunSpec cannot choose a URL, filesystem path, model, toolset, evaluator, or budget.
- The child receives only the `todo` toolset, preventing the public lifecycle API from inheriting the parent's broad tool surface.
- The child returns text only. It never edits a candidate artifact directly.

## Fixed fixture

The child chooses one closed strategy:

| Strategy | Deterministic operations | Correctness |
|---|---:|---|
| `baseline` | 10 | pass |
| `single_pass` | 7 | pass |
| `memoized_lookup` | 5 | pass |

The required child response is one JSON object:

```json
{"strategy":"memoized_lookup","rationale":"short explanation"}
```

Unknown strategies, malformed JSON, extra keys, missing rationale, timeout, cancellation, or child failure produce no candidate and fail closed.

## Tool flow

1. `avo_create_run`
   - requires a bounded objective and explicit approval reference;
   - constructs a plugin-owned one-step RunSpec;
   - persists it and moves `created → ready`.
2. `avo_step`
   - moves `ready → running`;
   - launches one leaf child using the public lifecycle API;
   - waits for a bounded backend-configured period;
   - records child terminal state, result hash, and API-call count as append-only evidence;
   - converts synchronous lifecycle-launch errors into a terminal no-result state;
   - parses a closed JSON payload;
   - creates one content-addressed Candidate;
   - runs the model-free evaluator;
   - persists candidate and evaluation evidence;
   - moves to `succeeded` or an explicit no-result/budget terminal state;
   - stops.
3. `avo_status` and `avo_lineage` are read-only.
4. `avo_cancel` closes a run before the child step begins. In-flight cross-process cancellation is intentionally not claimed in Phase 1.

## Numeric hardening

Phase 1 closes Phase 0 review findings:

- Boolean values are rejected in numeric fields and scores.
- Every direct numeric value must be finite.
- Accumulated cost must remain finite after addition.
- SQLite JSON serialization uses `allow_nan=False`.
- A successful candidate on the final permitted step terminates as `succeeded`.

## Persistence

Schema version 2 adds:

- `candidates(candidate_hash, run_id, candidate_json)`
- `evaluations(evaluation_hash, run_id, candidate_hash, evaluation_json)`

The existing run state and append-only event ledger remain authoritative for transitions. Candidate and evaluation identities bind the exact child output-derived artifact and deterministic evidence.

## Desktop contract

The unified package remains opt-in. When its Desktop half is enabled, it renders the configuration route, sidebar item, and command-palette action. A Node VM harness now evaluates the actual ESM module against synthetic Hermes SDK modules and verifies registration plus storage reads.

Desktop settings cannot enable `phase1_enabled`. This prevents renderer-local preferences from granting backend execution authority.

## Phase 1 acceptance matrix

- [x] Phase 0 suite remains green.
- [x] Boolean and accumulated-cost regression tests pass.
- [x] Storage schema upgrades to version 2.
- [x] Plugin Doctor registers exactly seven tools and zero hooks.
- [x] Desktop syntax and behavioral harness pass.
- [x] Plugin remains disabled by default.
- [x] With backend Phase 1 gate off, run creation fails closed.
- [x] On the acceptance host, one approved Docker run launches exactly one child with only `todo`.
- [x] Live child result is deterministically evaluated and terminal.
- [x] Malformed and unlisted child outputs produce no candidate.
- [x] Lifecycle launch failure closes the run instead of stranding `running`.
- [x] Child API-call count is preserved in the evidence ledger.
- [x] Final acceptance-host plugin state is disabled.
- [x] Forge review approves exact bytes.
- [x] Terra QA passes exact bytes and Docker evidence.
- [x] GitHub CI passes Python 3.11–3.13, Ruff, and both Desktop gates.

## Acceptance receipt — 2026-08-21

- Accepted implementation commit: `4bc6554512ad0beb293adb4a435417f02919c831`
- Parent: `d1bd4c61289cbf6e91a469743f281184df7e6e6a`
- Implementation diff SHA-256: `5570f59ff185b907f873e011a3e047bf898ba7aae9a3947ca210c53f75b8560b`
- Local and acceptance-host suites: 51 tests passed; Ruff, Node syntax, Desktop VM harness, and Plugin Doctor passed.
- Forge/GLM review: `APPROVE` on exact bytes.
- Verifier/Terra acceptance: `PASS` on exact commit and acceptance-host evidence.
- Acceptance host: plugin 0.2.0 installed and left disabled.
- Live canary: one child; `memoized_lookup`; operations `5.0`; status `succeeded`; one candidate; one eligible evaluation; one child API call.
- Final backend state: `phase1_enabled=false`; plugin disabled; plugin toolset removed from CLI.
- GitHub Actions run: https://github.com/TheCodeOfDave/hermes-agentic-variation/actions/runs/32508644762 — PASS on Python 3.11, 3.12, and 3.13.


## Explicitly deferred

- File or repository editing
- Terminal execution by a child
- Network access
- Model/provider override
- In-flight restart reconnection
- Multi-step loops
- Persistent memory reduction
- Supervisor intervention
- Scheduling
- Candidate promotion, commit, push, deployment, or external effects
