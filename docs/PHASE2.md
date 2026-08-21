# Phase 2 — Persistent Continuation, Reconciliation, and One Supervisor

## Decision

Phase 2 remains a bounded sequential controller, not a multi-agent graph and not an autonomous loop. The real-edge test finds no independent branches: each action consumes the prior persisted state. The executable path is therefore:

```text
approved Phase 2 RunSpec
→ explicit bounded variation step
→ deterministic evaluation
→ compact continuation snapshot
→ ready | supervision_required | terminal
→ optional deterministic reconciliation after interruption
→ durable `supervising` state → at most one restricted supervisor advice call
→ ready or explicit terminal state
```

No scheduler or recurring worker is introduced. Every advance requires a direct tool call.

## Loop contract

Loop name: Agentic Variation Phase 2 continuation

Purpose: Preserve enough scored lineage to continue safely across Hermes sessions, reconcile interrupted steps from durable evidence, and allow one bounded supervisor redirection after deterministic stagnation.

Trigger: An explicit `avo_step`, `avo_reconcile`, or `avo_supervise` tool call while both the plugin and backend Phase 2 gate are enabled.

Inputs/sources:

- immutable plugin-owned RunSpec;
- authoritative SQLite run state and append-only events;
- content-addressed candidates and deterministic evaluations;
- latest compact continuation snapshot;
- stored supervisor advice, if any.

State/memory:

1. immutable candidate/evaluation lineage;
2. append-only run event journal;
3. one revisable, revisioned continuation snapshot per run;
4. append-only supervisor advice artifacts.

Safe actions:

- derive and persist a bounded continuation snapshot;
- reconcile `running`/`evaluating` from durable evidence;
- launch one `todo`-only variation or supervisor child;
- record strict typed text as untrusted evidence;
- apply deterministic state transitions.

Draft-only actions: Supervisor search directions stored as advice. They cannot change target, evaluator, tools, network policy, budgets, or approval.

Approval-required actions: Enabling the backend Phase 2 gate and invoking executable tools.

Never automate:

- schedules or recurrence;
- file/repository mutation;
- terminal commands in children;
- network access;
- provider/model overrides;
- credentials;
- push, deploy, publish, messaging, purchasing, or deletion.

Stopping rules:

- RunSpec step/cost/wall bounds reached;
- successful terminal candidate on the final step;
- second supervisor request after the single allowance;
- malformed supervisor output;
- evidence conflict or unsupported state;
- plugin/gate disabled.

Receipt/log: SQLite state, events, candidates, evaluations, continuation snapshots, supervisor advice, terminal state, and acceptance evidence.

Failure mode: Missing child process is never inferred successful. Reconciliation either completes an evaluation from durable evidence or records an interrupted/no-progress attempt. Ambiguous evidence fails closed.

Manual fallback: Read status/memory/lineage, then cancel or leave disabled. No database surgery is part of the tool surface.

## Typed contracts

### ContinuationMemory `avo.continuation-memory.v1`

- `run_spec_hash`: immutable binding;
- `memory_revision`: positive monotonically increasing integer;
- `run_status` and `state_revision`;
- `best_candidate_hash`;
- bounded `recent_candidate_hashes` (maximum 5);
- bounded `recent_evaluation_hashes` (maximum 5);
- bounded `recent_failure_signatures` (maximum 5);
- bounded `tried_hypotheses` (maximum 5, each maximum 300 characters);
- `supervisor_advice_hash` when present.

Identity is canonical SHA-256. Raw model transcripts are referenced by result hash, not copied into memory.

### SupervisorAdvice

Existing `avo.supervisor-advice.v1` remains authoritative:

- exact RunSpec hash;
- stagnation-evidence hash;
- one to three bounded directions;
- bounded prohibited repeats.

The supervisor cannot mutate the RunSpec and its output is never executed.

## Persistence schema v3

- `continuation_memory(run_id PRIMARY KEY, memory_revision, memory_hash, memory_json)` — revisable with compare-and-swap revision.
- `supervisor_advice(advice_hash PRIMARY KEY, run_id, advice_json)` — append-only identity rows.
- Existing runs, events, candidates, and evaluations remain unchanged.

## Reconciliation rules

### `running`

- If no candidate/evaluation pair is durably present for the current attempt, append interruption evidence and apply `interrupt`, counting one no-progress attempt.
- If a candidate/evaluation pair exists, advance to `evaluating`, then apply the persisted deterministic eligibility result.

### `evaluating`

- If exactly one latest evaluation exists, apply its persisted eligibility result.
- If evidence is missing or conflicting, apply `evaluation_missing`, counting one no-progress attempt.

### Other states

Return `noop`; never invent work.

### `supervising`

- If one complete advice artifact exists, apply it and return to `ready`.
- If advice is absent after process loss, record `SUPERVISOR_MISSING` and terminate fail-closed.
- The transition into `supervising` occurs before child launch, so optimistic revision checks prevent two supervisors from launching for one run.

All reconciliation uses optimistic state revision checks. Missing process-local child handles have no authority.

## Supervisor rules

Trigger: only `supervision_required` caused by deterministic no-progress.

Budget: one advice artifact per run.

Child authority:

- role `leaf`;
- toolset `todo` only;
- no model override;
- no working directory;
- bounded wait;
- fixed plugin-authored goal and context packet.

Output:

```json
{
  "directions": ["one to three bounded directions"],
  "prohibited_repeats": ["zero to three bounded labels"]
}
```

Exact keys only. Unknown, empty, oversized, or malformed output terminates as `no_result` or returns fail-closed without resetting stagnation. A second supervisor request deterministically completes the run rather than extending it.

## Tools

Phase 2 adds:

- `avo_create_phase2_run`
- `avo_memory`
- `avo_reconcile`
- `avo_supervise`

Existing Phase 1 tools remain supported. Phase 2 uses backend settings `phase2_enabled` and `phase2_wait_seconds`, both independent of Desktop storage and defaulting to false/120.

`avo_memory` is read-only. It reports `stale=true` when its snapshot revision trails the authoritative run state; only explicit step, reconcile, supervise, cancel, or create operations refresh the persisted snapshot.

## Acceptance

- [x] Phase 1 suite remains green.
- [x] Schema migrates v2→v3 without changing prior rows.
- [x] Continuation memory is bounded, canonical, revisioned, and restart-readable.
- [x] Successful and failed steps refresh memory.
- [x] Running interruption reconciles to no-progress without inferring success.
- [x] Persisted candidate/evaluation evidence reconciles deterministically.
- [x] Mixed lineages containing prior no-evidence failures still replay the current durable evaluation exactly.
- [x] Concurrent reconciliation loses via optimistic revision conflict.
- [x] Supervisor is unavailable outside `supervision_required`.
- [x] Supervisor receives only `todo` and no authority fields.
- [x] Malformed supervisor output fails closed.
- [x] Exactly one supervisor advice artifact is allowed.
- [x] Supervisor launch intent persists before the child starts, and abandoned supervision reconciles fail-closed.
- [x] Second supervision request terminates rather than extending the run.
- [x] Plugin Doctor registers exactly eleven tools and zero hooks.
- [x] Desktop remains unable to enable backend execution.
- [x] Local and Serenity suites, Ruff, build, Node syntax/harness, and Plugin Doctor pass.
- [x] One live Serenity stagnation→supervisor→manual-step sequence is accepted and final plugin state is disabled.
- [x] Forge approves exact bytes; Terra independently passes exact bytes and live evidence.
- [x] GitHub CI passes Python 3.11–3.13 and Desktop gates.

## Acceptance receipt — 2026-08-21

- Accepted implementation commit: `906242c38ed6f2781fae5321ad46117639a554a9`
- Parent: `26a29f2228d2b1fa0b348548c24a4dd566ddeafd`
- Implementation diff SHA-256: `a8d7cdd6b440e35cfde82882ceb07f5bf9043a4986105d7fa03150bf19f07afe`
- Candidate archive SHA-256: `6ec54711ca88297f72ce283c83bc10a8d18661a3afe380752f17cd147d1a3654`
- Local and Serenity: 75 tests passed; Ruff, wheel build, Node syntax, Desktop VM harness, and Plugin Doctor passed; Plugin Doctor registered eleven tools and zero hooks.
- Forge/GLM: `APPROVE` on exact corrected bytes after mixed-lineage reconciliation review.
- Verifier/Terra: `PASS` on exact commit, installed-source comparison, and durable Serenity evidence.
- Serenity: Hermes v0.20.5 upstream `fd3a783a`; plugin 0.3.0 installed and left disabled.
- Live run: `phase2-5cfc671d8168b1fa`; first candidate `memoized_lookup` scored `5.0` and became best; strict-equal second candidate triggered `supervision_required`; exactly one supervisor advice artifact applied; third explicit step terminated `budget_exhausted` while preserving the best candidate.
- Durable evidence: schema 3; state revision 12; memory revision 5 bound to state revision 12; three candidates; three evaluations; one supervisor advice; each child and supervisor recorded one API call.
- Final backend state: `phase1_enabled=false`, `phase2_enabled=false`, plugin disabled, plugin toolset absent from CLI, API healthy.
- GitHub Actions: https://github.com/TheCodeOfDave/hermes-agentic-variation/actions/runs/32517420859 — PASS across Python 3.11–3.13, Ruff, and Desktop gates.
- Known upstream residual: CLI emitted an early unknown-toolset warning and exited `134` during Honcho teardown after returning the successful final result; authoritative SQLite evidence and final safe state were intact.

## Explicitly deferred

- autonomous scheduling or recurrence;
- repository/file/terminal/network authority;
- real artifact mutation;
- more than one supervisor intervention;
- cross-host workers or leases;
- true provider-dollar cost accounting when the public lifecycle exposes no exact cost;
- live Desktop rendering on dc-workstation.
