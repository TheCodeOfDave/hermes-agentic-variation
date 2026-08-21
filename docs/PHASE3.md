# Phase 3 — Disposable Repository Mutation Canary

## Decision and API constraint

Phase 3 proves one real mutation in a plugin-owned disposable Git repository. It does **not** grant the child Hermes `file` or `terminal` toolsets.

Hermes Public Subagent Lifecycle API v1 rejects `working_directory` and per-tool blocking. Granting built-in `file`/`terminal` would therefore expose the parent environment rather than confine the child to the fixture. That is not an acceptable sandbox.

The safe Phase 3 shape is:

```text
backend-owned Phase 3 gate
→ plugin creates one isolated no-commit Git fixture repository
→ todo-only child chooses one closed mutation enum
→ controller maps enum to trusted source bytes
→ confined executor writes one allowlisted file
→ confined executor runs one fixed argv test command
→ deterministic evaluator records candidate/evaluation/receipt
→ terminal state
→ repository retained as evidence; no cleanup/delete tool
```

The model proposes data. Trusted plugin code owns every filesystem path, byte template, command, environment, timeout, evaluator, and terminal decision.

## Authority contract

### Child

- role: `leaf`;
- toolset: `todo` only;
- no model/provider override;
- no working directory;
- no file or terminal tools;
- no network, credentials, Git, scheduler, messaging, or deployment tools;
- returns exactly one JSON object with `mutation` and `rationale`.

### Controller

May only:

1. create a unique directory beneath the plugin-owned Phase 3 root;
2. write the fixed baseline files and `.git` metadata via `git init`;
3. replace only `calculator.py` with one trusted mutation template;
4. run exactly `python -m unittest -q` with `shell=False`, fixed cwd, minimal environment, bounded timeout;
5. read/hash files beneath the repository;
6. persist evidence to profile-scoped SQLite.

It may not delete the repository, commit, add remotes, push, fetch, access credentials, use a shell, follow symlinks, traverse outside the root, run child-provided commands, or write child-provided bytes.

## Fixture

Baseline `calculator.py`:

```python
def sum_even(numbers):
    return sum(numbers)
```

Fixed `test_calculator.py` expects only even integers to be summed.

Closed mutation enum:

- `baseline` — unchanged failing behavior;
- `filter_odd` — trusted but incorrect mutation;
- `filter_even` — trusted correct mutation.

The correct trusted source is:

```python
def sum_even(numbers):
    return sum(number for number in numbers if number % 2 == 0)
```

## Run contract

Phase 3 RunSpec is plugin-owned:

- target is the generated repository path;
- seed digest is the canonical baseline tree digest;
- evaluator is `phase3.unittest.v1`;
- comparison minimizes `test_failures`;
- correctness requires `tests_pass` and `mutation_matches`;
- max steps: 1;
- allowed child toolsets: `todo`;
- network disabled;
- explicit approval receipt required.

The user cannot provide paths, commands, toolsets, mutation bytes, evaluator IDs, network policy, or budgets.

## Persistence schema v4

Add append-only `mutation_receipts`:

- receipt hash;
- run ID;
- repository ID;
- baseline tree hash;
- mutated tree hash;
- mutation enum;
- changed paths;
- fixed command ID;
- exit code;
- test result;
- stdout/stderr hashes;
- repository retained flag;
- cleanup status fixed to `retained`.

The receipt is content-addressed and bound to the RunSpec/candidate/evaluation.

## Recovery

The run records `repo_created` before child launch and `mutation_applied` before test execution.

`avo_phase3_reconcile`:

- `running` + no receipt: mark interrupted/no-result; never rerun mutation or tests automatically;
- `running`/`evaluating` + complete receipt and candidate/evaluation: replay deterministic evaluation from durable evidence;
- other states: `noop`.

No process-local child handle is durable authority.

## Tools

Phase 3 adds:

- `avo_create_phase3_run`
- `avo_mutate_phase3`
- `avo_phase3_receipt`
- `avo_phase3_reconcile`

Existing status and lineage tools remain usable because all runs share the same profile-scoped ledger.

Backend settings:

- `phase3_enabled: false`
- `phase3_wait_seconds: 120`
- `phase3_test_timeout_seconds: 20`

Desktop cannot enable them.

## Acceptance

- [ ] Phase 0–2 suite remains green.
- [ ] Public lifecycle constraint is documented and no child gets file/terminal.
- [ ] Fixture repository is created only below plugin-owned root.
- [ ] Repository is a real Git repository with zero commits and no remotes.
- [ ] No symlink/path traversal can escape the run repository.
- [ ] Child output accepts only the closed mutation enum and bounded rationale.
- [ ] Controller writes only trusted template bytes to `calculator.py`.
- [ ] Executor uses fixed argv, `shell=False`, fixed cwd, minimal environment, and timeout.
- [ ] `filter_even` passes; baseline and `filter_odd` fail deterministically.
- [ ] No commit, push, remote, credential, network, deletion, or cleanup capability exists.
- [ ] Mutation receipt is content-addressed, append-only, and restart-readable.
- [ ] Interrupted mutation never reruns effects automatically.
- [ ] Plugin Doctor registers exactly fifteen tools and zero hooks.
- [ ] Desktop remains unable to enable backend execution.
- [ ] Local and Serenity suites, Ruff, build, Node syntax/harness, Plugin Doctor, security, and privacy gates pass.
- [ ] Live Serenity canary mutates one disposable repo, passes fixed tests, records one receipt, and leaves the repo retained.
- [ ] Final Serenity plugin state is disabled and all execution gates are false.
- [ ] Forge approves exact bytes; Terra independently passes exact bytes and live evidence.
- [ ] GitHub CI passes Python 3.11–3.13 and Desktop gates.

## Explicitly deferred

- arbitrary model-authored patches or code;
- child file/terminal access until Hermes supports a verified confined workspace capability;
- cleanup/deletion;
- commits, branches, remotes, pushes, pull requests, deployment, or promotion;
- network, credentials, package installation, or dependency resolution;
- more than one mutation per run;
- autonomous recurrence or scheduling;
- non-fixture repositories.
