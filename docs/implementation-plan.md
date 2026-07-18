# Implementation and PR plan

## Purpose

This plan turns the contracts in this repository into small, reviewable pull requests. Each PR must leave `main` runnable, demonstrate one coherent capability, and satisfy its own merge gate without depending on unfinished future work.

The canonical specifications are:

- [Product contract](product.md)
- [Architecture](architecture.md)
- [Application contracts](contracts.md)
- [Semantic and optimization engine](engine.md)

If implementation exposes a missing or contradictory decision, update the relevant contract in the same PR. Do not silently invent a second behavior in code.

The current workspace is not recognized as a Git repository. Before PR 1, initialize or repair repository metadata, commit the documentation baseline, and create the implementation branch. That setup does not change the product architecture.

## Dependency map

```text
Documentation baseline
        |
       PR 1  Application foundation
        |
       PR 2  Persistence and domain
        +--------------------------> PR 6  Optimizer engine --------+
        |                                                            |
        v                                                            |
       PR 3  Room access and host authoring                          |
        +----------------> PR 5  Semantic compiler ------------------+
        |                                                            |
        v                                                            v
       PR 4  Participant collection ------------------------------> PR 7
                                                                     |
                                                                   PR 8
                                                                     |
                                                                   PR 9
```

PR 4 and PR 5 may proceed in parallel after PR 3. PR 6 may begin after PR 2 and run beside them. PR 7 waits for all three; the remaining PRs merge in order.

## Rules for every PR

### Scope

- One primary review question and one end-to-end outcome.
- No speculative infrastructure, compatibility layer, or abstraction for deferred features.
- Database changes include an Alembic migration and migration test.
- API changes include request, response, authorization, state, and error tests.
- User-facing changes include loading, empty, failure, and narrow-screen behavior relevant to that slice.
- Contract changes are made before or with the implementation they govern.

### Required checks

```text
Backend:   Ruff, mypy, pytest
Frontend:  TypeScript, Vitest, production Vite build
Flows:     Playwright for every completed cross-page workflow
Image:     multistage Docker build from a clean checkout
```

CI never calls the live model provider. Semantic tests use recorded, reviewed fixtures. A live provider smoke test is an explicit manual release step.

### Security and privacy gate

- No session contents, answers, reference material, provider payloads, or secrets in logs or public errors.
- Every mutation proves the caller's room grant, checks CSRF, and checks room state.
- Participant endpoints never expose host-only reference material, coverage units before publication, other groups, or other participants' raw answers.
- User and model strings render as text; no raw HTML path is introduced.
- Input bounds are enforced before persistence and before provider calls.

### Merge evidence

Every PR description includes:

1. the user-visible outcome;
2. the contract sections implemented or changed;
3. commands and results for required checks;
4. one screenshot or short recording for a UI slice;
5. any intentionally deferred edge case already named in these docs.

## Documentation baseline — canonical decisions

**Outcome:** one source of truth exists before application scaffolding begins.

Included:

- product promise, limits, policies, and acceptance criteria;
- React/Vite/Tailwind plus FastAPI/PostgreSQL architecture;
- signed room-session access model;
- four-table persistence and JSON artifact contracts;
- semantic compiler and coverage-first optimizer specification;
- this ordered implementation plan;
- historical proposals moved out of the canonical document path.

**Merge gate:** all local links resolve, JSON examples parse, terminology is consistent, and no active document specifies the superseded server-rendered or Supabase designs.

## PR 1 — Application foundation

**Depends on:** documentation baseline.

**Outcome:** a developer can start the complete local stack and load a styled React route through FastAPI.

### Scope

- Create `frontend/` with React, TypeScript, Vite, Tailwind, and React Router.
- Create `backend/` with Python 3.12, FastAPI, Pydantic, settings, structured logging, and a health endpoint.
- Add a development proxy from Vite to `/api`.
- Add reproducible TypeScript API-type generation from FastAPI OpenAPI.
- Add FastAPI production static serving and `index.html` fallback for browser routes, excluding `/api` and built assets.
- Add PostgreSQL to Docker Compose and a multistage Dockerfile skeleton.
- Establish backend and frontend test, lint, type-check, and build commands.
- Commit reproducible Python and npm lock files; use `npm ci` for clean frontend builds.
- Add `.env.example` with names and safe descriptions only.

### Not included

Database models, sessions, room creation, model calls, or optimization.

### Tests and merge gate

- Unit smoke tests for FastAPI startup and the React shell.
- Direct refresh works for `/`, `/create`, `/host/example`, and `/join/example` in the production image.
- `/api/health` returns success; unknown `/api` paths return JSON `404`, not `index.html`.
- A clean Docker build starts one Python application process and connects to PostgreSQL.

## PR 2 — Persistence and domain contracts

**Depends on:** PR 1.

**Outcome:** the four-table data model and typed JSON artifacts are executable and migration-backed.

### Scope

- Add SQLAlchemy models for rooms, questions, participants, and responses.
- Add the initial Alembic migration with checks, composite foreign keys, indexes, defaults, and cascades from [contracts.md](contracts.md#postgresql-schema).
- Add Pydantic domain schemas for coverage units, analysis results, and grouping results.
- Add repository methods that always scope room-owned records by `room_id`.
- Add room-state transition guards as domain functions.
- Add factories for cryptographically random, normalized join codes and application-owned unit, family, and group IDs.
- Define deterministic JSON serialization and schema-version validation.

### Not included

Public room endpoints, browser sessions, model prompts, or CP-SAT logic.

### Tests and merge gate

- Migration upgrades an empty PostgreSQL database and downgrades cleanly in test.
- Database checks reject invalid group bounds, states, cross-room responses, and duplicate positions.
- Domain tests cover every allowed and rejected state transition.
- JSON round-trip tests reject unknown schema versions, duplicate IDs, and dangling references.
- Join-code generation passes alphabet, normalization, and collision-retry tests.

## PR 3 — Room access and host authoring

**Depends on:** PR 2.

**Outcome:** a host can create and fully prepare a draft room without an account.

### Scope

- Add the signed, HTTP-only Starlette room-session cookie and bounded room grants.
- Add `GET /api/session`, CSRF token handling, and same-origin mutation checks.
- Implement host authorization and caller-safe `404`, `409`, and `422` errors.
- Implement room creation, host room retrieval, room settings update, question CRUD, reordering, and opening.
- Implement unit editing with stable application-owned IDs.
- Add the React create-room and host-authoring pages.
- Validate question, reference, unit, and group-size limits at the API boundary.
- Treat opening as approval of every current coverage-unit list.

### Not included

Automatic unit generation, participant joining, response collection, or grouping.

### Tests and merge gate

- A new browser session creates a room and receives host access without a profile.
- A different session cannot discover or mutate the room through host endpoints.
- CSRF, malformed session, missing grant, wrong state, and validation cases have stable errors.
- New manual units receive server IDs; edits preserve IDs; unknown IDs are rejected; deleted IDs are not reused; draft regeneration can replace the list later.
- The room cannot open without questions, valid units, or valid capacity bounds.
- Playwright completes create → author questions → approve units → open.

## PR 4 — Participant joining, answers, and polling

**Depends on:** PR 3.

**Outcome:** participants can join an open room, edit only their own answers, and both roles see accurate progress.

### Scope

- Implement public join-code lookup and idempotent participant joining.
- Add participant grants to the signed room session.
- Implement participant room state and own-response APIs.
- Implement answer upsert; normalized blank input deletes the response row.
- Implement compact host/participant status polling with caller-specific fields.
- Add host removal of a participant while the room is open; response rows cascade.
- Build join, answer, waiting, and host lobby pages with two-second polling.
- Define progress as submitted response rows over `participants × questions`.
- Use shared room-row locks for joins and response writes so the analysis transition can freeze a complete snapshot.

### Not included

Semantic compilation, optimization, or published groups.

### Tests and merge gate

- Two browser contexts join the same room and can change only their own answers.
- Repeating join from the same room grant returns the existing participant.
- Participant responses never contain reference material or another participant's data.
- Host counts update through polling and stop polling in terminal states.
- Concurrent write/freeze tests prove no response commits after the room becomes `analyzing`.
- Playwright completes join → answer → edit → wait on desktop and narrow mobile viewport.

## PR 5 — Semantic compiler

**Depends on:** PR 2 for domain artifacts and PR 3 for draft questions. May run in parallel with PR 6.

**Outcome:** reviewed room inputs compile into a validated, deterministic analysis artifact without letting the model form groups.

### Scope

- Add the official OpenAI Python client and Responses API behind the narrow compiler interface in [engine.md](engine.md#boundary).
- Implement coverage-unit generation from a prompt and optional host-only reference material.
- For each non-empty question, implement two independent batched calls over the same opaque participant IDs: coverage classification and family clustering.
- Give the coverage call the question, optional reference material, approved units, and answers; require transient exact-answer evidence for every covered unit.
- Give the family call only the question and answers; never pass it reference material, coverage units, or coverage output.
- Use separate Pydantic-backed Structured Output schemas with `store: false`, then apply independent domain validation and at most one bounded repair attempt per call.
- Validate literal evidence spans, merge the two complete result sets by participant ID, and persist only `familyId` plus `coveredUnitIds`.
- Assign unit and family IDs in application code; accept only model-returned text, indices, and known IDs.
- Add locally generated empty assignments for unanswered participant-question pairs.
- Skip both provider calls for an all-empty question and emit empty families plus empty assignments.
- Add prompt-injection delimiters, timeouts, concurrency bounds, and privacy-safe provider telemetry.
- Add reviewed dynamic-programming and philosophy fixtures.

### Not included

Room background tasks, CP-SAT grouping, or live host review pages.

### Tests and merge gate

- Recorded fixtures validate without network access.
- Coverage-contract tests cover unknown or duplicate IDs, invalid units, missing or extra evidence, non-literal or oversized quotes, extra fields, and the repair limit.
- Family-contract tests cover unknown or duplicate IDs, invalid family indices, unused families, a valid all-null result with `families: []`, extra fields, and the repair limit.
- Schema tests reject family fields in coverage output and coverage or evidence fields in family output.
- Merge tests prove exact participant-set agreement; order-independent merging of shuffled arrays; null-family coverage; unequal coverage inside one family; equal coverage across different families; and no partial artifact when either call fails.
- Independence tests prove changing only a family result cannot change `coveredUnitIds`, and changing only a coverage result cannot change `familyId`.
- Provider-call tests prove the two prompts are isolated, all-empty questions make zero calls, and a partially answered question makes two initial calls before any bounded repair or transport retry.
- Stored-artifact tests reject evidence and family-level unit fields.
- Logs and exceptions contain no answer or reference text.
- Fixture evaluation separately reports evidence-supported per-unit precision/recall and pairwise family agreement for human review.
- The initial live-demo quality gates in [engine.md](engine.md#semantic-evaluation) pass on adjudicated fixtures.
- A manual smoke test generates sensible units, classifies coverage, clusters families, and merges both subjects with the configured provider and pinned model.

## PR 6 — Coverage-first optimizer

**Depends on:** PR 2. May run in parallel with PR 5.

**Outcome:** a validated semantic artifact produces a capacity-valid partition with honest feasibility and solver statuses.

### Scope

- Implement feasible group-count selection and balanced fixed capacities.
- Implement CP-SAT assignment, coverage, full-coverage, and family-presence variables.
- Implement the exact full-coverage feasibility pass and tri-state status.
- Implement normalized lexicographic coverage fallback objectives.
- Implement solver-only representative variables and Teach Each Other objectives.
- Implement Explore Different Approaches objectives.
- Add deterministic seed, stable ordering, one search worker, initial hints, symmetry breaking, and canonical group labels.
- Persist only the small grouping artifact; derive diagnostics separately.
- Add the global time-budget behavior and best-found-within-limit wording.

### Not included

HTTP routes, database orchestration, model calls, or presentation UI.

### Tests and merge gate

- Known fixtures cover feasible, proven-infeasible, timeout/unknown, null-family, and missing-answer cases.
- Property tests prove every participant appears once and every group meets its fixed capacity.
- Small randomized cases match a brute-force oracle for coverage objectives.
- Tests prove lower-priority objectives never reduce a fixed higher-priority value.
- Teach and Explore produce policy-specific results from the same semantic fixture.
- Repeated runs serialize the same partition for deterministic fixtures.

## PR 7 — Analysis orchestration

**Depends on:** PR 4, PR 5, and PR 6.

**Outcome:** the host can freeze an open room, run the complete analysis pipeline, observe status, retry safely, and switch policy without additional model calls.

### Scope

- Implement full-analysis and optimizer-only application services.
- In one transaction, lock the room, validate capacity, freeze joins/writes, clear the public error, and claim `analyzing`.
- Return `202` and execute one intentionally non-durable task in a worker thread with a fresh database session.
- Bound all OpenAI requests through one semaphore, bound solver work, and enforce the end-to-end deadline. A successful first-pass compilation makes exactly two initial calls per question containing at least one answer.
- Atomically commit `analysis_result`, `grouping_result`, and `ready`; expose no partial artifact.
- On failure, atomically set `failed` and a sanitized host-visible error.
- Preserve analysis and replace grouping during optimizer-only policy switches.
- Mark stale `analyzing` rooms failed on single-process startup.
- Add host analysis, progress, failure, retry, and policy-switch UI states.

### Not included

Durable queues, multiple workers, scheduled retries, or publication.

### Tests and merge gate

- State/concurrency tests prove a single analysis claim and an immutable response snapshot.
- Invalid capacity returns `409` and leaves the room `open`.
- Failure never exposes a new partial artifact; successful results and `ready` commit together.
- Failure injection in either semantic branch commits no question-level or room-level partial artifact.
- Optimizer-only switching makes zero provider calls and preserves the analysis artifact byte-for-byte.
- Full-analysis call-count tests prove two initial requests per non-empty question, one repair and one transport-retry allowance per branch, and the absolute six-request ceiling per non-empty question.
- Startup recovery changes stale `analyzing` rooms to `failed`.
- Playwright runs analysis with recorded fixtures and displays polling transitions through `ready` and `failed`.

## PR 8 — Group review, publication, and discussion agenda

**Depends on:** PR 7.

**Outcome:** the host can audit and publish a grouping, and each participant receives only their own actionable discussion agenda.

### Scope

- Implement derived group diagnostics from immutable questions, analysis, and partition.
- Add the host group-review API and UI: membership, unit coverage, missing units, all eligible carriers, represented families, and original-answer audit.
- Implement atomic publication from `ready` only.
- Implement participant `my-group` projection with names, question checklists, carriers, family labels, and honest missing-coverage warnings.
- Match the approved host-review and participant-agenda visual direction.
- Add copy for `feasible`, `infeasible`, and `unknown` coverage outcomes without overstating optimality.
- Stop publication/status polling at the terminal state.

### Not included

Manual group editing, chat, attendance, post-discussion assessment, or cross-room history.

### Tests and merge gate

- Derived diagnostics agree with analysis and partition on every fixture.
- Publication rejects stale or invalid partitions and is idempotent after success.
- A participant cannot enumerate other groups or retrieve other participants' raw answers.
- Host and participant projections show the same unit/family facts for the participant's group.
- Playwright completes host review → publish → two participants retrieve their distinct group views.
- Accessibility checks cover keyboard use, labels, focus, contrast, reduced motion, and narrow screens.

## PR 9 — Demo and release hardening

**Depends on:** PR 8.

**Outcome:** a clean deployment reliably demonstrates Junto's complete value proposition with realistic fixtures.

### Scope

- Finalize five-question, twenty-four-participant dynamic-programming and philosophy demo datasets.
- Add a development-only fixture loader that uses public application services, never production backdoors.
- Pin Python, npm, OR-Tools, OpenAI SDK, and demo model versions.
- Complete the multistage production image, release migration command, health/readiness checks, HTTPS cookie configuration, and one-worker startup command.
- Add join-attempt and expensive-endpoint rate limits appropriate to one process.
- Add participant-facing disclosure that display names and answers are stored and answer text is processed through the OpenAI API.
- Define and document the demo deployment's room-data retention and deletion procedure.
- Add operational notes for interrupted analyses, provider failure, database backup, logs, and manual recovery.
- Run the complete acceptance checklist from [product.md](product.md#product-acceptance).

### Not included

Accounts, institutional compliance claims, multi-replica operation, durable jobs, or production-scale analytics.

### Tests and merge gate

- A clean environment builds, migrates, starts, and passes the end-to-end suite.
- The main 5 × 24 fixture completes within `ANALYSIS_TIMEOUT_SECONDS` and all grouping invariants pass.
- Both subject fixtures exercise coverage and family diversity without correctness-specific terminology.
- A manual live-provider run succeeds for unit generation, independent coverage classification and family clustering, and their server-side merge.
- Restart during analysis produces a recoverable `failed` room rather than partial output.
- Release review confirms no secrets in frontend assets, logs, repository history, or image layers.
- Two independent reviewers complete the host and participant demo scripts from a fresh browser.

## Demo script

The final demonstration should prove one idea clearly: Junto groups from the semantic distribution of answers, not from names or random assignment.

1. Create or load a five-question room.
2. Show subject-neutral, host-approved coverage units.
3. Join approximately twenty-four fixture participants with visibly complementary answers.
4. Start analysis and explain that the model classifies coverage and clusters families independently, while only the optimizer forms groups.
5. Review one group whose members collectively cover units no individual covered alone.
6. Switch from Teach to Explore and show a changed partition with no additional provider calls.
7. Publish and show the participant agenda, including an honest missing-unit warning if the chosen fixture demonstrates partial coverage.

Do not spend demo time on account systems, realtime transport, database internals, or claims that Junto has already proven learning outcomes.

## Definition of MVP complete

The implementation is complete only when PR 9's gate and every acceptance criterion in [product.md](product.md#product-acceptance) pass on a clean deployment. A polished mockup, isolated optimizer notebook, or model prompt demo is not the shipped application.
