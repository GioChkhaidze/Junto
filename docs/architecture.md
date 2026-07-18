# Architecture

## Goals

The hackathon architecture optimizes for one coherent deployment, explicit boundaries, and a complete room workflow. It deliberately avoids institutional identity, browser-to-database access, realtime infrastructure, and a durable job system.

The canonical product contract is [product.md](product.md). Exact storage and HTTP contracts are in [contracts.md](contracts.md).

## System

```text
Browser
  ├── React + TypeScript application built by Vite
  ├── Tailwind CSS design system
  ├── ordinary fetch requests and two-second polling
  └── signed, HTTP-only room-session cookie
          │
          ▼
FastAPI application
  ├── serves compiled Vite assets
  ├── exposes the JSON API
  ├── enforces room-scoped access and state transitions
  ├── reads and writes PostgreSQL
  ├── calls the OpenAI Responses API
  ├── validates artifacts with Pydantic
  ├── runs OR-Tools CP-SAT
  └── runs one non-durable in-process analysis task
          │
          ▼
PostgreSQL
  ├── four relational tables
  └── room-local JSON artifacts
```

Deployment contains one application container, one PostgreSQL database, and the external OpenAI API. Node.js is used only to build the frontend; it is not a production runtime.

## Technology

### Frontend

- React and TypeScript;
- Vite;
- Tailwind CSS;
- React Router;
- TypeScript DTOs generated from FastAPI's OpenAPI document;
- a typed `fetch` wrapper and small polling hooks;
- Vitest and React Testing Library;
- Playwright for end-to-end flows.

The frontend owns rendering and transient interaction state. It never talks directly to PostgreSQL or the model provider.

FastAPI returns `index.html` for direct browser navigation to application routes such as `/create`, `/host/:roomId`, and `/join/:joinCode`. `/api` and built-asset paths are excluded from that fallback so API errors remain JSON and missing assets remain real `404` responses.

### Application

- Python 3.12;
- FastAPI and Starlette;
- Pydantic 2;
- SQLAlchemy 2 and psycopg 3;
- Alembic;
- Uvicorn;
- pytest, Ruff, and mypy.

FastAPI owns authorization, validation, room transitions, persistence, semantic orchestration, optimization, and static-file delivery.

### Engine

- the official OpenAI Python SDK and Responses API behind a narrow compiler interface;
- Structured Outputs generated from the same Pydantic schemas used for validation;
- stateless requests with `store: false`, no tools, and no response chaining;
- OR-Tools CP-SAT;
- recorded model fixtures in automated tests.

The API choice follows OpenAI's current [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and [Python SDK](https://developers.openai.com/api/docs/libraries#install-an-official-sdk) guidance. The model identifier remains configuration, is checked for Structured Outputs support, and is pinned for the demo rather than silently tracking a changing alias.

Semantic and optimizer modules do not import FastAPI or frontend concerns. They accept typed values and return typed artifacts so tests can call them directly.

Inside the semantic boundary, a coverage classifier and a family clusterer depend only on the provider interface. A question compiler coordinates them, validates each result independently, and performs the participant-ID merge. Neither classifier imports or calls the other.

## Runtime paths

### Browser request

```text
React page
  → typed API client
  → FastAPI route
  → capability and state checks
  → application service
  → repository
  → PostgreSQL
```

Routes should translate HTTP to application commands. Business rules belong in services or domain functions, not route handlers.

### Analysis request

```text
POST /api/rooms/{id}/analysis
  → atomic room transition to analyzing
  → HTTP 202
  → synchronous workflow in a worker thread
      → fresh database session
      → per-question coverage classification and family clustering
          → two independent Structured Outputs requests
          → one shared OpenAI-request concurrency bound
          → validation and merge by opaque participant ID
      → artifact validation
      → CP-SAT optimization
      → atomic artifact write and transition to ready
```

Analysis is intentionally non-durable for the hackathon. A process restart can interrupt it, but cannot publish partial output. Startup recovery marks stale `analyzing` rooms as `failed`; retry safely replaces room-local artifacts.

The room-row locking and artifact commit rules are normative in [contracts.md](contracts.md#freeze-and-artifact-transactions). In particular, the `analyzing` transition freezes a transactionally complete response snapshot, and the transition to `ready` occurs in the same transaction that writes both final artifacts.

Run one Uvicorn process. A durable queue and separate workers are introduced only after restart tolerance or concurrent analysis volume becomes a demonstrated requirement.

## Room-session access

Junto uses Starlette's signed cookie session. The cookie contains only opaque database IDs and a CSRF secret:

```json
{
  "csrf": "random-session-value",
  "grants": [
    {
      "roomId": "room-uuid",
      "host": true,
      "participantId": "participant-uuid"
    }
  ]
}
```

The cookie is signed, not encrypted. It must contain no display names, responses, join codes, model data, or other sensitive content.

The signature, not secrecy of the UUIDs, authorizes access. There are no host-token or participant-token columns in PostgreSQL. A grant remains valid only while its referenced room or participant still exists, so deleting either record invalidates that grant on its next use.

Production cookie settings:

```text
Name = junto_session
Path = /
HttpOnly = true
Secure = true
SameSite = Lax
```

Every state-changing request must pass the signed room grant, verify the room or participant still exists, and include `X-CSRF-Token` matching the session value. The API also requires an allowed same-origin `Origin` header, falling back to `Referer` only for user agents that omit it.

The grants array contains at most one record per room and is ordered least-recently used to most-recently used. It stores at most `MAX_SESSION_ROOM_GRANTS` records; adding another evicts the oldest. A browser may hold host access, participant access, or both for one room. There is intentionally no cross-device recovery. Clearing cookies removes access to accountless rooms.

Join codes are invitations, not host credentials. Generate them from a cryptographically secure, unambiguous alphabet, check uniqueness, and rate-limit join attempts.

## Data handling

Junto is accountless and pseudonymous, not fully anonymous. It stores room-local display names and answers, and sends question text, opaque participant IDs, and answer text to OpenAI. Coverage-classification calls also receive optional host reference material and coverage units; family-clustering calls deliberately receive neither. The join page must disclose that processing and tell participants not to submit sensitive personal information.

Reference material is host-only. It can guide semantic compilation but is never returned to participant endpoints. Responses API calls set `store: false`; this disables response state storage but is not presented as a blanket zero-retention claim because account-level data controls still apply. Logs contain IDs, timings, counts, and provider request IDs—not prompts, references, answers, cookie contents, or provider payloads. See OpenAI's [data controls](https://developers.openai.com/api/docs/guides/your-data) for the provider-side policy.

Coverage evidence is transient answer text returned by the provider. The application validates it in memory, derives `coveredUnitIds`, and discards it; it is never persisted or logged. A successful first-pass analysis issues two initial provider calls for each question that has at least one non-empty answer. Each branch permits at most one repair request and one shared transport retry, for an absolute ceiling of six HTTP requests per non-empty question. Authoring-time coverage-unit generation is counted separately.

The public demo must define a short room-data retention and deletion procedure before release; [PR 9](implementation-plan.md#pr-9--demo-and-release-hardening) owns that operational decision. Junto makes no institutional privacy or compliance claim in the MVP.

## Client updates

Use ordinary requests for all mutations. Poll every two seconds for:

- participant and submission counts;
- analysis status;
- publication status.

Stop polling when the relevant state becomes terminal. Junto has no chat, shared document, presence protocol, or participant-to-participant live state, so WebSockets or database change feeds add no current value.

## Repository target

```text
junto/
├── backend/
│   ├── junto/
│   │   ├── api/
│   │   ├── access/
│   │   ├── db/
│   │   ├── domain/
│   │   ├── semantic/
│   │   ├── optimizer/
│   │   ├── services/
│   │   ├── static/          # compiled frontend in production image
│   │   ├── config.py
│   │   └── main.py
│   ├── tests/
│   ├── requirements.lock
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── routes/
│   │   └── styles.css
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.ts
├── migrations/
├── fixtures/
│   ├── dynamic_programming/
│   └── philosophy/
├── docs/
├── Dockerfile
├── docker-compose.yml
└── README.md
```

### Dependency rules

- `frontend` depends only on the HTTP contract.
- `api` may call access checks and application services.
- `services` coordinate repositories, semantic compilation, and optimization.
- `semantic` and `optimizer` are independent of HTTP and database sessions.
- `db` maps persisted records but does not contain model prompts or solver objectives.
- stored JSON schemas live with domain contracts and are validated at read and write boundaries.
- browser DTOs are generated from OpenAPI; do not hand-maintain a second copy of backend request and response schemas.

## Configuration

| Variable | Purpose | Default for development |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection | required |
| `SESSION_SECRET` | Cookie signing | required |
| `OPENAI_API_KEY` | Server-side OpenAI credential | required for live model calls |
| `OPENAI_MODEL` | Pinned Structured Outputs-capable model | required |
| `PUBLIC_BASE_URL` | Join and QR links | `http://localhost:8000` |
| `MAX_ANALYSIS_CONCURRENCY` | Concurrent OpenAI requests across both compiler call types | `3` |
| `MAX_PARTICIPANTS_PER_ROOM` | Room safety bound | `60` |
| `MAX_QUESTIONS_PER_ROOM` | Room safety bound | `8` |
| `MAX_ANSWER_CHARACTERS` | Per-answer bound | `1500` |
| `MAX_REFERENCE_CHARACTERS` | Per-question host reference bound | `8000` |
| `MODEL_TIMEOUT_SECONDS` | One provider request budget | `45` |
| `SOLVER_TIMEOUT_SECONDS` | CP-SAT portion of the analysis budget | `30` |
| `ANALYSIS_TIMEOUT_SECONDS` | End-to-end analysis budget | `120` |
| `MAX_SESSION_ROOM_GRANTS` | Recent room grants retained in the cookie | `8` |

Secrets are server-only. The frontend build receives no model or database credentials.

## Deployment

Use a multistage Docker build:

1. Node stage installs frontend dependencies with `npm ci` from `package-lock.json` and runs the Vite production build.
2. Python stage installs backend dependencies from `requirements.lock`.
3. Compiled frontend assets are copied into the FastAPI static directory.
4. The release command runs migrations before traffic reaches the new image.
5. The final image starts `uvicorn` with one worker and one application replica.

The platform must provide persistent process execution without scale-to-zero during an analysis, HTTPS, and a standard PostgreSQL connection string.

## Explicitly excluded

- Next.js or a production Node server;
- server-rendered application templates;
- Supabase Auth, Realtime, browser SDK, or RLS;
- OAuth, passwords, profiles, or permanent roles;
- Redis, Celery, or a dedicated worker;
- WebSockets or SSE;
- vector databases and custom model training;
- a multi-provider abstraction beyond the narrow interface needed for fixtures.

## Scaling triggers

| Observed need | Addition |
|---|---|
| Interrupted jobs are unacceptable | Durable queue and worker |
| Polling traffic becomes material | SSE or WebSockets |
| Hosts need history across devices | Accounts and recoverable ownership |
| Cross-room research queries are required | Normalize selected semantic fields |
| Institutions supply questions and rosters | LMS integration and institutional access |
