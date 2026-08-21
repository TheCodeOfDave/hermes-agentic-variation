# Hermes Agentic Variation

An **AVO-inspired** long-horizon experiment controller for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

> [!IMPORTANT]
> This project is independent community work. It is not NVIDIA AVO, is not affiliated with NVIDIA, and does not reproduce NVIDIA's unreleased internal implementation.

## Current status: Phase 2

Phase 2 adds persistent compact continuation memory, deterministic interrupted-run reconciliation, and at most one backend-gated supervisor advice call. Every advance remains an explicit tool call. Children receive only the in-memory `todo` toolset and have no file, command, repository, credential, or network authority.

Implemented now:

- immutable, versioned contracts for run specifications, candidates, evaluations, supervisor advice, and terminal receipts;
- stable canonical SHA-256 identities;
- a deterministic run state machine with explicit terminal states and bounded stagnation handling;
- a SQLite run ledger with optimistic concurrency and append-only transition evidence;
- a model-free fixture evaluator that fails closed on missing correctness or score evidence;
- eleven Hermes tools:
  - `avo_phase0_info`
  - `avo_validate_run_spec`
  - `avo_create_run`
  - `avo_step`
  - `avo_status`
  - `avo_cancel`
  - `avo_lineage`
  - `avo_create_phase2_run`
  - `avo_memory`
  - `avo_reconcile`
  - `avo_supervise`
- an opt-in Hermes Desktop companion with an **Agentic Variation** configuration page;
- configurable planning defaults for step, time, cost, stagnation, network, toolset, and evaluator fields, stored in the Desktop plugin's isolated local storage.

Phase 2 remains deliberately narrow:

- at most three explicitly requested variation steps;
- one supervisor advice call after deterministic stagnation;
- execution disabled by default through independent backend Phase 1 and Phase 2 gates;
- versioned compact continuation memory and additive SQLite schema v3;
- deterministic reconciliation from persisted evidence rather than process-local handles;
- no child file or command tools;
- command execution;
- repository mutation;
- experiment scheduling;
- network access;
- candidate promotion, publication, or deployment;
- autonomous schedules, recurrence, or multiple supervisor interventions.

That absence is deliberate. First make the control plane boring and correct. Then attach an agent.

## Architecture

```text
Approved immutable RunSpec
  -> explicit todo-only child choice
  -> deterministic evaluator
  -> append-only evidence + compact continuation memory
  -> ready | supervision_required | terminal
  -> optional one todo-only supervisor advice
  -> explicit next step or stop
```

The evaluator—not a model—owns candidate eligibility.

See [`docs/PHASE0.md`](docs/PHASE0.md), [`docs/PHASE1.md`](docs/PHASE1.md), and [`docs/PHASE2.md`](docs/PHASE2.md).

## Development

Requirements: Python 3.11–3.13.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check .
hermes plugins doctor . --ci
```

## Testing in Hermes

Do not install an unreviewed checkout into a daily-driver profile. Validate the directory first:

```bash
hermes plugins doctor /path/to/hermes-agentic-variation --ci
```

A native plugin install is opt-in and should remain disabled until its exact reviewed commit is selected for a test profile.

### Hermes Desktop

This repository is a unified Hermes package: the native Python plugin lives at the root and the Desktop companion lives at `desktop/plugin.js`. After installation, the Desktop half inventories in **Settings → Plugins** as **Agentic Variation** and remains off until enabled. Enabling it adds:

- an **Agentic Variation** sidebar entry;
- a configuration page at `/agentic-variation`;
- an **Agentic Variation: configure** command in the command palette.

Desktop options remain inert planning defaults. Executable gates are backend-owned in `plugins.entries.agentic-variation.settings` and cannot be enabled from Desktop.

## Research basis

- NVIDIA, [AVO: Agentic Variation Operators for Autonomous Evolutionary Search](https://arxiv.org/abs/2603.24517)
- NVIDIA, [AVO reaches 100% on the public ARC-AGI-3 set](https://developer.nvidia.com/blog/nvidia-avo-reaches-100-on-arc-agi-3-demonstrating-a-frontier-level-general-purpose-architecture-for-long-horizon-autonomous-agents/)
- Hermes Agent, [Build a Plugin](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
- Hermes Agent, [Public Subagent Lifecycle API](https://hermes-agent.nousresearch.com/docs/developer-guide/subagent-lifecycle-api)

## License

MIT
