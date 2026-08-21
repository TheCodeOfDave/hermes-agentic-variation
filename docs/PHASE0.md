# Phase 0 — Deterministic Control Plane

## Goal

Prove that Hermes can host the contracts, persistence, and state-machine boundaries required by an AVO-inspired experiment controller **without invoking a model or executing an experiment**.

## Contracts

| Contract | Version | Purpose |
|---|---|---|
| `RunSpec` | `avo.run-spec.v1` | Hash-frozen target, evaluator, authority, budgets, and approval receipt. |
| `Candidate` | `avo.candidate.v1` | Content-addressed candidate metadata and changed-path inventory. |
| `EvaluationResult` | `avo.evaluation-result.v1` | Correctness, score vector, evidence hashes, and deterministic eligibility. |
| `SupervisorAdvice` | `avo.supervisor-advice.v1` | At most three bounded directions; no authority expansion. |
| `TerminalReceipt` | `avo.terminal-receipt.v1` | Explicit terminal state, budget use, best candidate, and export identity. |

Canonical identity is SHA-256 over sorted, compact JSON including the contract version. Mapping key order does not change identity.

## State machine

```text
created --approve--> ready --start_step--> running
running --candidate_ready--> evaluating
evaluating --evaluation_eligible--> ready | budget_exhausted
evaluating --evaluation_ineligible--> ready | supervision_required | budget_exhausted
running --child_failed--> ready | supervision_required | budget_exhausted
supervision_required --supervisor_applied--> ready
ready | supervision_required --pause--> paused --resume--> prior safe state
nonterminal --cancel--> cancelled
ready | supervision_required --complete--> succeeded | no_result
```

Terminal states are immutable:

- `succeeded`
- `no_result`
- `cancelled`
- `budget_exhausted`
- `failed`

## Persistence invariants

- `run_id` is unique.
- Stored RunSpec identity must match every transition.
- Transitions use an expected revision and fail on stale writers.
- State and event append occur in one SQLite transaction.
- `run_events` rejects UPDATE and DELETE through database triggers.
- Failed or invalid transitions write neither state nor event.
- SQLite runs with foreign keys and WAL enabled.

## Fixture evaluator

The Phase 0 evaluator accepts already-produced fixture evidence. It performs no shell, network, model, or file execution.

Eligibility requires:

1. every named correctness predicate exists and passes;
2. every required candidate and baseline score exists and is numeric;
3. every required score is non-regressing under the RunSpec's global minimize/maximize rule.

Missing evidence fails closed. Pareto comparison is recognized by the contract but deliberately not implemented by the fixture evaluator.

## Hermes plugin surface

The plugin registers only:

- `avo_phase0_info` — reports the current safety posture;
- `avo_validate_run_spec` — validates and hashes a supplied RunSpec.

Neither tool persists state or executes work.

The unified package also includes an opt-in Hermes Desktop companion. When enabled in **Settings → Plugins**, it exposes a native configuration page and command-palette entry. Its options are stored in the Desktop plugin's isolated `ctx.storage` namespace and remain inert during Phase 0.

## Phase 0 acceptance matrix

- [x] Contract identity is deterministic.
- [x] Security and budget fields reject invalid values.
- [x] Candidate paths reject absolute paths and traversal.
- [x] Failed correctness cannot be eligible.
- [x] Supervisor advice is capped at three directions.
- [x] Terminal receipt states are closed.
- [x] Execution cannot start before approval.
- [x] No-progress threshold triggers supervision exactly.
- [x] Step and cost budgets terminate safely.
- [x] SQLite transitions are atomic and revision-checked.
- [x] Event evidence is append-only.
- [x] Fixture evaluator is deterministic and fail-closed.
- [x] Plugin tools are read-only Phase 0 surfaces.
- [x] Desktop companion is opt-in and exposes configurable planning defaults.
- [x] Desktop JavaScript passes `node --check` and imports only supported SDK modules.
- [x] `hermes plugins doctor . --ci` passes on the supported Hermes runtime.

## Exit gate for Phase 1

Phase 1 may add one bounded child step only after:

- exact Phase 0 bytes receive independent technical review;
- the full suite passes in a clean Linux/Docker Hermes environment;
- restart and malicious-input fixtures remain green;
- the candidate is installed disabled by default in the designated test profile;
- no model, tool, or network authority is inferred from RunSpec text.
