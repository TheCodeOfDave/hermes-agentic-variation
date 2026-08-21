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

- [x] Phase 0–2 suite remains green.
- [x] Public lifecycle constraint is documented and no child gets file/terminal.
- [x] Fixture repository is created only below plugin-owned root.
- [x] Repository is a real Git repository with zero commits and no remotes.
- [x] No symlink/path traversal can escape the run repository.
- [x] Child output accepts only the closed mutation enum and bounded rationale.
- [x] Controller writes only trusted template bytes to `calculator.py`.
- [x] Executor uses fixed argv, `shell=False`, fixed cwd, minimal environment, and timeout.
- [x] `filter_even` passes; baseline and `filter_odd` fail deterministically.
- [x] No commit, push, remote, credential, network, deletion, or cleanup capability exists.
- [x] Mutation receipt is content-addressed, append-only, and restart-readable.
- [x] Interrupted mutation never reruns effects automatically.
- [x] Plugin Doctor registers exactly fifteen tools and zero hooks.
- [x] Desktop remains unable to enable backend execution.
- [x] Local and Serenity suites, Ruff, build, Node syntax/harness, Plugin Doctor, security, and privacy gates pass.
- [x] Live Serenity canary mutates one disposable repo, passes fixed tests, records one receipt, and leaves the repo retained.
- [x] Final Serenity plugin state is disabled and all execution gates are false.
- [x] Forge approves exact bytes; Terra independently passes exact bytes and live evidence.
- [x] GitHub CI passes Python 3.11–3.13 and Desktop gates.

## Acceptance receipt — 2026-08-21

- Accepted implementation commit: `ec31a305df3e91780e95f4c285faf264b2973859`
- Parent: `bcbe1724d75d3825afa6f7d21e7d51bc45804d3a`
- Implementation diff SHA-256: `96075b71ecb68b7eb1885ee2405a998a4332450dc8fcf7b3d858bef72e3b73b2`
- Candidate archive SHA-256: `70ffbf56979016bc838efcbbed81289fa880ccb3f49f0831e73ad2a76dca8d94`
- Local and Serenity: 96 tests passed; Ruff, wheel build, Node syntax, Desktop VM harness, and Plugin Doctor passed; Plugin Doctor registered fifteen tools and zero hooks.
- Security scan found no hardcoded secrets, shell injection, dynamic execution, unsafe pickle, or formatted SQL. Both Git privacy gates passed before commit.
- Forge/GLM: `APPROVE` on exact final bytes after cross-phase run-ownership and tool-routing corrections.
- Verifier/Terra: final corrected run `PASS`; authoritative archive hash and full installed-source equality verified, after superseding two blocked attempts that used the wrong archive/location evidence.
- Serenity: Hermes v0.20.5 upstream `76f6ba37`; plugin 0.4.0 installed and left disabled.
- Live run `phase3-ec70160e83e350b6`: todo-only child selected `filter_even`; controller changed only trusted `calculator.py`; fixed `python -m unittest -q` ran two tests and passed; state `succeeded`, revision 4; one candidate, one evaluation, one append-only mutation receipt, child API calls 1.
- Retained repository: `/opt/data/plugin-data/agentic-variation/phase3-runs/phase3-ec70160e83e350b6`; Git commit count 0; remote count 0; baseline tree `c174344437b68536e0f858d41e28aad269a90e7e221566de26bc6e0a647a650c`; mutated tree `a1e0236ae7a2b2338452aeb687416a9110ed8477745347b513d39fabb4ad51f0`.
- Receipt hash: `c5051b6e9e38b11957faf5060e30da6fbc6c42d05f0f3831d85d854187805728`; cleanup status `retained`.
- Final backend state: Phase 1/2/3 gates false, plugin disabled, plugin toolset absent from CLI, API and containers healthy with zero restarts.
- GitHub Actions: https://github.com/TheCodeOfDave/hermes-agentic-variation/actions/runs/32531547427 — PASS across Python 3.11–3.13, Ruff, and Desktop gates.
- Environmental residuals: Serenity filesystem was 93% used with about 14 GB free. Acceptance tooling left `.venv`, `.pytest_cache`, and `.ruff_cache` under the installed plugin directory; they were not deleted because deletion was not authorized.
- Known upstream residual: interactive CLI emitted the existing unknown-toolset warning and exited `134` during Honcho teardown after returning the successful result; authoritative receipt and final safe state were intact.

## Explicitly deferred

- arbitrary model-authored patches or code;
- child file/terminal access until Hermes supports a verified confined workspace capability;
- cleanup/deletion;
- commits, branches, remotes, pushes, pull requests, deployment, or promotion;
- network, credentials, package installation, or dependency resolution;
- more than one mutation per run;
- autonomous recurrence or scheduling;
- non-fixture repositories.
