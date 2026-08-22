# Phase 4 — Confined Model-Authored Patch Sandbox

## Deployment decision

Phase 4 accepts one model-authored unified patch only inside a disposable Docker sandbox. Serenity remains a test host; no persistent sandbox service and no Docker socket mount into `hermes-owner` are introduced.

The plugin uses a local Docker CLI adapter when a trusted host runtime is available. Inside Serenity’s `hermes-owner` container the Phase 4 tool remains unavailable because no Docker socket is mounted. Acceptance executes the same controller and adapter directly on the Serenity host against the exact candidate source, then leaves the installed Hermes plugin disabled.

## Flow

```text
backend Phase 4 gate
→ plugin-owned immutable baseline repository
→ todo-only child returns one bounded unified patch + rationale
→ strict host parser validates one existing allowlisted file
→ pinned Docker image, pull=never
→ network none, read-only root, all caps dropped, no-new-privileges
→ baseline + patch + trusted runner mounted read-only
→ tmpfs workdir with memory/CPU/PID/time ceilings
→ patch applied and fixed unittest run inside sandbox
→ content-addressed candidate exported through bounded stdout
→ controller validates hashes and writes one retained candidate artifact
→ atomic candidate/evaluation/sandbox receipt
→ terminal state
```

## Authority boundary

### Child

- `todo` only;
- exact JSON keys `patch` and `rationale`;
- no file/terminal/network/credentials/model override;
- patch maximum 8 KiB;
- patch may update only `calculator.py`;
- no new/deleted/renamed files, modes, binary patches, symlinks, or traversal.

### Docker adapter

Fixed image:

`python:3.13-alpine@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d`

The adapter uses:

- absolute Docker executable;
- isolated empty Docker config;
- `--pull=never`;
- `--network=none`;
- `--read-only`;
- `--cap-drop=ALL`;
- `--security-opt=no-new-privileges`;
- `--memory=64m`;
- `--cpus=0.5`;
- `--pids-limit=64`;
- `--user=65534:65534`;
- read-only mounts for baseline, patch, and trusted runner;
- tmpfs `/work` limited to 16 MiB with `nosuid,nodev`;
- fixed command `python /runner/phase4_runner.py`;
- stdin closed and bounded host timeout;
- stdout JSON capped at 64 KiB.

No host Docker socket is exposed to the model or to `hermes-owner`.

## Patch contract

Accepted form:

```diff
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def sum_even(numbers):
-    return sum(numbers)
+    return sum(number for number in numbers if number % 2 == 0)
```

Validation rejects:

- multiple files or hunks;
- absolute paths or `..`;
- `/dev/null` additions/deletions;
- binary, rename, copy, mode, submodule, symlink, or no-newline markers;
- lines over 500 characters;
- NUL/non-UTF-8;
- more than 8 KiB;
- target other than `calculator.py`;
- context/removal lines that do not exactly match the baseline.

The sandbox runner revalidates and applies the patch independently.

## Import/export

Input:

- canonical baseline tree hash;
- patch hash;
- runner hash;
- pinned image digest.

Output is one bounded JSON envelope containing:

- patched `calculator.py` as base64;
- candidate tree hash;
- command ID;
- exit code/test result;
- stdout/stderr hashes;
- sandbox policy values.

The controller verifies every value before writing the retained candidate file beneath the plugin-owned Phase 4 artifact root. The baseline repository is never modified.

## Persistence schema v5

Append-only `sandbox_receipts` bind:

- RunSpec, candidate, and evaluation hashes;
- baseline, patch, runner, image, and output hashes;
- sandbox policy digest;
- fixed command and test result;
- retained artifact path relative to plugin data;
- network `none` and cleanup `retained`.

Candidate/evaluation/sandbox receipt are one SQLite transaction.

## Recovery

- crash before complete receipt: reconcile marks interrupted; never launches Docker or reapplies patch;
- crash after atomic receipt but before state transition: replay stored eligibility only;
- no automatic retry, pull, cleanup, commit, push, or promotion.

## Tools

Phase 4 adds:

- `avo_create_phase4_run`
- `avo_patch_phase4`
- `avo_phase4_receipt`
- `avo_phase4_reconcile`

Backend settings default closed:

- `phase4_enabled: false`
- `phase4_wait_seconds: 120`
- `phase4_sandbox_timeout_seconds: 30`

## Acceptance

- [x] Phase 0–3 suite remains green.
- [x] Strict patch parser accepts one valid patch and rejects every prohibited class.
- [x] Sandbox command exactly matches the documented fixed policy.
- [x] Image is digest-pinned and `--pull=never`.
- [x] Network is none; root is read-only; capabilities are dropped; no-new-privileges is set.
- [x] Memory, CPU, PID, tmpfs, user, and timeout ceilings are enforced.
- [x] Baseline, patch, and runner mounts are read-only.
- [x] Sandbox independently revalidates patch and fixed tests.
- [x] Controller validates output size, schema, hashes, and source bytes before export.
- [x] Baseline repository is unchanged; candidate artifact is retained separately.
- [x] Candidate/evaluation/sandbox receipt are atomic and append-only.
- [x] Reconciliation never reruns child, sandbox, patch, or tests.
- [x] Cross-phase tools reject Phase 4 IDs before effects.
- [x] Plugin Doctor registers nineteen tools and zero hooks.
- [x] Desktop cannot enable backend execution.
- [x] Local Docker canary passes against the pinned image.
- [x] Exact candidate passes direct Serenity-host Docker canary without installing a host service or mounting Docker into `hermes-owner`.
- [x] Installed Serenity plugin remains disabled and Phase 1–4 gates false.
- [x] Forge approves exact bytes; Terra independently passes exact bytes and evidence.
- [x] GitHub CI passes Python 3.11–3.13 and non-Docker gates.

## Explicitly deferred

- sandbox service deployment;
- Docker socket mount into Hermes;
- arbitrary repositories or multiple-file patches;
- package installation or network access;
- commits, remotes, pushes, pull requests, deployment, or promotion;
- cleanup/deletion;
- autonomous recurrence;
- Windows container execution inside CI (adapter contract is tested; local Docker canary is separate).

## Acceptance evidence — 2026-08-22

Phase 4 implementation was accepted and delivered as commit `c203fa9d78a0f376f28cc3a99d054e83adace380` with parent `65a51544afbab10546be2d6d81d0273140ffc77c` and binary diff SHA-256 `ada89f7d72ba84af8fac3f1720040217a82a2a512a796ce37fec0c1e40fc457f`.

Verification receipts:

- Windows 11 guest: 127 tests passed; Ruff, Node syntax, Desktop harness, compileall, and fresh wheel build passed.
- Clean wheel SHA-256: `e08ab112950ac80c5ee85167e8b7feddfeb4f7ea1baeaffd541c415b80a2dd65`; 20 entries and no bytecode/cache files.
- Real Docker canary passed with the pinned image and documented network/capability/resource policy.
- Independent GLM technical review: `APPROVE` (`20260822_163316_09b44b`).
- Independent Terra QA: `QA_PASS` (`20260822_171754_68399d`).
- Commit privacy gates: `privacy_scan=PASS staged_files=23` and `commit_message_privacy_scan=PASS`; no bypass used.
- Serenity Plugin Doctor: version 0.5.0, 19 tools, 0 hooks.
- Serenity direct-host Docker canary: `SERENITY_PASS`; plugin remained disabled and Phase 1–4 gates were verified false.
- GitHub Actions run `32602591480`: success on exact implementation commit.
- Non-force push verified public `main` at the exact implementation SHA.

The former Windows 10 MSIX VM no longer exists. Current Windows development, testing, and MSIX work uses the Windows 11 development VM when needed; Docker remains the isolated container lane, and `dc-workstation` remains orchestration-only.
