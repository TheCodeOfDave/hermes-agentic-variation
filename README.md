# Hermes Agentic Variation

An **AVO-inspired** long-horizon experiment controller for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

> [!IMPORTANT]
> This project is independent community work. It is not NVIDIA AVO, is not affiliated with NVIDIA, and does not reproduce NVIDIA's unreleased internal implementation.

## Current status: Variation Cycles

The current Variation Cycle accepts one bounded model-authored, two-or-three-artifact proposal and evaluates it through separate apply and evaluation sandboxes. The child remains `todo`-only. Both sandboxes use a digest-pinned image with no network, read-only roots and mounts, dropped capabilities, no-new-privileges, and fixed CPU, memory, PID, tmpfs, time, and output ceilings.

Implemented now:

- immutable, versioned contracts for run specifications, candidates, evaluations, supervisor advice, and terminal receipts;
- stable canonical SHA-256 identities;
- a deterministic run state machine with explicit terminal states and bounded stagnation handling;
- a SQLite run ledger with optimistic concurrency and append-only transition evidence;
- a model-free fixture evaluator that fails closed on missing correctness or score evidence;
- twenty-three Hermes tools:
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
  - `avo_create_phase3_run`
  - `avo_mutate_phase3`
  - `avo_phase3_receipt`
  - `avo_phase3_reconcile`
  - `avo_create_phase4_run`
  - `avo_patch_phase4`
  - `avo_phase4_receipt`
  - `avo_phase4_reconcile`
  - `avo_create_phase5_run`
  - `avo_patchset_phase5`
  - `avo_phase5_receipt`
  - `avo_phase5_reconcile`
- an opt-in Hermes Desktop companion with an **Agentic Variation** configuration page;
- configurable planning defaults for step, time, cost, stagnation, network, toolset, and evaluator fields, stored in the Desktop plugin's isolated local storage.

Variation Cycles remain deliberately narrow:

- one explicitly requested generation attempt;
- one fixed, plugin-owned source fixture and immutable evaluation corpus;
- one todo-only child that returns proposal data rather than touching files;
- two or three allowlisted source artifacts changed atomically;
- no additions, deletions, renames, binary patches, package installs, or network;
- no child file, terminal, Git, Docker, credential, or test authority;
- no Docker socket exposure;
- no commit, remote, push, promotion, publication, deployment, cleanup, retry, scheduling, or recurrence;
- deterministic recovery from persisted evidence without rerunning effects.

That absence is deliberate. First make the control plane boring and correct. Then attach an agent.

## Architecture

```text
Approved immutable Cycle Specification
  -> plugin-owned immutable baseline
  -> todo-only child returns one strict Variation Proposal
  -> host validator accepts two or three allowlisted artifacts
  -> pinned networkless apply sandbox treats patches as data
  -> separate immutable evaluator executes the candidate
  -> content-addressed Variation Candidate exported separately
  -> append-only Variation Receipt and terminal state
```

The evaluator—not a model—owns candidate eligibility.

Implementation-generation notes remain under `docs/`; operator-facing surfaces use Variation Cycle terminology rather than exposing internal generation numbers.

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
