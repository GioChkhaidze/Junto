# Junto: Hackathon Stack and Build Proposal

## 1. Build target

The hackathon deliverable is one anonymous, room-based web application demonstrating a complete response-to-discussion cycle:

```text
Create room
Add questions and reference material
Generate and approve coverage units
Open room
Collect anonymous answers
Compile response coverage and response families
Test full-coverage feasibility
Optimize the selected grouping policy
Review and publish groups
Show each participant their group and coverage agenda
```

The core acceptance invariant is:

> Every group receives the strongest feasible coverage of the question's required ideas and productive perspectives.

When full coverage is infeasible, Junto must maximize the weakest group's coverage and report the exact missing units. It must never label partial coverage as complete.

The main demo uses five questions and approximately twenty-four participants. A second prepared room in an unrelated subject demonstrates that the semantic contract and optimizer are not tied to one domain.

One saved semantic artifact supports both grouping policies. Junto computes and stores only the policy selected by the host. Switching policies reruns the optimizer without another language-model call.

## 2. Minimal architecture

```text
Browser
  ├── React + TypeScript interface built by Vite
  ├── Tailwind CSS design system
  ├── ordinary fetch requests and short polling
  ├── host capability cookie
  └── participant capability cookie
            │
            ▼
FastAPI application
  ├── serves the compiled Vite application
  ├── exposes the room-scoped JSON API
  ├── enforces room-scoped capabilities
  ├── reads and writes PostgreSQL
  ├── calls the language-model API
  ├── validates coverage and family artifacts with Pydantic
  ├── runs OR-Tools CP-SAT
  └── executes one in-process analysis function
            │
            ▼
PostgreSQL
  ├── four relational tables
  └── two room-local JSON result columns
```

The deployed system contains:

```text
one application container
one PostgreSQL instance
one language-model API
one optimization library
```

There is no server-side HTML rendering, Next.js server, production Node.js runtime, Supabase platform, browser database client, OAuth provider, Realtime service, Redis instance, Celery deployment, or dedicated analysis worker.

## 3. Stack

### Application server

- Python
- FastAPI
- Pydantic
- SQLAlchemy or another ordinary PostgreSQL driver
- Alembic for schema migrations
- Uvicorn

Python owns the complete application because the semantic compiler and optimizer are Junto's important backend functions. OR-Tools has first-class Python support, so a separate Python optimization service beside a TypeScript application would add a network boundary without adding product value.

### Frontend

- React
- TypeScript
- Vite
- Tailwind CSS

Vite builds the React application into static HTML, JavaScript, and CSS assets. FastAPI serves those compiled assets and exposes the JSON API, so the browser and API share one origin, one capability-cookie boundary, and one deployment container.

The production container does not run Node.js. Node is a build-time dependency only. FastAPI/Uvicorn is the sole application runtime.

React owns interactive browser state for question editing, coverage-unit editing, lobby and analysis polling, group cards, policy switching, and coverage inspection. Tailwind provides the shared responsive visual system for host and participant screens. Junto does not use server-rendered templates.

### Database

- Plain PostgreSQL
- ordinary server-side SQL access
- `jsonb` for room-local semantic and grouping artifacts

The application must not expose PostgreSQL directly to browsers. Database access is mediated by FastAPI, so authorization lives in normal application code and the stack remains portable across PostgreSQL hosts.

### Semantic compiler

- one language-model provider SDK
- provider-native strict structured output when available
- Pydantic validation after every response
- one repair attempt for schema-invalid output

Do not build multiple provider adapters for the hackathon. Keep only a thin internal interface so tests can supply recorded outputs.

### Optimizer

- OR-Tools CP-SAT
- deterministic input ordering
- sequential lexicographic objectives
- fixed random seed
- one CP-SAT search worker for reproducibility

### Packaging and deployment

- Docker
- one application image
- one managed PostgreSQL instance

The deployment provider is interchangeable as long as it can run a persistent container and provide a standard PostgreSQL connection string.

## 4. Repository layout

```text
junto/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── rooms.py
│   │   ├── participants.py
│   │   └── responses.py
│   ├── auth/
│   │   └── capabilities.py
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── migrations/
│   ├── semantic/
│   │   ├── compiler.py
│   │   ├── prompts.py
│   │   ├── schemas.py
│   │   └── validation.py
│   ├── optimizer/
│   │   ├── capacities.py
│   │   ├── model.py
│   │   └── serialize.py
│   ├── services/
│   │   ├── analysis.py
│   │   └── rooms.py
│   └── static/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── api/
│   │   └── styles.css
│   ├── package.json
│   └── vite.config.ts
├── fixtures/
│   ├── dynamic-programming/
│   └── philosophy/
├── tests/
│   ├── api/
│   ├── semantic/
│   ├── optimizer/
│   └── e2e/
├── Dockerfile
└── README.md
```

The frontend build outputs into `app/static`. The final container contains the compiled assets and starts only FastAPI/Uvicorn; Node.js is not part of the deployed runtime.

## 5. Room-scoped access model

Junto has no accounts and no permanent user roles.

### 5.1 Creating a room

`POST /api/rooms` creates:

```text
room ID
join code
host token
```

The raw host token is returned once and stored in an HTTP-only cookie. Only its hash is stored in PostgreSQL.

### 5.2 Joining a room

`POST /api/rooms/by-code/{joinCode}/participants` creates a participant inside that room and returns a participant token in an HTTP-only cookie. Only its hash is stored.

### 5.3 Capability rules

Host capability:

- edit the draft room;
- generate or edit coverage units;
- open the room;
- view submitted answers;
- start analysis;
- change the selected policy and rerun optimization;
- review and publish groups.

Participant capability:

- read the room's questions while it is open;
- create or edit only that participant's answers;
- poll room state;
- retrieve only that participant's published group.

### 5.4 Token requirements

- generate host and participant tokens from a cryptographically secure random source;
- use enough entropy that tokens cannot be guessed;
- store an HMAC-SHA-256 or equivalent keyed hash rather than the raw token;
- compare derived hashes in constant time;
- set cookies `HttpOnly`, `Secure`, and `SameSite=Lax` in production;
- scope cookies so host and participant capabilities can coexist safely;
- never place host tokens in logs, model inputs, analytics events, or public URLs.

Join codes are invitations, not administrative credentials. They may be shorter than capability tokens, but join attempts must be rate-limited.

This is authentication in the narrow technical sense of proving possession of a room capability. It is not OAuth, identity management, or an account system.

## 6. Database model

The MVP has four tables.

### 6.1 `rooms`

```text
id                    uuid primary key
join_code             text unique not null
host_token_hash       text not null
title                 text not null
policy                teach | explore
minimum_group_size    integer not null
preferred_group_size  integer not null
maximum_group_size    integer not null
status                draft | open | analyzing | ready | published | failed
analysis_result       jsonb nullable
grouping_result       jsonb nullable
error                 text nullable
created_at            timestamp not null
updated_at            timestamp not null
```

Constraints:

```text
minimum_group_size >= 2
minimum_group_size <= preferred_group_size
preferred_group_size <= maximum_group_size
```

One room combines what the previous design called an activity and a session. Possession of the host token grants control. There is no owner profile or reusable-activity hierarchy.

`analysis_result` and `grouping_result` are replaceable, room-local derived artifacts. Rerunning semantic analysis overwrites both. Switching policy preserves `analysis_result` and overwrites only `grouping_result`.

### 6.2 `questions`

```text
id                  uuid primary key
room_id             uuid not null references rooms on delete cascade
position            integer not null
prompt              text not null
reference_material  text not null
coverage_units      jsonb not null

unique(room_id, position)
unique(id, room_id)
```

Example `coverage_units`:

```json
[
  {
    "id": "u1",
    "text": "Defines the dynamic-programming state"
  },
  {
    "id": "u2",
    "text": "Derives the recurrence"
  }
]
```

Coverage units belong to one question, are edited together, and are consumed together. They do not need a separate table.

### 6.3 `participants`

```text
id                       uuid primary key
room_id                  uuid not null references rooms on delete cascade
display_name             text not null
participant_token_hash   text not null
joined_at                timestamp not null

unique(id, room_id)
unique(room_id, participant_token_hash)
```

A participant exists only inside one room. There is no global student account or permanent profile.

Display-name uniqueness is not required. The UI may disambiguate duplicate names without turning them into identities.

### 6.4 `responses`

```text
room_id         uuid not null references rooms on delete cascade
participant_id  uuid not null
question_id     uuid not null
text            text not null
updated_at      timestamp not null

primary key(participant_id, question_id)
foreign key(participant_id, room_id)
  references participants(id, room_id) on delete cascade
foreign key(question_id, room_id)
  references questions(id, room_id) on delete cascade
```

Including `room_id` allows PostgreSQL to guarantee that the participant and question belong to the same room.

A response row exists only after a participant saves an answer. Unanswered questions do not receive fake empty rows. When analysis input is assembled, the application locally represents missing participant-question answers with null family and zero covered units.

## 7. JSON artifacts

### 7.1 Semantic analysis result

```json
{
  "schemaVersion": "1",
  "model": "selected-model",
  "questions": [
    {
      "questionId": "q1",
      "families": [
        {
          "id": "f1",
          "label": "Top-down memoization"
        },
        {
          "id": "f2",
          "label": "Bottom-up tabulation"
        }
      ],
      "assignments": [
        {
          "participantId": "p1",
          "familyId": "f1",
          "coveredUnitIds": ["u1", "u2", "u3"]
        },
        {
          "participantId": "p2",
          "familyId": "f2",
          "coveredUnitIds": ["u1", "u2", "u3", "u4"]
        },
        {
          "participantId": "p3",
          "familyId": null,
          "coveredUnitIds": []
        }
      ]
    }
  ]
}
```

Family assignment and coverage are independent. Competing positions can each form valid families, while their unit coverage depends on the host-approved coverage definitions.

### 7.2 Grouping result

```json
{
  "schemaVersion": "1",
  "policy": "teach",
  "solverStatus": "optimal",
  "objectiveValues": {
    "worstNormalizedCoverage": 1000,
    "fullyCoveredGroupQuestions": 19
  },
  "groups": [
    {
      "id": "g1",
      "participantIds": ["p1", "p4", "p8", "p12"],
      "questions": [
        {
          "questionId": "q1",
          "coveredUnitIds": ["u1", "u2", "u3", "u4"],
          "missingUnitIds": [],
          "representedFamilyIds": ["f1", "f2"]
        }
      ]
    }
  ],
  "coverageReport": {
    "fullyCoveredGroupQuestions": 19,
    "totalGroupQuestions": 20
  }
}
```

The application joins participant IDs to display names when rendering a group page. It derives unit carriers by combining `analysis_result` with group membership.

No separate tables are required for families, assignments, response coverage, analysis runs, grouping runs, groups, group members, or explainers.

## 8. Room state and mutation rules

### Draft

- host can edit title, policy, size constraints, questions, reference material, and coverage units;
- participants cannot join;
- semantic and grouping results are null.

### Open

- participants can join;
- participants can create and edit their own responses;
- question content and coverage units are immutable;
- the host can inspect participation and submission counts.

### Analyzing

- joins and response mutations are rejected;
- semantic compilation and optimization execute;
- host and participant clients poll status.

### Ready

- host can inspect groups and coverage diagnostics;
- participants remain on the waiting screen;
- host may change policy and rerun only the optimizer;
- host may rerun the entire analysis, overwriting current artifacts.

### Published

- grouping is visible;
- each participant can retrieve only the group containing their participant ID;
- room inputs remain immutable.

### Failed

- the error is visible only to the host;
- the host can retry analysis;
- partial artifacts must not be presented as a valid result.

## 9. Coverage-unit generation

Coverage compilation runs while the room is in `draft`.

### Input

```text
question ID
question prompt
reference answer, rubric, source text, or learning objectives
```

### Output

```json
{
  "questionId": "q1",
  "units": [
    {"id": "u1", "text": "..."},
    {"id": "u2", "text": "..."}
  ]
}
```

### Prompt rules

- return three to seven units when the material supports that range;
- make every unit atomic and self-contained;
- include only elements required for a strong response or productive discussion;
- ground or align every unit with the provided reference material and question;
- allow concepts, reasoning steps, evidence, arguments, objections, perspectives, tradeoffs, or risks;
- avoid grading labels, numeric importance, and confidence;
- do not turn every response family into a coverage unit; keep required coverage and observed approaches separate.

The host can edit, delete, or regenerate units. Opening the room is blocked until every question has at least one accepted unit.

## 10. Response compilation

After responses freeze, the analysis function runs one model call per question. Calls may run concurrently with a small limit.

### Input

```text
question prompt
reference material
accepted coverage units
anonymous participant IDs and non-empty answer text
```

### Output

```json
{
  "questionId": "q1",
  "families": [
    {"id": "f1", "label": "Top-down memoization"},
    {"id": "f2", "label": "Bottom-up tabulation"}
  ],
  "assignments": [
    {
      "participantId": "p1",
      "familyId": "f1",
      "coveredUnitIds": ["u1", "u2", "u3"]
    }
  ]
}
```

### Prompt rules

- cluster by core reasoning, approach, or position;
- use the smallest partition that preserves grouping-relevant distinctions;
- never cluster by writing style, verbosity, confidence, or identity;
- assign one primary family to each substantive answer;
- use `null` when no coherent approach exists;
- count a unit only when the answer substantively represents the element described by it;
- do not count keywords, incidental references, or material that mischaracterizes the host-approved unit;
- when an objective unit requires correctness, do not count an invalid formula, fact, or reasoning step;
- for open-ended questions, do not reject a relevant position merely because another response defends the opposite position;
- keep family labels short and question-local;
- include every input participant ID exactly once;
- never invent participant or unit IDs.

### Validation

Pydantic and explicit domain checks require:

- exact question ID;
- unique family IDs;
- exact participant-ID coverage for the submitted inputs;
- one assignment per submitted answer;
- valid family references;
- valid coverage-unit references;
- no duplicate unit IDs inside an assignment;
- no extra fields.

The application adds local null assignments for participants with no response to that question.

Malformed model output receives one repair attempt containing validation errors. A second failure marks the room `failed`.

## 11. Optimizer implementation

### 11.1 Capacity selection

Given participant count `n` and size constraints `(minimum, preferred, maximum)`:

1. enumerate feasible group counts;
2. choose the count minimizing `abs(n / group_count - preferred)`;
3. break ties by minimizing the largest capacity deviation, then by choosing the larger group count;
4. create an exact balanced capacity list;
5. fix those capacities before semantic optimization.

### 11.2 Core variables

```text
x[s,g]          participant assignment
unit[g,q,u]     coverage-unit availability
full[g,q]       complete required-unit coverage
family[g,q,f]   response-family presence
contributor[s,g] participant carries at least one coverage unit in the group
```

### 11.3 Hard constraints

```text
Each participant appears exactly once.
Each group matches its fixed capacity.
Unit availability is the OR of assigned correct-unit carriers.
Family presence is the OR of assigned family members.
```

### 11.4 Exact full-coverage test

First solve with:

```text
unit[g,q,u] = 1
for every group, question, and required coverage unit
```

If feasible, keep those constraints for all later policy objectives.

If infeasible, solve sequentially:

```text
maximize worst normalized group-question coverage
maximize minimum fully covered questions per group
maximize total fully covered group-question pairs
maximize total normalized coverage
```

Normalize with exact integer scaling based on the number of units in each question.

### 11.5 Teach Each Other policy

After coverage objectives are fixed:

```text
maximize minimum active coverage contributors per group
maximize total active contributors
minimize maximum concentration of uniquely carried units on one participant
maximize response-family variety as a final tie-breaker
```

There are no explainer variables. The group page derives every eligible unit carrier and lets the group decide who speaks.

### 11.6 Explore Different Approaches policy

After coverage objectives are fixed:

```text
maximize minimum questions with at least two families per group
maximize total group-question pairs with at least two families
maximize normalized distinct-family count
minimize maximum normalized non-null single-family concentration
maximize coverage-contributor distribution as a final tie-breaker
```

Response-family variety never substitutes for required-unit coverage.

### 11.7 Lexicographic execution

For each objective:

1. solve;
2. record the optimum;
3. add a constraint fixing that value;
4. solve the next objective.

Do not combine objectives with weighted sums.

### 11.8 Determinism and limits

- use stable participant ordering;
- use stable group labels;
- fix a deterministic random seed;
- use one CP-SAT search worker;
- add symmetry-breaking constraints;
- set a total solve limit;
- persist `optimal`, `feasible`, `infeasible`, or `failed` accurately;
- publish only assignments satisfying every hard constraint.

## 12. In-process analysis execution

When the host presses **Generate groups**, the request handler atomically claims the room:

```sql
UPDATE rooms
SET status = 'analyzing',
    error = NULL,
    updated_at = now()
WHERE id = :room_id
  AND status IN ('open', 'ready', 'failed')
RETURNING id;
```

Only a successful `RETURNING` starts analysis. This prevents duplicate runs and freezes response mutations through the same status transition.

The handler then returns immediately and schedules one in-process background function:

```text
1. open a fresh database session
2. load room, questions, units, participants, and responses
3. compile each question
4. validate and assemble analysis_result
5. run the selected optimizer policy
6. validate and save grouping_result
7. set room status to ready
```

Operational requirements:

- do not reuse the request's database session inside the background function;
- keep blocking model SDK calls and CP-SAT work away from the async event loop;
- catch failures, roll back partial writes, and set the room to `failed` with a host-visible diagnostic;
- write `analysis_result`, `grouping_result`, and final status transactionally where practical;
- run one application process for the hackathon so duplicate in-memory schedulers are not introduced;
- on application startup, mark stale `analyzing` rooms as `failed` so the host can retry;
- make reruns safe by replacing room-local JSON artifacts rather than appending versions.

This execution is intentionally non-durable. A process restart can interrupt analysis, but it cannot corrupt a published grouping. A separate queue and worker become justified only when concurrent volume or durability requirements make in-process execution inadequate.

## 13. Polling behavior

Junto has no shared document, chat, presence system, or participant-to-participant live state. Ordinary HTTP plus short polling is sufficient.

Poll every one or two seconds for:

- participant count in the host lobby;
- submitted-answer count;
- room status during analysis;
- publication status on participant waiting screens.

Use ordinary requests for:

- room creation and editing;
- joining;
- answer save and update;
- analysis start;
- policy change;
- publication;
- published group retrieval.

Polling responses should be compact and conditional where useful. Stop polling when the relevant terminal state is reached.

## 14. Routes and screens

### 14.1 Browser routes

```text
/create
/host/{roomId}
/join/{joinCode}
```

`/host/{roomId}` renders the appropriate host panel for the current room state: editor, lobby, responses, analysis, group review, or published summary.

`/join/{joinCode}` renders the appropriate participant state: join form, questions, waiting screen, or published group.

### 14.2 Required screens

#### Create room

- room title;
- Teach Each Other or Explore Different Approaches;
- minimum, preferred, and maximum group sizes;
- question prompt;
- reference material;
- generated coverage units with edit controls.

#### Host lobby

- join code and QR code;
- participant count and names;
- open-room state;
- submitted-answer progress;
- Generate groups action.

#### Participant response flow

- display name entry;
- questions and answer fields;
- explicit saved state;
- participant-scoped edits while the room is open.

#### Analysis state

- compact processing status;
- retry state on failure;
- polling until ready.

#### Group review

- group members;
- full or partial coverage for every question;
- missing units;
- all members who carried each unit;
- represented response families;
- policy switch that reruns only optimization;
- publish action.

#### Participant group page

- group number and members;
- questions in order;
- complete coverage checklist;
- unit carriers derived from the artifacts;
- represented approaches;
- explicit partial-coverage warning when necessary.

## 15. API surface

All browser mutations go through FastAPI.

```text
POST   /api/rooms
GET    /api/rooms/{roomId}/host
PATCH  /api/rooms/{roomId}
POST   /api/rooms/{roomId}/questions
PATCH  /api/questions/{questionId}
POST   /api/questions/{questionId}/compile-coverage
POST   /api/rooms/{roomId}/open

GET    /api/rooms/by-code/{joinCode}
POST   /api/rooms/by-code/{joinCode}/participants
GET    /api/rooms/{roomId}/participant
PUT    /api/rooms/{roomId}/responses/{questionId}

GET    /api/rooms/{roomId}/status
POST   /api/rooms/{roomId}/analyze
POST   /api/rooms/{roomId}/optimize
POST   /api/rooms/{roomId}/publish
GET    /api/rooms/{roomId}/my-group
```

Host endpoints require the room's host capability. Participant endpoints require the room's participant capability. Status responses expose only the data appropriate to the caller.

## 16. Build sequence

### Foundation

- FastAPI application and Vite build;
- Docker image and PostgreSQL connection;
- four database tables and migrations;
- capability-token utilities and secure cookies;
- create, join, question, participant, and response flows;
- room state enforcement and polling.

### Semantic compiler

- coverage compilation schema and editor;
- response compilation schema using `coveredUnitIds`;
- one model integration;
- validation and repair path;
- recorded fixture outputs and reviewed semantic cases.

### Optimizer

- capacity selection;
- exact full-coverage feasibility test;
- coverage fallback objectives;
- Teach Each Other objectives;
- Explore Different Approaches objectives;
- deterministic serialization into `grouping_result`.

### Complete room loop

- atomic transition to analyzing;
- in-process analysis function;
- failure and stale-run recovery;
- host group review and policy switch;
- publication;
- participant group page.

### Demo polish

- seeded dynamic-programming room;
- seeded philosophy room;
- QR join flow;
- clear full/partial coverage visualization;
- comparison of selected policy results from one saved semantic artifact;
- deterministic fallback fixtures for development and tests.

## 17. Testing

### Access tests

- a host token controls only its room;
- a participant token edits only its participant's responses;
- participants cannot read other raw responses through the API;
- participants retrieve only their own published group;
- invalid and cross-room tokens are rejected;
- host and participant raw tokens never appear in stored rows or logs.

### State tests

- only `open` rooms accept joins and response changes;
- analysis start atomically transitions one room once;
- response writes cannot race past the transition to `analyzing`;
- failed analysis records an error and can be retried;
- stale analyzing rooms recover to `failed` after restart;
- only `ready` rooms can publish.

### Semantic contract tests

- every submitted participant appears exactly once;
- missing answers receive local null assignments;
- no invented participant or unit IDs;
- keyword-only or incidental mentions do not count as coverage;
- objective correctness-bearing units reject invalid formulas, facts, or reasoning steps;
- open-ended opposing positions can each receive valid family and coverage assignments;
- schema repair handles common malformed outputs;
- recorded examples from multiple subjects remain coherent.

### Optimizer tests

- every participant appears exactly once;
- every group matches its capacity;
- every group-question contains every required coverage unit when feasible;
- impossible full coverage is reported accurately;
- fallback objectives protect the weakest group;
- Teach and Explore produce policy-appropriate partitions on fixtures;
- identical inputs produce identical serialized results;
- randomized rooms remain valid across supported sizes.

### End-to-end tests

- host creates a room without an account;
- participant joins without an account;
- participant submits answers;
- host starts analysis;
- in-process analysis writes valid JSON artifacts;
- host reviews and publishes;
- participant sees their assigned group and coverage agenda;
- policy switching reuses semantic analysis without another model call.

## 18. Hackathon acceptance criteria

The build is complete when:

- any person can create a room without registration;
- the creator receives a private room-scoped host capability;
- participants can join by code without accounts;
- participants can submit and edit only their own answers while the room is open;
- coverage units can be generated, reviewed, and edited;
- response compilation marks the coverage units substantively represented by each answer;
- the optimizer tests full required-unit coverage exactly;
- every feasible group contains all required units for every question;
- infeasible coverage is reported without false completeness;
- group-size constraints always hold;
- changing policy reruns only the optimizer;
- the host can review and publish;
- each participant sees only their published group;
- the complete flow works for two unrelated subject fixtures;
- the deployed runtime consists of one application container and PostgreSQL.

## 19. Demo plan

Use prepared rooms with approximately twenty-four anonymous participants.

### Room A: dynamic programming

Responses include:

- top-down and bottom-up methods;
- complete and partial explanations;
- several mistaken but coherent approaches;
- different coverage of state, recurrence, base cases, order, and complexity.

Show:

1. the host-created coverage units;
2. participant answers arriving;
3. exact full-coverage feasibility;
4. the selected grouping;
5. a group page showing every required unit and its carriers;
6. a policy switch that reuses `analysis_result` and reruns only CP-SAT.

### Room B: philosophy

Responses include:

- distinct positions;
- competing supporting arguments;
- objections and responses;
- overlapping and missing coverage.

The second room demonstrates that the schema and optimizer accept another domain without subject-specific code. It does not claim universal semantic accuracy.

## 20. Deferred work

Add only after a concrete product need appears:

- optional accounts for saved room history;
- duplicate-room support for reusable question sets;
- durable queues and separate workers for concurrent analysis volume;
- SSE or WebSockets when polling becomes material;
- versioned semantic and grouping runs for auditing or experiments;
- normalization for cross-room analytics;
- Canvas LTI, Kahoot, or other integrations;
- organizational roles and institutional access controls;
- repeated-pair avoidance across rooms;
- large-room hierarchical compilation;
- custom model training or vector databases.

## 21. Technical decision summary

```text
Product boundary:
Anonymous, capability-based rooms

Core guarantee:
Every group receives the strongest feasible required-unit coverage

Browser application:
React + TypeScript + Vite + Tailwind

Application runtime:
FastAPI serves the JSON API and compiled Vite assets

Database:
Plain PostgreSQL, four tables, two JSON result columns

Access:
Hashed host and participant capability tokens in secure cookies

Live behavior:
Ordinary HTTP plus one-to-two-second polling

Semantic engine:
One language model with strict structured output and Pydantic validation

Semantic artifact:
Coverage units, response families, and per-response coverage

Grouping policies:
Teach Each Other and Explore Different Approaches

Optimizer:
OR-Tools CP-SAT with exact feasibility and lexicographic objectives

Background work:
One intentionally non-durable in-process analysis function

Deployment:
One Docker application container and one PostgreSQL instance
```
