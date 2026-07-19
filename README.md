# Junto

Junto is an accountless, room-based website for turning individual answers into live discussion groups.

The product goal is to form valid groups with the strongest feasible coverage of each question's host-approved ideas. The current repository implements the complete room experience and a clearly labelled deterministic grouping placeholder. It does **not** yet analyze answer meaning or optimize coverage.

## Current status

The first end-to-end slice is implemented:

- a host creates a timed room, optionally uploads reference material, writes questions, and defines coverage units;
- participants join with a code and room-scoped display name;
- starting the activity freezes the participant roster and starts one server-owned deadline;
- participants answer one question at a time, autosave between questions, review, and submit once;
- all submissions, the deadline, or an early host finish starts the analysis transition;
- a deterministic placeholder forms balanced, capacity-valid groups and releases them automatically;
- the host can see every group, while each participant can retrieve only their own.

This is a development prototype, not a production deployment. Rooms, uploaded material, answers, and groups live in an in-memory repository and are lost whenever the FastAPI process restarts.

## Runtime

```text
React + TypeScript + Vite + Tailwind
                 |
                 v
              FastAPI
       + signed room sessions
       + Pydantic API schemas
       + reference text extraction
       + in-memory repository
       + deterministic grouping seam
```

Vite serves the frontend during development and proxies `/api` to FastAPI. A production-style build can be served by FastAPI from `frontend/dist`.

Planned next adapters are PostgreSQL for durable storage, the OpenAI API for semantic compilation, and OR-Tools CP-SAT for coverage-first grouping. None is wired into the current slice.

## Run locally

Use Python 3.12 or newer and Node.js 20.19 or newer.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m uvicorn junto.main:app --reload --port 8000
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`.

Local development generates a fresh process-local signing secret automatically. For any HTTPS
deployment, set `JUNTO_ENV=production` and provide a random `JUNTO_SESSION_SECRET` of at least 32
characters; startup fails rather than using a public fallback. See [.env.example](.env.example).

## Verify

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check junto tests
.\.venv\Scripts\python.exe -m mypy junto
```

```powershell
cd frontend
npm run typecheck
npm test
npm run build
```

After `npm run build`, FastAPI detects and serves `frontend/dist` when the API starts from this repository.

## Documentation

| Document | Purpose |
|---|---|
| [Product contract](docs/product.md) | Current experience, concepts, guarantees, boundaries, and target outcome |
| [Architecture](docs/architecture.md) | Implemented layers, runtime paths, replaceable seams, access, and persistence status |
| [Application contracts](docs/contracts.md) | State machine, validation, API surface, projections, privacy, and placeholder guarantees |
| [Semantic and optimization engine](docs/engine.md) | Future OpenAI and OR-Tools engine specification; not implemented yet |
| [Implementation plan](docs/implementation-plan.md) | Current checkpoint and PR-sized path from prototype to the intended engine |
| [Design system](DESIGN.md) | Visual and interaction source of truth |

Earlier proposals under `docs/archive/` are historical context, not implementation specifications.

## Product principles

- A host is an action within a room, not a permanent user role.
- Access is accountless and room-scoped; there are no profiles, OAuth flows, or institutional identities.
- Coverage units are subject-agnostic: concepts, steps, evidence, arguments, objections, perspectives, tradeoffs, or risks.
- Coverage belongs to an individual answer. A future response family will never own or imply coverage.
- The timer and allowed room actions come from the server.
- Ordinary HTTP and short polling are sufficient; the product has no realtime collaboration protocol.
- Placeholder output must never be presented as semantic, AI-generated, optimized, or evidence of learning.

## Visual direction

[DESIGN.md](DESIGN.md) defines Junto's white-first academic workspace, restrained green state and action color, conventional controls, ruled rosters, and quiet typography. Chips, tag clouds, gradients, glass effects, decorative card grids, oversized marketing copy, and AI-branded interface language are outside the design system.
