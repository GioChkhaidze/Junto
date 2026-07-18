# Junto

Junto is an accountless, room-based web application that forms live discussion groups from submitted answers.

Its core promise is:

> Form valid groups that collectively contain the strongest feasible coverage of every question's host-approved ideas.

Within a bounded solve, Junto distinguishes proven full coverage from infeasible or still-unknown cases and labels time-limited output as the best valid assignment found—not as a proof of optimality.

A language model independently classifies per-answer coverage and clusters response families. The server validates and merges those results; a deterministic CP-SAT optimizer then forms capacity-valid groups, prioritizing coverage before the selected grouping policy.

## Status

The product and engineering contracts are ready for implementation. Application code has not been scaffolded yet.

## Planned stack

```text
React + TypeScript + Vite + Tailwind
                  │
                  ▼
                FastAPI
        ├── PostgreSQL
        ├── OpenAI Responses API
        └── OR-Tools CP-SAT
```

Vite is a build-time tool. FastAPI serves the compiled frontend and JSON API from one application container. PostgreSQL is the only persistent service.

## Documentation

| Document | Purpose |
|---|---|
| [Product contract](docs/product.md) | Problem, promise, workflow, policies, scope, and acceptance criteria |
| [Architecture](docs/architecture.md) | Runtime, component boundaries, access model, background work, deployment, and repository shape |
| [Application contracts](docs/contracts.md) | Terminology, room states, database schema, stored JSON, browser routes, and API surface |
| [Semantic and optimization engine](docs/engine.md) | Evidence-grounded coverage classification, independent family clustering, validation, feasibility, and policy objectives |
| [Implementation and PR plan](docs/implementation-plan.md) | Ordered pull requests, dependencies, gates, tests, and demo checkpoints |

These files are canonical. Earlier exploratory proposals are retained under `docs/archive/` only for history and must not be used as implementation specifications.

## Product loop

```text
Create room
Add questions and optional reference material
Generate and approve coverage units
Open room
Collect answers
Analyze responses
Optimize the selected policy
Review and publish groups
Discuss
```

## Non-negotiable decisions

- Rooms are accountless and capability-scoped; there are no user profiles or institutional roles.
- Coverage units are subject-agnostic and host-approved.
- Coverage belongs to individual answers; response families never own or imply coverage units.
- Coverage classification and family clustering are independent model calls joined only by opaque participant ID.
- Coverage is optimized before response-family diversity or contributor distribution.
- The model interprets text but never forms groups.
- The optimizer receives only validated, discrete artifacts.
- Only the selected grouping result is stored; switching policy reuses semantic analysis.
- PostgreSQL contains four relational tables and room-local JSON artifacts.
- Clients use ordinary HTTP and short polling; Junto has no realtime collaboration protocol.
- Analysis is an intentionally non-durable in-process task for the hackathon build.

## Visual direction

[DESIGN.md](DESIGN.md) is the visual source of truth. Junto uses a white-first academic workspace, restrained green actions and state, conventional form controls, ruled rosters, and one quiet sans-serif family. It explicitly excludes chips, tag clouds, gradients, glass effects, decorative card grids, oversized marketing copy, and AI-branded interface language.

The exploratory PNGs under `assets/mockups/` predate this direction and are retained only as historical artifacts. Do not implement their coral/purple palette, avatar chips, nested rounded cards, or decorative icon treatment.

## Next step

Begin with [PR 1 in the implementation plan](docs/implementation-plan.md#pr-1--application-foundation), then merge in dependency order. Every PR has a runnable acceptance gate; no PR should rely on an unimplemented future layer to demonstrate its own behavior.
