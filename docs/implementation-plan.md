# Implementation and PR plan

## Purpose

This plan moves Junto from the current end-to-end prototype to a durable, coverage-aware application in reviewable increments. Each PR must leave the repository runnable and must not describe an absent dependency as working.

The current slice deliberately proves the room experience before introducing OpenAI, OR-Tools, or PostgreSQL.

## Current checkpoint

| Area | Repository state |
|---|---|
| React/TypeScript/Vite/Tailwind shell and routes | implemented |
| Host material-first authoring flow | implemented |
| Lobby, frozen cohort, and server-owned timer | implemented |
| One-question participant flow, autosave, review, submit | implemented |
| Signed room sessions, CSRF, and role projections | implemented |
| TXT/MD/PDF/DOCX extraction | implemented |
| Deterministic capacity-valid placeholder groups | implemented |
| Automated backend coverage | implemented |
| Frontend build, interaction tests, and browser QA | stabilization gate |
| PostgreSQL persistence | not implemented |
| OpenAI semantic compiler | not implemented |
| OR-Tools optimizer | not implemented |
| Production deployment and operations | not implemented |

The memory repository is a conscious prototype adapter. Restarting FastAPI deletes every room and is expected until the persistence PR lands.

## Dependency path

```text
Current first slice
        |
        v
PR 1: stabilize and prove the room workflow
        |
        v
PR 2: durable PostgreSQL repository
        |
        +-------------------+
        v                   v
PR 3: semantic compiler   PR 4: CP-SAT optimizer
        \                   /
         \                 /
          v               v
        PR 5: engine orchestration
                  |
                  v
        PR 6: deployment and demo hardening
```

PR 3 and PR 4 may proceed in parallel after their shared typed artifact contract is fixed. PR 5 integrates both only after each passes fixture tests independently.

## Rules for every PR

### Scope discipline

- State the user-visible outcome and explicit non-goals.
- Change one architectural seam at a time.
- Keep transport, application rules, domain logic, and adapters separate.
- Update the canonical docs and Pydantic/TypeScript shapes in the same PR as a contract change.
- Preserve accountless room-scoped access unless a later product decision explicitly changes it.
- Never add a fake provider call, fake progress percentage, fake solver result, or artificial delay for appearance.

### Required checks

Backend changes:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check junto tests
.\.venv\Scripts\python.exe -m mypy junto
```

Frontend changes:

```powershell
cd frontend
npm run typecheck
npm test
npm run build
```

Cross-page behavior requires a browser test or a documented manual run until the browser suite is established. UI changes include a desktop and narrow-viewport check against [DESIGN.md](../DESIGN.md).

### Security and privacy gate

- Every mutation validates CSRF, role grant, room ownership, room state, and input bounds.
- Participant projections never expose material, coverage units, all groups, or another participant's answer.
- Logs and public errors contain no session contents, answer text, extracted material, provider prompt, or secret.
- User and model text is rendered as text, never trusted HTML.
- Expensive and uploaded inputs are bounded before processing.

### Merge evidence

Every PR description records:

1. implemented outcome;
2. affected contract sections;
3. commands and results;
4. one screenshot or short recording for a visible flow;
5. known limitations that remain intentionally deferred.

## PR 1 - Stabilize the first slice

**Outcome:** a developer can prove the complete room flow locally on desktop and a narrow viewport without an external service.

### Scope

- Finish host and participant state rendering for all six room states.
- Keep questionnaire navigation save-before-leave and make save failure recoverable.
- Synchronize countdown display from `serverTime`, `deadlineAt`, and `remainingSeconds`.
- Verify the authoring sequence uploads only supported material and supplies coverage units for every question.
- Reconcile TypeScript DTOs with current Pydantic responses; remove unused client calls for endpoints the backend does not expose.
- Cover host lobby, cohort start, answer save, final submit, deadline, early finish, failure, all-groups, and own-group projections.
- Add accessible names, live save status, keyboard focus, reduced-motion behavior, 44-pixel touch targets, and wrapped question navigation.
- Validate direct browser-route fallback after a production frontend build.
- Keep placeholder provenance visible in technical payloads without turning the interface into an AI status show.

### Not included

PostgreSQL, OpenAI calls, semantic coverage, response families, OR-Tools, accounts, WebSockets, or deployment claims.

### Merge gate

- Backend tests, frontend tests, type checking, and build pass from a clean install.
- A browser completes create -> upload -> author -> lobby -> three participants -> timed answers -> submit -> published groups.
- All-submitted, deadline, and early-host-finish paths each claim one grouping run.
- Participant access to `/groups`, another participant identity, and cross-room mutations fails.
- Restart behavior is called out as destructive prototype behavior in README and UI/developer notes.
- Visual review finds no chips, avatar pills, gradients, glass, decorative card grids, fake AI progress, or mobile horizontal overflow.

## PR 2 - Durable PostgreSQL repository

**Depends on:** PR 1.

**Outcome:** rooms survive process restarts without changing the browser workflow.

### Scope

- Implement the existing `RoomRepository` protocol with PostgreSQL, SQLAlchemy, psycopg, and Alembic.
- Design the minimal durable representation for rooms, questions, participants, responses, room-level material metadata/text, frozen cohort, and grouping result.
- Preserve aggregate transaction boundaries for cohort freeze, answer-versus-deadline races, final submission, analysis claim, and result publication.
- Add unique join-code handling, room-scoped foreign keys, ordered questions, cascades, checks, and useful indexes.
- Move secrets and connection values into validated environment configuration.
- Add startup migration instructions and integration-test fixtures using a real PostgreSQL instance.
- Decide material retention explicitly; do not silently retain original upload bytes if extracted text is sufficient.

### Not included

Semantic analysis, optimizer logic, accounts, reusable activities, normalized cross-room analytics, or a separate worker.

### Merge gate

- Migration upgrades an empty database and validates downgrade behavior.
- A room survives an application restart at each non-transient state.
- Concurrent start, save, submit, deadline, and analysis claims preserve current invariants.
- The same API and browser tests pass against memory and PostgreSQL adapters.
- Deleting or expiring a room removes its room-scoped personal data according to the documented retention rule.

## PR 3 - OpenAI semantic compiler

**Depends on:** PR 2 and the artifact schemas in [engine.md](engine.md).

**Outcome:** a frozen answer set compiles into validated per-answer coverage and independent response families without selecting groups.

### Scope

- Add a narrow provider interface and the official OpenAI SDK behind it.
- Pin a model configuration that supports the required structured output schema.
- For each question, make coverage classification and response-family clustering independent operations over opaque participant IDs.
- Give coverage classification the prompt, approved coverage units, relevant extracted material, and answers.
- Give family clustering the prompt and answers only; do not pass coverage units or coverage output.
- Validate every participant exactly once, known unit IDs only, bounded family labels, null-family answers, and literal answer evidence where required by the engine contract.
- Merge the two validated results by participant ID in application code.
- Skip provider calls for all-empty questions and create explicit empty assignments locally.
- Add request timeouts, bounded concurrency, bounded repair behavior, privacy-safe telemetry, and deterministic recorded fixtures.
- Store only validated semantic artifacts; never store provider chain-of-thought.

### Not included

Group formation, CP-SAT, policy objectives, live provider calls in CI, automatic unit generation, or claims that semantic judgments are always correct.

### Merge gate

- Reviewed programming, philosophy, history, and design fixtures demonstrate subject-neutral coverage units.
- Contract tests reject unknown IDs, missing participants, duplicate assignments, unsupported coverage, cross-branch fields, and malformed family indices.
- Independence tests prove a family result cannot change coverage and a coverage result cannot change family membership.
- Logs, exceptions, and recorded HTTP metadata contain no answer or material text.
- A manual live-provider evaluation reports accuracy disagreements honestly and is not substituted for automated fixtures.

## PR 4 - Coverage-first OR-Tools optimizer

**Depends on:** PR 2 and the artifact schemas in [engine.md](engine.md). May run in parallel with PR 3.

**Outcome:** a validated semantic fixture produces a deterministic capacity-valid partition that prioritizes coverage before the selected policy.

### Scope

- Replace the placeholder capacity slicer behind `GroupingService` with an OR-Tools CP-SAT implementation accepting typed semantic artifacts.
- Preserve feasible group-count selection and balanced fixed capacities.
- Implement participant assignment, per-group unit coverage, and honest full-coverage feasibility status.
- Optimize coverage lexicographically before any policy-specific objective.
- Implement Teach Each Other and Explore Different Approaches without granting coverage through family membership.
- Set deterministic ordering, seed, search-worker count, time budget, and canonical group labels.
- Return feasible, infeasible, unknown, and time-limited outcomes without overstating optimality.
- Derive diagnostics from the final partition and semantic artifact rather than trusting model-authored summaries.

### Not included

OpenAI calls, HTTP orchestration, manual group editing, learning-outcome claims, or publication UI.

### Merge gate

- Property tests prove exactly-once membership and capacity validity.
- Small random fixtures match a brute-force oracle for coverage objectives.
- Lower-priority objectives never reduce a fixed higher-priority coverage value.
- Teach and Explore can differ while using the same semantic artifact.
- Proven infeasible and time-limit/unknown cases use distinct, honest language.
- Repeated deterministic fixtures serialize the same partition.

## PR 5 - Integrate the real engine

**Depends on:** PR 3 and PR 4.

**Outcome:** collection closes into real semantic compilation and coverage-aware grouping while preserving the established room experience.

### Scope

- Replace the placeholder service with compiler -> validation -> optimizer orchestration.
- Atomically freeze the response snapshot and claim one analysis run.
- Persist the validated semantic artifact and final grouping artifact without exposing partial output.
- Drive analysis labels from actual backend stages; expose no percentage unless measured work supports it.
- Keep `analyzing -> published | failed` and automatic release unless product testing establishes a concrete need for host review.
- Return engine provenance and diagnostics separately from placeholder DTOs.
- Show the host capacity, achieved coverage, missing units, represented families, and original-answer audit needed to understand a result.
- Show participants only their group and a concise per-question discussion agenda.
- Add a bounded retry path for failed non-durable analysis without duplicating results.

### Not included

Durable queues, multiple workers, cross-room history, participant chat, grading, or institutional integration.

### Merge gate

- One frozen snapshot produces one atomic artifact pair and one publication.
- Failure in either semantic branch or the optimizer exposes no partial group result.
- Participant diagnostics agree with the host projection but reveal no other group or raw answer.
- Recorded fixtures complete the browser flow without network access.
- A manual live run demonstrates complementary coverage in at least two subject areas and labels model uncertainty honestly.

## PR 6 - Deployment and demo hardening

**Depends on:** PR 5.

**Outcome:** one documented deployment can run the education-track demonstration reliably without claiming institutional production readiness.

### Scope

- Add a reproducible multistage image and one-process startup command.
- Run PostgreSQL migrations as an explicit release operation.
- Configure HTTPS-only cookies, strong secrets, trusted origins, upload and request limits, and rate limiting for join and analysis paths.
- Add structured privacy-safe logs, health/readiness checks, provider and solver timing, and sanitized failure reporting.
- Define room retention, deletion, backup, and interrupted-analysis recovery.
- Add participant disclosure for stored names/answers and external model processing before any live provider deployment.
- Build reviewed classroom-sized fixtures and a development-only loader through normal application services.
- Run accessibility, responsive, failure, and load checks for the supported 60-participant envelope.

### Not included

Accounts, LMS integration, compliance certification, multi-region availability, production-scale analytics, or proof that grouping improves learning.

### Merge gate

- A clean environment builds, migrates, starts, and passes the end-to-end suite.
- A classroom fixture completes within the configured analysis budget without violating any grouping invariant.
- Restart and provider-failure drills recover or fail safely without partial publication.
- No secret, material, response text, or session value appears in frontend assets or logs.
- Two people can run the demo script from fresh browsers using only the documentation.

## Demo script

The first-slice demo should prove the workflow honestly:

1. Upload optional material and author subject-neutral coverage units.
2. Create the invite and join from several participant sessions.
3. Start once to show the frozen roster and shared timer.
4. Answer one question per page and show autosave plus final review.
5. Submit the cohort and show automatic placeholder groups by role.
6. State plainly that this build uses deterministic capacity grouping and that semantic compilation and optimization are next.

After PR 5, replace step 6 with a comparison showing how complementary answer coverage changes the partition. Do not spend demo time on accounts, WebSockets, database internals, or unproven learning-outcome claims.

## Completion definitions

The **first slice** is complete when PR 1's gate passes.

The **coverage-aware hackathon product** is complete when PR 5's gates pass with recorded fixtures and one reviewed live-provider run.

The **deployable demo** is complete only when PR 6's operational, privacy, and clean-environment gates pass. None of these labels means Junto has proven improved learning; that requires a separate study with a defensible comparison and outcome measure.
