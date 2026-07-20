# Junto

Junto is an accountless, room-based website that turns individual answers into live discussion groups. A host defines
the ideas or perspectives that should be present for each question; Junto classifies what each answer contributes and
uses a coverage-first optimizer to form valid groups.

The product promise is deliberately bounded:

> Form capacity-valid groups with the strongest feasible coverage of every question's host-approved ideas and productive
> perspectives.

Junto does not grade participants, guarantee that every requested idea can appear in every group, or claim that grouping
improves learning.

## What is implemented

- React, TypeScript, Vite, and CSS Modules SPA with material-first authoring, optional AI-assisted question and coverage
  drafting, a timed one-question-at-a-time questionnaire, autosave, review, and role-specific results.
- FastAPI application with Pydantic contracts, signed room-session cookies, CSRF checks, trusted-origin enforcement,
  bounded uploads, and ordinary HTTP polling.
- PostgreSQL persistence through SQLAlchemy and psycopg, with Alembic migrations, row-locked room transactions,
  cascading deletion, retention, and stale-analysis recovery.
- Independent semantic operations for answer coverage and response families using the OpenAI Responses API with Pydantic
  Structured Outputs.
- OR-Tools CP-SAT grouping that fixes capacity first, optimizes coverage lexicographically, then applies the selected
  Teach or Explore objective.
- Atomic publication of validated semantic and grouping artifacts; failed analysis exposes no partial result and has one
  bounded host retry by default.
- A deterministic recorded-provider mode for tests and the reviewed offline demo fixture.
- Development-only synthetic cohorts with 20 varied identities, offline patterned responses, and an explicit OpenRouter
  response action using a server-owned pinned model pool.
- A multistage container image and a one-process deployment profile backed by PostgreSQL.

## Runtime

```text
React + TypeScript + Vite + CSS Modules
                |
                | same-origin JSON + short polling
                v
             FastAPI
      + signed room capabilities
      + room workflow and file extraction
      + semantic compiler
      + OR-Tools CP-SAT
          |              |
          v              v
     PostgreSQL     OpenAI Responses API
```

The language model interprets question-local answer text but never selects groups. The optimizer receives only
validated, discrete coverage and family assignments; a response family never owns or implies coverage units.

## Engine modes

| Mode          | Semantic source          | Grouping                         | Use                             |
| ------------- | ------------------------ | -------------------------------- | ------------------------------- |
| `placeholder` | none                     | deterministic capacity partition | arbitrary local UI development  |
| `recorded`    | reviewed fixture outputs | real CP-SAT optimizer            | offline tests and scripted demo |
| `openrouter`  | strict Chat Completions  | real CP-SAT optimizer            | development evaluation only     |
| `openai`      | live Responses API calls | real CP-SAT optimizer            | live deployment                 |

Production configuration requires `openai`, PostgreSQL, a strong session secret, an OpenAI API key, secure cookies, and
explicit HTTPS origins. The in-memory repository and placeholder engine remain development adapters, not silent
production fallbacks.

## Local development

Use Python 3.12 or newer and Node.js 20.19 or newer.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item ..\.env.example ..\.env # once; then add local credentials as needed
.\.venv\Scripts\python.exe -m uvicorn junto.main:app --reload --port 8000 --env-file ..\.env
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. With no database URL or engine mode set, development uses the in-memory repository and
labelled placeholder grouping. AI-assisted authoring is independently enabled whenever `OPENAI_API_KEY` is present, so
it can be used while analysis remains in `placeholder` or `recorded` mode. See [Operations](docs/operations.md) to run
PostgreSQL, recorded fixtures, or the live analysis provider.

For a database-backed run, set `DATABASE_URL`, migrate before starting the app, and keep the same URL for both commands:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\.venv\Scripts\python.exe -m uvicorn junto.main:app --port 8000 --env-file ..\.env
```

Vite proxies `/api` to FastAPI in development. A production frontend build is served directly by FastAPI from
`frontend/dist`.

## Verify

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check junto tests
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy junto
```

PostgreSQL integration tests run when `TEST_DATABASE_URL` points to a disposable PostgreSQL database.

```powershell
cd frontend
npm run typecheck
npm run format:check
npm test
npm run build
```

The recorded end-to-end demo does not require an API key. A live semantic-quality evaluation does, and its reviewed
results must be reported separately from structural test results.

## Documentation

- [Product contract](docs/product.md): experience, product promise, guarantees, and non-goals.
- [Architecture](docs/architecture.md): runtime, module boundaries, persistence, access, and execution model.
- [Application contracts](docs/contracts.md): state machine, API, projections, validation, and privacy boundaries.
- [Semantic and optimization engine](docs/engine.md): model inputs, validation, solver priorities, and truth labels.
- [Semantic evaluation](docs/evaluation.md): recorded gates, live evaluator, report contract, and human review.
- [Operations](docs/operations.md): configuration, migration, deployment, retention, recovery, and release checks.
- [Demo guide](docs/demo.md): recorded classroom fixture and live-demo sequence.
- [Design system](DESIGN.md): visual and interaction source of truth.

## Deliberate boundaries

- No profiles, passwords, OAuth, permanent teacher role, or cross-room identity.
- No browser-to-database access, WebSockets, shared document, chat, or realtime presence.
- One application process runs analysis in-process; horizontal workers require a durable job design first.
- Uploaded source bytes are discarded after bounded extraction; extracted text is retained only with its room.
- Model classifications remain fallible and auditable. Solver validity does not prove semantic correctness or learning
  impact.
