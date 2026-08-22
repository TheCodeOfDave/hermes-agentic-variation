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

- [ ] Phase 0–3 suite remains green.
- [ ] Strict patch parser accepts one valid patch and rejects every prohibited class.
- [ ] Sandbox command exactly matches the documented fixed policy.
- [ ] Image is digest-pinned and `--pull=never`.
- [ ] Network is none; root is read-only; capabilities are dropped; no-new-privileges is set.
- [ ] Memory, CPU, PID, tmpfs, user, and timeout ceilings are enforced.
- [ ] Baseline, patch, and runner mounts are read-only.
- [ ] Sandbox independently revalidates patch and fixed tests.
- [ ] Controller validates output size, schema, hashes, and source bytes before export.
- [ ] Baseline repository is unchanged; candidate artifact is retained separately.
- [ ] Candidate/evaluation/sandbox receipt are atomic and append-only.
- [ ] Reconciliation never reruns child, sandbox, patch, or tests.
- [ ] Cross-phase tools reject Phase 4 IDs before effects.
- [ ] Plugin Doctor registers nineteen tools and zero hooks.
- [ ] Desktop cannot enable backend execution.
- [ ] Local Docker canary passes against the pinned image.
- [ ] Exact candidate passes direct Serenity-host Docker canary without installing a host service or mounting Docker into `hermes-owner`.
- [ ] Installed Serenity plugin remains disabled and Phase 1–4 gates false.
- [ ] Forge approves exact bytes; Terra independently passes exact bytes and evidence.
- [ ] GitHub CI passes Python 3.11–3.13 and non-Docker gates.

## Explicitly deferred

- sandbox service deployment;
- Docker socket mount into Hermes;
- arbitrary repositories or multiple-file patches;
- package installation or network access;
- commits, remotes, pushes, pull requests, deployment, or promotion;
- cleanup/deletion;
- autonomous recurrence;
- Windows container execution inside CI (adapter contract is tested; local Docker canary is separate).
