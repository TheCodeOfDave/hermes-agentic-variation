# Hermes Agentic Variation

An **AVO-inspired** long-horizon experiment controller for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

> [!IMPORTANT]
> This project is independent community work. It is not NVIDIA AVO, is not affiliated with NVIDIA, and does not reproduce NVIDIA's unreleased internal implementation.

## Current status: Phase 1

Phase 1 adds exactly one backend-gated Hermes child step against a built-in reasoning fixture. The child receives only the in-memory `todo` toolset. It has no file, command, repository, credential, or network authority.

Implemented now:

- immutable, versioned contracts for run specifications, candidates, evaluations, supervisor advice, and terminal receipts;
- stable canonical SHA-256 identities;
- a deterministic run state machine with explicit terminal states and bounded stagnation handling;
- a SQLite run ledger with optimistic concurrency and append-only transition evidence;
- a model-free fixture evaluator that fails closed on missing correctness or score evidence;
- seven Hermes tools:
  - `avo_phase0_info`
  - `avo_validate_run_spec`
  - `avo_create_run`
  - `avo_step`
  - `avo_status`
  - `avo_cancel`
  - `avo_lineage`
- an opt-in Hermes Desktop companion with an **Agentic Variation** configuration page;
- configurable planning defaults for step, time, cost, stagnation, network, toolset, and evaluator fields, stored in the Desktop plugin's isolated local storage.

Phase 1 remains deliberately narrow:

- one child and one candidate only;
- execution disabled by default through backend `phase1_enabled: false`;
- no child file or command tools;
- command execution;
- repository mutation;
- experiment scheduling;
- network access;
- candidate promotion, publication, or deployment;
- persistent autonomous loops or supervisor intervention.

That absence is deliberate. First make the control plane boring and correct. Then attach an agent.

## Architecture

```text
Approved immutable RunSpec
  -> one no-file/no-command child choice
  -> deterministic evaluator
  -> append-only evidence receipt
  -> succeeded candidate or explicit no-result terminal state
  -> stop
```

The evaluator—not a model—owns candidate eligibility.

See [`docs/PHASE0.md`](docs/PHASE0.md) for the foundation and [`docs/PHASE1.md`](docs/PHASE1.md) for the bounded child contract.

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

Desktop options remain inert planning defaults. The executable Phase 1 gate is backend-owned in `plugins.entries.agentic-variation.settings.phase1_enabled` and cannot be enabled from Desktop.

## Research basis

- NVIDIA, [AVO: Agentic Variation Operators for Autonomous Evolutionary Search](https://arxiv.org/abs/2603.24517)
- NVIDIA, [AVO reaches 100% on the public ARC-AGI-3 set](https://developer.nvidia.com/blog/nvidia-avo-reaches-100-on-arc-agi-3-demonstrating-a-frontier-level-general-purpose-architecture-for-long-horizon-autonomous-agents/)
- Hermes Agent, [Build a Plugin](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins)
- Hermes Agent, [Public Subagent Lifecycle API](https://hermes-agent.nousresearch.com/docs/developer-guide/subagent-lifecycle-api)

## License

MIT
