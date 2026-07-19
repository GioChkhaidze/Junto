# Architecture

## Goal

The first slice favors one understandable web application, explicit module boundaries, and a complete room workflow. It avoids accounts, browser-to-database access, realtime infrastructure, durable jobs, and premature service separation.

This document distinguishes the code that exists now from the adapters planned for the coverage-aware product.

## Implemented system

```text
Browser
  - React + TypeScript
  - Vite and Tailwind CSS
  - feature pages and reusable UI components
  - typed fetch client
  - ordinary forms and short polling
          |
          v
FastAPI application
  - JSON routes and Pydantic schemas
  - signed room-session access and CSRF checks
  - room workflow service
  - reference text extraction
  - in-process deadline scheduler
  - deterministic grouping placeholder
          |
          v
RoomRepository protocol
          |
          v
Thread-safe in-memory implementation
```

The current repository has no external database, model call, optimizer process, queue, WebSocket server, or second backend runtime.

## Planned replacements

The important behaviors sit behind narrow seams:

```text
RoomRepository        InMemoryRoomRepository -> PostgreSQL repository
GroupingService       placeholder            -> semantic compiler + CP-SAT optimizer
ReferenceTextExtractor default implementation remains replaceable for testing
Scheduler             thread timer           -> durable scheduling only if required
```

PostgreSQL, the OpenAI API, and OR-Tools are the target stack, but none is currently wired into the runtime. Adding them should replace adapters rather than change browser routes or room behavior unnecessarily.

## Frontend structure

```text
frontend/src/
  api/                 same-origin HTTP and room endpoint functions
  domain/              TypeScript DTOs and room/activity types
  components/
    layout/            application shell
    system/            error boundary
    ui/                reusable controls and state components
  features/
    home/              entry page
    host/create/       sequential room authoring
    host/room/         lobby, progress, analysis, and all groups
    participant/join/  code and display-name entry
    participant/room/  waiting, questionnaire, review, and own group
  hooks/               countdown, polling, connectivity, and document title
  styles/              design tokens and global rules
```

Feature pages coordinate API calls and page state. `api/` owns transport details, `domain/` owns shared TypeScript shapes, and reusable components do not perform room requests. Backend Pydantic models remain the wire authority; the hand-maintained TypeScript DTOs mirror them and are checked by the frontend build. OpenAPI type generation is a future hardening step.

Browser routes are:

| Route | Purpose |
|---|---|
| `/` | Create-or-join entry |
| `/create` | Host authoring sequence |
| `/host/:roomId` | Host lobby and room lifecycle |
| `/join/:joinCode` | Participant name entry |
| `/room/:roomId` | Participant waiting, answers, and own group |

The UI follows [DESIGN.md](../DESIGN.md). CSS modules keep feature styling local; Tailwind supplies the build integration and utilities where useful. Shared colors, spacing, typography, focus, and motion rules live in the style layer.

## Backend structure

```text
backend/junto/
  api/           HTTP translation, schemas, and role-specific presenters
  access/        signed-session grants and CSRF verification
  services/      room use cases, reference extraction, and scheduling
  domain/        entities, errors, capacity logic, and grouping interface
  repositories/  repository protocol and current memory adapter
  config.py      bounded runtime settings
  main.py        dependency assembly and application shell
```

Dependency direction is inward:

- routes translate HTTP into application calls and never own workflow rules;
- services coordinate state transitions through the repository protocol;
- domain code has no FastAPI, browser, or storage dependency;
- presenters expose only the projection allowed for the caller;
- `main.py` chooses concrete adapters.

This arrangement lets tests inject a clock, scheduler, repository, extractor, or grouping implementation without running a server or calling an external system.

## Runtime paths

### Draft authoring

```text
React authoring page
  -> typed API function
  -> FastAPI route + host grant + CSRF check
  -> RoomService
  -> RoomRepository transaction
```

Material upload adds one real extraction step before storing the room aggregate:

```text
multipart file
  -> request-body middleware bound before multipart spooling
  -> 5 MiB bounded file read
  -> PDF page / DOCX expanded-size guard
  -> extension-specific TXT/MD/PDF/DOCX parser
  -> normalized readable text
  -> attachment metadata + extracted text in the room aggregate
```

The original file bytes are not retained by the current repository. Uploaded metadata and extracted text disappear with every other room value on process restart.

### Timed collection

Starting from `lobby` validates capacity, freezes cohort IDs, records UTC `startedAt` and `deadlineAt`, and schedules an in-process deadline callback. Browser countdowns use `serverTime`, `deadlineAt`, and `remainingSeconds`; client clocks are display helpers, not authority.

Answer navigation performs an ordinary `PUT` and waits for its receipt. Polling retrieves small role-specific status projections. There is no shared document, presence channel, chat, WebSocket, or database-change subscription.

### Analysis placeholder

Collection is claimed once by one of three triggers:

- every frozen participant submitted;
- the server deadline became due;
- the host ended collection early.

The room moves to `analyzing`. An in-process scheduler advances two descriptive phases and calls `GroupingService`. The default implementation ignores questions and answers, calculates feasible balanced capacities, partitions stable join order, commits the complete result, and moves directly to `published`.

The default stage delay is zero. The UI must not invent progress percentages, provider activity, or optimizer work. If grouping raises an exception, the room becomes `failed` with a sanitized message.

## State and transaction model

The memory repository stores a complete `Room` aggregate and protects copies with one re-entrant lock. Its transaction context copies the aggregate, applies a service operation, then replaces the stored value. This is sufficient for deterministic local tests and single-process prototype behavior.

It is not durable and cannot coordinate multiple processes. The next persistence adapter must preserve the same service-level atomic boundaries with PostgreSQL transactions and row locking, especially:

- start and cohort freeze;
- answer save versus deadline/analysis claim;
- single final submission;
- analysis result commit and publication.

Until that adapter exists, run one FastAPI process and treat every restart as deleting all rooms.

## Room-scoped access

FastAPI uses Starlette's signed session cookie. The cookie contains a CSRF secret and bounded grants similar to:

```json
{
  "nonce": "opaque-browser-session-value",
  "csrf": "opaque-random-value",
  "grants": [
    {
      "roomId": "room-uuid",
      "host": true,
      "participantId": "participant-uuid"
    }
  ]
}
```

The browser-session nonce makes joining one room idempotent even when the browser repeats a request. The cookie is signed, not encrypted, so it contains identifiers only: never names, answers, material, join codes, or group content. Mutations require the matching `X-CSRF-Token`. Missing grants return caller-safe not-found responses so UUID knowledge alone grants nothing.

Development generates a random process-local signing secret and uses non-secure cookies on localhost. `JUNTO_ENV=production` requires a supplied secret of at least 32 characters and enables secure cookies by default; startup fails if the secret is missing or weak. HTTPS remains a deployment requirement. This capability model is convenient and accountless but is not cross-device recovery.

## Data exposure

- Host projections include draft questions, coverage units, material metadata, roster, progress, and all published groups.
- Participant projections include public room timing, prompts, that participant's answers and submission state, then only that participant's published group.
- Participants do not receive extracted reference text, coverage units, other answers, all-group enumeration, or host errors.
- Model-provider data handling does not yet exist because there is no provider integration.

## Development and built serving

During development, Vite runs on port `5173` and proxies `/api` to Uvicorn on port `8000`.

For a built application, `npm run build` writes `frontend/dist`. FastAPI serves its assets and returns `index.html` for browser routes. API paths are excluded from the SPA fallback so unknown API requests remain JSON `404` responses.

Node.js is not needed at runtime once assets are built. The current repository does not yet include a production database, migrations, container deployment, backup strategy, rate limiting, or operational recovery.

## Scaling and durability triggers

Add infrastructure only for a demonstrated requirement:

- PostgreSQL is required before rooms must survive restarts or multiple app processes.
- A durable queue is required before interrupted analyses need retries across deployments.
- Server-sent events or WebSockets are justified only if status polling becomes material.
- Accounts are justified only when people need saved history or cross-device room recovery.
- Normalized semantic tables are justified only when cross-room reporting needs them.

The intended architecture remains one frontend, one FastAPI application, one PostgreSQL database, one model provider, and one optimizer library.
