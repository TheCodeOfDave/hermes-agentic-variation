# Variation Cycle — Atomic Bounded Multi-Artifact Proposal

## Decision

A Variation Cycle expands the **shape of one candidate**, not the authority of the model.

A `todo`-only child may propose one patch set affecting two or three existing, plugin-owned, explicitly allowlisted source files. Trusted controller and sandbox code independently validate and apply the complete set transactionally. Immutable tests remain controller-owned. The evaluator—not the model—decides eligibility.

A Variation Cycle does not add a loop, retry, commit, push, pull request, deployment, cleanup, network access, package installation, credential access, arbitrary repository, or test modification.

## Goal

Prove that Hermes can evaluate a small cross-file source change without allowing the child to:

- choose its repository, files, tests, command, image, runtime, or limits;
- weaken or replace the evaluator;
- apply only the convenient part of a patch set;
- add, remove, rename, copy, chmod, symlink, or binary-edit files;
- access the host filesystem, Docker socket, network, credentials, or another run;
- commit, push, publish, deploy, schedule, recur, or retry automatically.

## Non-goals

A Variation Cycle is not general coding authority. It is not a real-project repair agent and does not authorize:

- user repositories or arbitrary plugin repositories;
- test, fixture, CI, manifest, dependency, or configuration edits;
- package installation or lockfile changes;
- model-selected tools, commands, providers, images, or budgets;
- multiple attempts, iterative repair, autonomous continuation, or supervisor calls;
- source promotion, Git publication, deployment, messaging, purchasing, or deletion.

## Flow

```text
backend Variation Cycle gate
→ plugin-owned immutable three-file baseline repository
→ fixed objective and immutable test suite
→ todo-only child returns one closed patch-set JSON object
→ host validates exact schema, cardinality, paths, aggregate size, and each patch
→ Stage A: trusted applier container, pinned image and locked policy
→ applier revalidates baseline hashes and every patch without importing or executing candidate code
→ host accepts exactly one complete applier envelope and independently reconstructs every output byte
→ host atomically stages the verified candidate below the plugin-owned artifact root
→ Stage B: separate untrusted candidate worker behind an immutable evaluator process
→ fixed JSON request corpus runs with network none and the same resource/security ceilings
→ evaluator detects early exit, `os._exit(0)`, missing/extra/malformed responses, timeout, signal, stderr, and overflow
→ host requires Docker exit 0 plus one exact immutable success trailer
→ exact changed-path set, source hashes, test result, and fixed command are verified
→ atomic candidate/evaluation/patch-set receipt
→ terminal state
```

## Fixture

The plugin creates one real, no-commit, no-remote Git repository below the Variation Cycle workspace root.

Fixed source files:

- `calculator.py` — allowlisted source file;
- `filters.py` — allowlisted source file;
- `formatting.py` — optional third allowlisted source file used by negative/cardinality cases.

Immutable evaluator artifacts are mounted separately and never enter the patchable repository:

- `phase5_cases.json` — fixed ordered request/expected-response corpus;
- `phase5_evaluator.py` — PID-1 parent evaluator that never imports candidate modules;
- `phase5_worker.py` — fixed worker bootstrap that alone imports candidate modules and speaks the bounded pipe protocol.

The primary canary requires coordinated changes to `calculator.py` and `filters.py`; neither file can satisfy the immutable case corpus alone. A separate valid three-file acceptance case changes `formatting.py` as well to prove the ceiling and canonical ordering behavior.

Cases, manifests, trusted applier/evaluator/worker code, and repository metadata are never patch targets.

## Child contract

The child remains a fresh leaf session with only the in-memory `todo` toolset.

Exact JSON shape:

```json
{
  "patches": [
    {
      "path": "calculator.py",
      "patch": "--- a/calculator.py\n+++ b/calculator.py\n..."
    },
    {
      "path": "filters.py",
      "patch": "--- a/filters.py\n+++ b/filters.py\n..."
    }
  ],
  "rationale": "bounded explanation"
}
```

Validation:

- exact top-level keys: `patches`, `rationale`;
- `patches` is an array of two or three objects;
- each object has exactly `path` and `patch` string keys;
- paths are unique ASCII names from the closed allowlist;
- patches are ordered by UTF-8 bytewise lexicographic path order; this is the canonical path order throughout a Variation Cycle;
- each patch header must be exactly `--- a/<path>` then `+++ b/<path>` with no BOM, timestamp, suffix, or trailing text;
- rationale is non-empty, at most 1,000 Unicode scalar values, and at most 4,000 UTF-8 bytes;
- each patch is at most 8 KiB measured after JSON decoding as UTF-8 bytes;
- aggregate encoded patch bytes are at most 16 KiB;
- each decoded patch line is at most 500 UTF-8 bytes;
- canonical patch-set identity is SHA-256 over strict JSON encoded with sorted keys, no insignificant whitespace, ASCII escapes, finite values only, and the already canonical patch order;
- no unknown keys, duplicate paths, duplicate patch bytes, Unicode line separators, CR, NUL, overlong lines, or trailing data.

The child does not receive file, terminal, Docker, network, credential, model, provider, Git, scheduling, or messaging tools.

## Patch contract

Each member is one strict unified patch against one existing allowlisted source file.

Allowed per file:

- exactly one canonical file header pair with no suffixes;
- one or two hunks;
- at least one unchanged context line per hunk;
- exact application at the hunk-header line positions with no fuzz, offset search, or optional section text;
- context, removals, and additions that match the approved baseline exactly;
- canonical LF-terminated UTF-8 text without BOM;
- at least one content-changing addition or removal in every member;
- changes only within the existing file.

Rejected:

- file additions or deletions (`/dev/null`);
- rename, copy, mode, binary, submodule, symlink, or no-newline markers;
- absolute paths, traversal, backslashes, alternate separators, or Unicode separator tricks;
- BOMs, timestamped headers, optional hunk-section text, zero-context hunks, fuzz, or offset application;
- tests, fixtures, manifests, runner files, Git metadata, dependencies, or configuration;
- overlapping or out-of-order hunks;
- context/removal mismatch;
- hunk count or line count mismatch;
- no-op patch members whose output hash equals the baseline hash;
- output source larger than 16 KiB per file;
- any patch-set member failing validation.

The host parser validates every member before Docker starts. Stage A repeats baseline and patch validation independently without importing candidate modules.

## Atomicity

A patch set is all-or-nothing across two isolated stages.

### Stage A — trusted patch application

1. Start a fresh applier container with the immutable baseline, patch-set input, and applier mounted read-only.
2. Verify the baseline tree and every allowlisted/test-file hash.
3. Parse and apply every patch in canonical path order without importing or executing any patched module.
4. Reject the entire set if any member fails or produces no content change.
5. Capture exactly one complete strict-JSON applier envelope; zero, multiple, partial, prefixed, or suffixed envelopes fail closed.
6. The host reconstructs every expected source independently and rejects any path, order, byte, or hash mismatch.
7. Only then does the host atomically stage the complete candidate below the plugin-owned artifact root.

Because Stage A treats patches and sources only as data, model-authored Python never executes beside the trusted applier or its output channel.

### Stage B — untrusted candidate execution behind an immutable evaluator

1. Start a separate container with staged candidate sources and the immutable evaluator/worker bootstrap mounted read-only.
2. Run a fixed evaluator command as container PID 1. The evaluator process never imports candidate modules.
3. The evaluator launches one candidate worker subprocess with closed stdin after startup, sanitized environment, `close_fds=True`, and bounded stdout/stderr pipes.
4. Only the candidate worker imports and executes patched modules. It receives a fixed ordered JSON request corpus over a dedicated pipe and returns one bounded strict-JSON response per case.
5. The immutable evaluator validates response schema, case ID, cardinality, order, value, worker exit, and complete end-of-stream. Worker `os._exit(0)`, early exit, missing/duplicate/extra response, malformed JSON, stderr, timeout, signal, or output overflow is a deterministic failure.
6. The evaluator writes the fixed literal success trailer `PHASE5_EVALUATOR_PASS cases=<fixed-count>` only after every expected case passes, then exits `0`. Every other path exits nonzero and never writes the success trailer.
7. Host eligibility requires Docker exit `0`, exact trailer equality, bounded evaluator stdout, and empty evaluator stderr. Exit `0` without the exact trailer is a false-PASS classification and fails closed.
8. Hash the exact host-captured evaluator stdout/stderr bytes for the receipt.
9. Require the changed-path set to equal the validated patch-set path set before retaining the final candidate artifact.

The candidate worker cannot write directly to container stdout/stderr because both are pipes owned and consumed by the immutable evaluator. It receives no evaluator success trailer or completion state. Candidate-controlled exit status alone can never make the Docker container eligible.

No partial candidate, partial receipt, or partial eligibility decision is representable. A crash-created staging directory without a committed receipt is an inert orphan: it is never loaded, promoted, rewritten, or automatically deleted, and reconciliation reports it explicitly.

## Sandbox policy

Both stages use the digest-pinned image and fail-closed Docker adapter family proven by the earlier single-artifact workflow, but they run as separate containers and share no process, writable filesystem, or output channel.

Required Docker arguments remain controller-owned for each stage:

- exact digest-pinned Python image;
- `--pull=never`;
- `--network=none`;
- `--read-only`;
- `--cap-drop=ALL`;
- `--security-opt=no-new-privileges`;
- non-root UID/GID distinct from host-sensitive service identities;
- fixed memory, CPU, PID, tmpfs, and host timeout ceilings;
- Stage A read-only mounts for baseline, patch-set input, and trusted applier;
- Stage A stdout ceiling of 96 KiB, which exceeds the computed maximum valid three-file base64 envelope plus framing; any Stage A stderr byte is an error and its bounded hash is retained;
- Stage B read-only mounts for verified staged candidate, immutable case corpus, evaluator, and worker bootstrap;
- Stage B evaluator stdout ceiling of 4 KiB with exact success-trailer matching and empty evaluator stderr;
- candidate-worker response and stderr pipes capped at 64 KiB each inside the evaluator;
- fixed workdir and one fixed command per stage;
- closed stdin and bounded stdout/stderr.

The receipt records both stage command IDs and the literal memory, CPU, PID, tmpfs, UID/GID, output, and timeout ceilings in addition to the policy hash.

The model, plugin inside the Hermes acceptance container, and both sandbox containers never receive the host Docker socket.

## Import, staging, and test evidence

Approved input identity binds:

- RunSpec hash;
- ordered allowlisted source paths and baseline hashes;
- immutable case-corpus, evaluator, and worker-bootstrap hashes;
- canonical patch-set hash;
- rationale hash;
- ordered member patch hashes;
- trusted applier hash;
- pinned image digest;
- both stage command IDs;
- sandbox policy hash and literal ceilings.

Stage A emits exactly one strict JSON document occupying all container stdout, with no prefix, suffix, second object, partial frame, or non-UTF-8 bytes. Candidate patches are never executed in Stage A. The envelope contains:

- ordered changed paths;
- each patched source as base64;
- per-file source hashes;
- candidate tree hash;
- applier command ID;
- applier status;
- policy values.

The host reconstructs the expected patched sources using its independently validated patch set and rejects any byte, path, order, hash, status, policy, command, or framing mismatch before staging files.

Candidate tree hash is SHA-256 over the canonical JSON array of UTF-8 bytewise path-ordered `(path, source_sha256)` pairs for all three allowlisted source files. `.git`, evaluator artifacts, staging metadata, tmpfs/runtime files, timestamps, and filesystem attributes are excluded and bound separately where applicable.

Stage B emits no candidate envelope. The host directly observes:

- Docker process exit code;
- exact bounded evaluator stdout bytes;
- exact bounded evaluator stderr bytes;
- timeout, signal, launch, and overflow classifications.

The host hashes those captured bytes itself. Eligibility requires every prior Stage A and changed-path check, Docker exit `0`, evaluator stdout equal to the exact fixed success trailer, and empty evaluator stderr. Exit `0` with empty, additional, malformed, or incorrect stdout is `FALSE_PASS` and fails closed. Candidate-worker exit `0` without the complete ordered response set is rejected by the immutable evaluator before the container can emit the success trailer. Zero, multiple, partial, prefixed, suffixed, forged, or truncated Stage A envelopes fail before artifact write.

## Persistence schema v6

Add append-only `patch_set_receipts`.

One receipt binds:

- RunSpec, candidate, and evaluation hashes;
- ordered baseline paths and hashes;
- ordered changed paths;
- patch-set, rationale, and member patch hashes;
- image, trusted-applier, immutable-cases, evaluator, worker-bootstrap, policy, both command, output tree, and output source hashes;
- literal memory, CPU, PID, tmpfs, UID/GID, Stage A 96-KiB output, Stage B/worker output, and timeout ceilings for both stages;
- Stage A envelope hash/status and empty-stderr hash/classification;
- host-observed Stage B Docker exit, exact success-trailer result, evaluator stdout/stderr hashes, and candidate-worker failure classification;
- retained artifact directory relative to plugin data;
- network policy `none`;
- cleanup status `retained`.

Candidate, evaluation, and patch-set receipt are inserted in one SQLite transaction. Update and delete triggers remain fail-closed.

Schema v5→v6 migration runs in one SQLite transaction and must preserve all pre-existing runs, events, candidates, evaluations, continuation memory, supervisor advice, mutation receipts, and sandbox receipts byte-for-byte. Migration tests compare populated pre/post rows and schema version, and any error rolls back the complete migration.

## Controller

The Variation Cycle engine adds one controller with an independent backend gate and workspace/artifact roots.

Responsibilities:

- validate objective and approval receipt before side effects;
- preflight the exact local image before repository creation;
- create one Cycle Specification with a closed evaluator ID and allowlist;
- launch exactly one `todo`-only child;
- parse one strict patch-set payload;
- validate all patches before Docker;
- run exactly one trusted applier container and verify its single envelope;
- reconstruct and atomically stage the complete candidate;
- run exactly one separate immutable-evaluator container with one candidate worker;
- directly capture and classify evaluator Docker exit/stdout/stderr and worker protocol failures;
- retain one final candidate artifact directory only after all identity checks;
- atomically record candidate, evaluation, and receipt;
- transition to one terminal result;
- report inert staging orphans during reconciliation;
- never retry automatically.

Every Variation Cycle tool must reject legacy run IDs before transitions, child calls, filesystem changes, or Docker calls. Legacy tools must similarly reject internal `phase5-` identifiers before effects.

## Recovery

Recovery remains evidence-only:

- crash before complete atomic evidence: classify interruption and terminate without child, applier-container, or test-container replay;
- crash after candidate/evaluation/receipt commit but before state transition: replay only the stored deterministic eligibility event;
- missing, duplicate, mismatched, partially ordered, or ambiguously framed evidence: fail closed;
- a staging directory without a matching committed receipt is reported as an inert orphan and is never loaded, promoted, rewritten, or automatically deleted;
- the fixture workspace, retained candidate, receipt, and reported inert orphans are explicit retained evidence—not untracked success residue;
- no automatic child launch, Docker execution, patch application, test execution, artifact rewrite, cleanup, or retry.

## Tools

The Variation Cycle engine exposes four internal compatibility tools:

- `avo_create_phase5_run`;
- `avo_patchset_phase5`;
- `avo_phase5_receipt`;
- `avo_phase5_reconcile`.

Expected plugin registration after implementation: 23 tools, 0 hooks.

Backend settings default closed:

- `phase5_enabled: false`;
- `phase5_wait_seconds: 120`;
- `phase5_sandbox_timeout_seconds: 30`.

File count, allowlist, per-patch size, aggregate size, hunk ceiling, image, command, and sandbox policy are code-owned constants, not Desktop settings.

Desktop may explain Variation Cycles but cannot enable execution or widen any limit.

## TDD slices

Implementation must use vertical RED→GREEN slices:

1. strict patch-set contract, numeric byte/character ceilings, and canonical identity;
2. canonical two-file success, canonical three-file success, and one-file/four-file/duplicate/unsorted/unknown/no-op-member rejection;
3. strict exact-position hunk application with header/BOM/context/fuzz/offset negatives;
4. Stage A applier atomicity, single-envelope framing, and immutable baseline revalidation without candidate execution;
5. Stage A forged/duplicate/truncated/prefixed/suffixed envelope rejection and host byte reconstruction;
6. Stage B immutable evaluator/worker protocol with host-observed exit/trailer/stdout/stderr, including `os._exit(0)`, exit-0-empty-output, early/partial/duplicate/extra response, timeout, signal, stderr, and overflow negatives;
7. exact changed paths, tampered source/path/order/tree/policy/command rejection, and inert-orphan reporting;
8. schema v6 atomic append-only receipt and populated-v5 transactional migration;
9. controller success/failure and legacy-tool routing;
10. no-effect recovery across both stages;
11. Desktop/manifest/tool registration and disabled defaults;
12. real pinned-Docker two-file and three-file canaries.

Each production behavior requires a focused failing test observed before implementation, then focused GREEN and full-suite verification.

## Acceptance

- [ ] All pre-existing suites remain green.
- [ ] Patch-set parser accepts canonical two-file and three-file cases.
- [ ] One-file, four-file, duplicate, unsorted, unknown, test-file, traversal, CR, NUL, BOM, Unicode-separator, timestamped-header, optional-section, binary, rename, mode, zero-context, fuzz/offset, no-op-member, over-500-byte-line, over-1,000-scalar/4,000-byte rationale, and oversized sets fail closed.
- [ ] Every member is validated before Stage A starts.
- [ ] Stage A revalidates baseline hashes and every member independently without importing or executing patched code.
- [ ] Stage A patch application is all-or-nothing.
- [ ] Stage A accepts exactly one complete strict-JSON envelope within the 96-KiB ceiling, emits empty stderr, admits the maximal valid three-file envelope, and rejects zero, forged, duplicate, partial, truncated, prefixed, or suffixed envelopes.
- [ ] Host reconstruction rejects all Stage A path/order/source/tree/status/policy/command tampering before staging.
- [ ] Stage B runs separately with read-only candidate/cases/evaluator/worker artifacts; only the worker imports candidate modules.
- [ ] The evaluator validates the complete ordered case protocol and candidate worker stdout/stderr/exit independently.
- [ ] Stage B Docker exit code and bounded evaluator stdout/stderr are captured and hashed directly by the host.
- [ ] Eligibility requires exit `0`, the exact immutable success trailer, and empty evaluator stderr.
- [ ] Candidate `os._exit(0)`, exit-0-empty-output, missing/duplicate/extra/partial response, malformed JSON, worker stderr, nonzero exit, timeout, signal, launch failure, and output-overflow cases fail closed or become deterministically ineligible.
- [ ] Exact changed-path set is enforced and immutable cases/evaluator/worker artifacts cannot be patched, omitted, or shadowed.
- [ ] Candidate tree hash scope and canonical serialization match the specification.
- [ ] Candidate/evaluation/patch-set receipt binds rationale, both stages, literal ceilings, and is atomic and append-only.
- [ ] Populated schema-v5 migration is transactional and preserves prior evidence.
- [ ] Recovery never reruns child, either Docker stage, patch, or tests and reports inert orphans.
- [ ] All legacy and Variation Cycle tools reject foreign run IDs before effects.
- [ ] Plugin Doctor reports 23 tools and 0 hooks; this count is confirmed from the implemented 19-tool baseline plus four Variation Cycle tools, not assumed from the specification.
- [ ] Desktop remains opt-in and cannot enable backend execution.
- [ ] Windows test VM focused/full gates pass.
- [ ] Real pinned-Docker two-file and three-file canaries pass; residue is limited to explicitly retained workspace/candidate/receipt evidence and reported inert orphans.
- [ ] Independent technical review approves exact bytes.
- [ ] Both commit privacy gates pass without bypass.
- [ ] Independent QA passes exact committed bytes.
- [ ] Acceptance-host Plugin Doctor and direct-host canaries pass while the plugin remains disabled and all backend execution gates are false.
- [ ] Non-force push and GitHub CI pass on exact SHAs.

## Explicitly deferred

- arbitrary repositories and user projects;
- file additions, deletions, renames, copies, modes, binaries, symlinks, tests, fixtures, manifests, dependencies, configuration, or CI changes;
- package installation and network access inside the sandbox;
- child file, terminal, Docker, Git, credential, messaging, scheduling, or deployment tools;
- repeated attempts, supervisor calls, continuation loops, scheduling, or recurrence;
- automatic commits, pushes, pull requests, publication, deployment, cleanup, or promotion;
- Docker socket mounts into Hermes containers;
- production enablement.

## Promotion rule

Variation Cycles may be implemented only after this specification receives independent architecture/security review. Any review correction changes the specification digest and requires a fresh review. Implementation acceptance does not authorize any wider authority.
