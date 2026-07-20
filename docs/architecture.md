# Architecture

## System boundary

Junto is one browser application, one FastAPI application process, one PostgreSQL database, one configured semantic
provider, and an in-process OR-Tools optimizer. It deliberately avoids accounts, browser-to-database access, WebSockets,
a queue, and a second backend runtime.

```text
Browser
  React + TypeScript + Vite + CSS Modules
  feature pages, typed fetch client, ordinary polling
                    |
                    v
FastAPI application
  Pydantic HTTP contracts
  signed room capabilities + CSRF
  room workflow + bounded reference extraction
  semantic compiler -> coverage-first CP-SAT
       |                              |
       v                              v
PostgreSQL                    OpenAI Responses API
six relational tables        two independent structured calls/question
+ two room-local JSON artifacts
```

`placeholder`, `recorded`, `openrouter`, and `openai` are explicit engine modes. The latter three use the real
optimizer; `placeholder` is a labelled capacity-only development adapter. OpenRouter uses a server-owned pinned model
pool and is development-only. Production still refuses to start without PostgreSQL and the live OpenAI mode.

## Frontend

```text
frontend/src/
  api/                 same-origin HTTP client and room endpoints
  domain/              TypeScript wire and UI types
  components/
    layout/            shared page shell
    system/            error and application boundaries
    ui/                reusable controls and state components
  features/
    home/              create-or-join entry
    host/create/       material-first authoring sequence
    host/room/         lobby, progress, analysis, and all groups
    participant/join/  invite disclosure and display-name entry
    participant/room/  waiting, questionnaire, review, and own agenda
  hooks/               countdown, polling, connectivity, document title
  styles/              tokens and global rules
```

Feature pages coordinate page state and API calls. `api/` owns transport, `domain/` owns shared shapes, and reusable UI
components do not reach into room endpoints. Backend Pydantic schemas are the wire authority; TypeScript mirrors them
and the frontend build catches drift.

Browser routes are:

| Route             | Purpose                                        |
| ----------------- | ---------------------------------------------- |
| `/`               | Create-or-join entry                           |
| `/create`         | Host authoring flow                            |
| `/host/:roomId`   | Host room lifecycle and all-group result       |
| `/join/:joinCode` | Participant disclosure and name entry          |
| `/room/:roomId`   | Participant questionnaire and own-group agenda |

The UI follows [DESIGN.md](../DESIGN.md): a white academic canvas, restrained green for state and action, conventional
controls, ruled lists, clear hierarchy, and no decorative AI styling. CSS Modules localize feature rules without a
utility-framework build layer.

## Backend

```text
backend/junto/
  api/           routes, Pydantic schemas, role-specific presenters
  access/        session grants, CSRF, origins, limits, headers, telemetry
  services/      room use cases, authoring assistance, analysis orchestration, scheduling, extraction
  domain/        room entities, workflow errors, capacity seam
  engine/        provider adapter, prompts, compiler, artifacts, optimizer
  repositories/  repository protocol, memory adapter, PostgreSQL adapter
  persistence/   SQLAlchemy models, mappers, engine/session construction
  config.py      validated environment configuration
  main.py        dependency assembly and SPA serving
```

Dependency direction stays inward:

- routes translate HTTP and enforce grants; they do not own workflow rules;
- services coordinate state transitions through `RoomRepository`;
- engine modules accept typed inputs and do not depend on FastAPI;
- presenters derive only the projection allowed for the caller;
- persistence mappers translate the room aggregate without leaking ORM records inward;
- `main.py` chooses adapters from explicit settings.

Tests can inject a clock, scheduler, repository, extractor, provider, optimizer, or complete analysis pipeline.

Development may also compose a synthetic-classroom service beside the room workflow. It replaces only the simulated
lobby roster in one transaction and later commits an entire generated answer matrix in one answering transaction. The
local patterned provider is network-free. The OpenRouter provider batches students, validates exact identifiers, denies
provider data collection, and uses only the configured pinned model pool. Neither path changes the persistence model.

## Runtime paths

### Authoring and collection

```text
React form
  -> typed API call
  -> route + room grant + CSRF
  -> RoomService
  -> row-locked repository transaction
```

Material uploads are bounded before Starlette can spool an unbounded multipart body. The extractor also bounds raw
bytes, PDF page count, DOCX expanded archive size, and extracted characters before saving metadata and normalized text.
Original file bytes are discarded.

AI-assisted authoring is deliberately outside the room aggregate because it can run before a room exists:

```text
uploaded file or pasted reference + complete browser draft
  -> multipart POST /api/authoring/suggestions + CSRF
  -> bounded extraction when a file is supplied
  -> AuthoringService
  -> OpenAI Responses API structured output (store=false, no tools)
  -> apply only the requested question or coverage target in browser state
  -> host review and ordinary room creation
```

The request is session-scoped, per-source rate-limited, and never grants room access. It contains the activity title,
the selected target/index, every current prompt and coverage-unit row, and extracted or pasted reference text. It
contains no room, participant, answer, invite-code, grouping, or solver data. Suggestions are transient and do not write
to the repository; persistence begins only when the host creates the activity through the normal room endpoints.

Opening the lobby freezes authoring. Starting validates a feasible capacity partition, freezes ordered cohort IDs,
records UTC `startedAt` and `deadlineAt`, and schedules the deadline callback. Browser countdowns derive from
`serverTime`, `deadlineAt`, and `remainingSeconds`; the server remains authoritative.

Answer navigation performs an ordinary `PUT` and waits for a receipt. Small role-specific views are polled while state
is non-terminal. There is no collaborative document, presence channel, or realtime protocol.

### Coverage-aware analysis

Collection is claimed once by all submissions, deadline, or host action:

```text
frozen room aggregate
  -> build one input batch per question
  -> coverage classification ----------+
  -> independent family clustering ----+-> validate and merge by participant ID
  -> immutable SemanticArtifact
  -> CoverageFirstOptimizer
  -> immutable GroupingArtifact
  -> atomic artifact storage + published state
```

The coverage call receives the prompt, relevant reference text, approved units, opaque participant IDs, and non-empty
answers. The family call receives only the prompt, opaque IDs, and answers. It cannot see units, references, or coverage
results. Display names, join codes, cookies, group sizes, and tentative groups are not sent to either call.

The OpenAI adapter uses the Responses API with Pydantic Structured Outputs, `store=false`, no tools, explicit request
timeouts, no SDK retries, and one compiler-owned transient retry. Coverage and family outputs each receive one bounded
repair opportunity after schema or domain failure. A process-wide limiter bounds provider concurrency.

All-empty questions skip provider calls and receive explicit empty assignments. Evidence quotes are validated as literal
substrings in memory, then discarded; the stored semantic artifact contains only family and covered-unit IDs.

The CP-SAT optimizer interprets no prose. It fixes balanced capacities, tests complete-coverage feasibility, optimizes
normalized coverage lexicographically, then applies Teach or Explore objectives. It always retains a deterministic
capacity-valid fallback and distinguishes proven infeasibility from unknown/time-limited search.

Only a complete artifact pair is published. A failed attempt clears both artifacts, stores a sanitized failure, and
allows a bounded retry against the same frozen cohort and saved responses.

### Placeholder and recorded modes

- `placeholder` skips the semantic pipeline and partitions stable join order into valid balanced groups. Its wire result
  says `generationMode: "placeholder"` and contains no coverage or solver claims.
- `recorded` resolves reviewed semantic fixture outputs without network access, passes the resulting validated artifact
  to the real optimizer, and publishes the normal coverage-aware projection.
- `openai` uses the live provider adapter and otherwise follows the same compiler, optimizer, persistence, and
  presentation paths.
- `openrouter` uses strict JSON-schema Chat Completions, denies provider data collection, and uses a server-owned pinned
  model pool; it is development-only.

## Persistence

The product model has four core collaboration records: room, question, participant, and response. PostgreSQL uses six
normalized tables because coverage-unit ordering and extracted reference material have their own constraints and
lifecycle:

| Table                 | Purpose                                                                   |
| --------------------- | ------------------------------------------------------------------------- |
| `rooms`               | workflow, timing, policy, group bounds, analysis metadata, JSON artifacts |
| `questions`           | ordered prompts and optional question-specific reference text             |
| `coverage_units`      | ordered host-approved units scoped to a question                          |
| `reference_materials` | upload metadata and extracted text; no source bytes                       |
| `participants`        | room-local name, browser-session nonce, cohort position, submission time  |
| `responses`           | sparse participant-question answer rows                                   |

`analysis_result` and `grouping_result` are versioned JSONB columns on `rooms`. They are generated together, consumed
together, and replaced together, so normalizing response families, assignments, groups, or diagnostics would add
synchronization cost without serving a current cross-room query. Host and participant diagnostics are derived at read
time from the artifact pair.

There are no user, teacher, profile, OAuth, job, analysis-version, group-member, or unit-explainer tables.

Every mutation locks the parent room row with `SELECT ... FOR UPDATE`, hydrates the aggregate, applies one service
operation, then commits the room and children together. This serializes cohort freeze, answer/deadline races, final
submission, analysis claims, and publication. Database constraints enforce join-code uniqueness, room-scoped foreign
keys, valid state values, sparse non-empty responses, ordering, and cascades.

Alembic owns schema changes and is run as a separate release operation. Readiness probes PostgreSQL without calling the
model or solver. Development may omit the database URL and use the thread-safe memory adapter; production cannot.

## Access and privacy

Starlette signs one HTTP-only, SameSite=Lax room-session cookie. It contains a random browser nonce, CSRF value, and a
bounded list of room IDs with host and/or participant grants. It contains no names, answers, material, join codes, or
group content. The cookie is signed, not encrypted.

All mutations require the matching `X-CSRF-Token`. A browser-session nonce plus a database uniqueness constraint makes
repeated joins to the same room idempotent. Missing room grants return caller-safe not-found responses. Trusted-origin
middleware rejects foreign browser mutations; production requires explicit HTTPS origins and secure cookies.

Public invite lookup exposes only title, duration, question count, lobby state, and analysis mode. Host projections
include authoring data, roster, progress, all groups, and the coverage audit. Participant projections include their own
identity, prompts, their own answers, and only their published group. Extracted reference text has no public API field.

Synthetic answer generation receives only the title, participant-visible prompts, opaque participant IDs, and synthetic
behavioral profiles. It never receives coverage units, question reference material, or uploaded extracted text. Its
endpoints are host-scoped, CSRF-protected, and disabled in production.

Request telemetry replaces UUIDs and invite codes with route templates and excludes bodies, cookies, model inputs, and
database values. One-process sliding-window limits cover anonymous room creation, authoring suggestions, joining, and
analysis/retry. These controls are suitable for the documented demo boundary, not a general anti-abuse service.

## Process and deployment model

The production image builds the SPA in a Node stage, installs a pinned Python runtime closure, then runs FastAPI as a
non-root user without Node. FastAPI serves `frontend/dist` and returns `index.html` for browser routes while unknown
`/api` paths remain JSON 404 responses.

Analysis and deadline callbacks run inside the one FastAPI process. PostgreSQL preserves rooms, deadlines, answers, and
published artifacts across restarts; startup maintenance marks stale `analyzing` rooms as `failed` and deletes expired
rooms. In-flight provider execution itself is not durable, so the start script enforces one web worker and the host
retry is the recovery path.

Add infrastructure only for a demonstrated requirement:

- a durable queue/worker before horizontal web workers or guaranteed in-flight analysis recovery;
- SSE or WebSockets only if classroom polling becomes material;
- accounts only for saved cross-device history;
- normalized semantic tables only for real cross-room analytics.

Operational configuration, migrations, retention, recovery, and release checks are in [operations.md](operations.md).
