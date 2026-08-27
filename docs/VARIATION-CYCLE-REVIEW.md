# Variation Cycle Specification Review Receipt

- Specification: `docs/VARIATION-CYCLE.md`
- Architecture-reviewed SHA-256 (pre-terminology bytes): `2245046f28d573c82e251e761a172f5780c29e26542127f1b44afc70da208553`
- Current terminology-adjusted SHA-256: `b4318d00cf1ca48e07f0b5f9ab53c0cdbb46799dc493359082064abdcba253fe`
- Independent reviewer: `technical_review` (GLM)
- Verdict: **APPROVE**
- Scope: specification-only architecture/security review; no implementation reviewed or authorized by implication.
- Publication status: naming-only bytes changed after review; fresh exact-byte review is required before promotion.

## Review lineage

1. `719d080ec17d25bcb0515b5061e89ea7c426bd80aef2c7bae1b4df2b7126be48` — `REQUEST_CHANGES`; required evaluator-channel, numeric-bound, three-file, identity, receipt, migration, and orphan corrections.
2. `6afdf7be8873d9016c6858ad0cf752f6877a38859ccd100e931d94a8f398e88f` — `APPROVE` with should-fix advisories; identified candidate-controlled Stage B exit-status forgery and output-ceiling precision.
3. `2245046f28d573c82e251e761a172f5780c29e26542127f1b44afc70da208553` — final `APPROVE`; no material defect remains.

Rejected and superseded revisions are retained outside the repository in the private development evidence directory.

## Final architecture boundary

- A Variation Cycle expands one candidate from one artifact to an atomic two-or-three-artifact source proposal.
- Stage A treats patches only as data and never imports or executes candidate code.
- Stage B runs candidate code only in a bounded worker behind an immutable PID-1 evaluator and fixed request corpus.
- Candidate-controlled process exit, missing/extra/partial responses, stderr, malformed data, timeout, signal, and output overflow cannot create a PASS.
- No network, credentials, Docker socket, arbitrary repository, test modification, commit, push, pull request, deployment, recurrence, cleanup, or production authority is granted.
- Backend execution remains disabled by default and Desktop cannot enable or widen it.

## Non-blocking implementation advisories

- Pin whether the exact success trailer includes a trailing newline.
- Test worker stderr flooding beyond 64 KiB to prove overflow classification does not deadlock.
- A per-case evaluator timeout is optional defense in depth; the stage timeout remains mandatory.

Any material specification change after this receipt changes the digest and requires a fresh independent review before implementation continues. Later system-neutral wording edits do not change the architecture, but their new document hash still requires verification before publication.
