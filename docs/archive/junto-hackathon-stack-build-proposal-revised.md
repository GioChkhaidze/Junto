# Junto: Hackathon Stack and Build Proposal

## 1. Build target

Build one accountless, room-based web application that completes this loop:

```text
Create room
Add questions and optional reference material
Generate and approve coverage units
Open room
Collect answers
Compile response families and per-response coverage
Optimize Teach Each Other or Explore Different Approaches
Review and publish groups
Show each participant the discussion agenda
```

The main demo uses five questions and approximately twenty-four participants. A second prepared room in an unrelated subject demonstrates that the semantic contract is not subject-specific.

The product stores one semantic analysis result and one selected grouping result per room. Switching policy reruns only the optimizer.

## 2. Minimal architecture

```text
Browser
  ├── server-rendered HTML
  ├── small vanilla-JavaScript polling and form helpers
  └── signed room-session cookie
          │
          ▼
FastAPI application
  ├── renders pages
  ├── handles room-scoped access
  ├── reads and writes PostgreSQL
  ├── calls one language-model provider
  ├── validates structured output with Pydantic
  ├── runs OR-Tools CP-SAT
  └── runs one non-durable in-process analysis task
          │
          ▼
PostgreSQL
  ├── four relational tables
  └── room-local JSON artifacts
```

Deployment contains:

```text
one application container
one PostgreSQL database
one language-model API
```

The hackathon build does not need a frontend framework, a Node.js build, Supabase, OAuth, WebSockets, Redis, Celery, a vector database, or a separate optimizer service.

## 3. Stack

### Application

- Python;
- FastAPI and Starlette;
- Jinja2 templates;
- Pydantic;
- SQLAlchemy 2;
- psycopg 3;
- Alembic;
- Uvicorn.

### Semantic compiler

- one provider SDK;
- strict structured output when supported;
- Pydantic validation;
- one schema-repair attempt;
- recorded fixture outputs for tests.

The provider is hidden behind one small function interface. The hackathon implementation supports one provider, not a provider framework.

### Optimizer

- OR-Tools CP-SAT;
- integer-only formulations;
- sequential lexicographic solves;
- stable input order;
- one solver worker;
- fixed seed;
- explicit solve limits and status reporting.

### Frontend

- Jinja2 pages;
- plain CSS;
- small `fetch` calls for autosave and polling.

There is no frontend build pipeline. FastAPI serves pages and static files directly.

### Deployment

- Docker;
- one persistent application process;
- one managed PostgreSQL instance;
- HTTPS supplied by the deployment platform.

The application uses a normal PostgreSQL connection string and contains no database-host-specific SDK.

## 4. Repository layout

```text
junto/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── access.py
│   ├── semantic.py
│   ├── optimizer.py
│   ├── workflow.py
│   ├── routes/
│   │   ├── host.py
│   │   └── participant.py
│   ├── templates/
│   └── static/
├── migrations/
├── fixtures/
│   ├── dynamic_programming/
│   └── philosophy/
├── tests/
│   ├── test_access.py
│   ├── test_semantic_contract.py
│   ├── test_optimizer.py
│   └── test_room_flow.py
├── Dockerfile
├── alembic.ini
└── README.md
```

Keep semantic and optimizer modules independent of HTTP routes. Tests call them directly.

## 5. Room-scoped access

Junto has no accounts, passwords, profiles, or permanent roles.

Use Starlette's signed cookie session. The cookie stores only opaque room and participant IDs:

```json
{
  "hostRooms": ["room-uuid"],
  "participants": {
    "room-uuid": "participant-uuid"
  }
}
```

The signature prevents modification. The cookie is `HttpOnly`, `Secure` in production, and `SameSite=Lax`.

Access rules:

- creating a room adds its ID to `hostRooms`;
- joining stores the participant ID under the room;
- host routes require the room ID in `hostRooms`;
- participant routes require the room-to-participant mapping;
- the model never receives session data or display names.

Use same-origin forms and requests. State-changing forms include a session CSRF token or equivalent same-origin validation.

This design intentionally has no cross-device recovery. Clearing the browser session removes access to accountless rooms. Recovery links and permanent accounts are deferred.

Join codes are random invitations, not administrative credentials. Generate them from an unambiguous alphabet, check uniqueness, and apply a small in-process rate limit to join attempts.

## 6. Database model

The MVP uses four tables. Use `timestamptz` for timestamps and database `CHECK` constraints for states and group sizes.

### 6.1 `rooms`

```text
id                    uuid primary key
join_code             text unique not null
title                 text not null
policy                text not null check (policy in ('teach', 'explore'))
minimum_group_size    smallint not null
preferred_group_size  smallint not null
maximum_group_size    smallint not null
status                text not null
analysis_result       jsonb null
grouping_result       jsonb null
last_error            text null
created_at            timestamptz not null
updated_at            timestamptz not null
```

Checks:

```text
minimum_group_size >= 2
minimum_group_size <= preferred_group_size
preferred_group_size <= maximum_group_size
maximum_group_size <= configured safety limit
status in ('draft', 'open', 'analyzing', 'ready', 'published', 'failed')
```

`analysis_result` and `grouping_result` are replaceable derived artifacts. Rerunning semantic analysis replaces both. Switching policy preserves `analysis_result` and replaces only `grouping_result`.

### 6.2 `questions`

```text
id                  uuid primary key
room_id             uuid not null references rooms on delete cascade
position            integer not null
prompt              text not null
reference_material  text null
coverage_units      jsonb not null default '[]'::jsonb

unique(room_id, position)
unique(id, room_id)
```

`reference_material` can contain an answer, rubric, reading excerpt, or learning objective. It is optional because the host approves the final coverage units.

Coverage units remain one JSON array because they are edited and consumed as one question-local object.

### 6.3 `participants`

```text
id            uuid primary key
room_id       uuid not null references rooms on delete cascade
display_name  text not null
joined_at     timestamptz not null

unique(id, room_id)
```

A participant exists only inside one room. Display names need not be unique; the interface can append a short suffix.

### 6.4 `responses`

```text
room_id         uuid not null references rooms on delete cascade
participant_id  uuid not null
question_id     uuid not null
text            text not null
updated_at      timestamptz not null

primary key(participant_id, question_id)
foreign key(participant_id, room_id)
  references participants(id, room_id) on delete cascade
foreign key(question_id, room_id)
  references questions(id, room_id) on delete cascade
```

The composite foreign keys guarantee that response, participant, and question belong to the same room.

A blank answer has no row. Missing answers are added as local null assignments when the semantic artifact is assembled.

## 7. Stored JSON

### 7.1 Coverage units

The model returns text. The server assigns IDs:

```json
[
  {"id": "u1", "text": "Defines the dynamic-programming state"},
  {"id": "u2", "text": "Derives the recurrence"}
]
```

The model never invents persistent unit IDs.

### 7.2 Semantic analysis result

```json
{
  "schemaVersion": 1,
  "questions": [
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
          "coveredUnitIds": ["u1", "u2"]
        },
        {
          "participantId": "p2",
          "familyId": null,
          "coveredUnitIds": []
        }
      ]
    }
  ]
}
```

The model initially returns `familyIndex`; the server validates it and converts it to a canonical family ID.

### 7.3 Grouping result

```json
{
  "schemaVersion": 1,
  "policy": "teach",
  "solverStatus": "optimal",
  "fullCoverageStatus": "feasible",
  "groups": [
    {
      "id": "g1",
      "participantIds": ["p1", "p4", "p8", "p12"]
    }
  ]
}
```

`fullCoverageStatus` is `feasible`, `infeasible`, or `unknown`. Only a proven result may use the first two values.

Do not store per-group coverage, missing units, represented families, or unit carriers. They are derived from group membership and `analysis_result`. Avoiding those duplicates removes synchronization bugs.

## 8. Room state machine

```text
draft → open → analyzing → ready → published
                    ↘ failed
```

### Draft

- host edits title, policy, size bounds, questions, reference material, and coverage units;
- participants cannot join;
- opening is blocked until each question has at least one approved unit.

### Open

- participants join and save answers;
- questions and coverage units are immutable;
- host sees participant and submission counts;
- **Generate groups** atomically changes the room to `analyzing` and freezes joins and writes.

### Analyzing

- no answer or participant mutations;
- clients poll status;
- semantic compilation and optimization run.

### Ready

- host reviews groups and coverage diagnostics;
- changing policy runs optimization only;
- rerunning analysis replaces semantic and grouping artifacts;
- participants remain on a waiting page.

### Published

- the partition is immutable;
- each participant retrieves only the group containing its participant ID.

### Failed

- partial results are not published;
- the host sees a concise error and can retry.

## 9. Coverage-unit generation

Coverage generation runs during `draft`.

### Model input

```text
question
optional reference answer, rubric, reading, or learning objective
```

### Model output

```json
{
  "units": [
    {"text": "Defines the state"},
    {"text": "Derives the recurrence"}
  ]
}
```

Validation:

- one to eight units;
- non-empty, unique unit text;
- content-specific wording rather than generic labels such as “argument” or “evidence”;
- concise text length;
- no IDs or extra fields.

The host approves or edits the result. The server assigns stable IDs in display order.

## 10. Response compilation

After responses freeze, run one model call per question. Limit concurrency to a small fixed number.

### Model input

```text
question
optional reference material
accepted coverage units with IDs
opaque participant IDs and non-empty answer text
```

### Model output

```json
{
  "families": [
    {"label": "Top-down memoization"},
    {"label": "Bottom-up tabulation"}
  ],
  "assignments": [
    {
      "participantId": "p1",
      "familyIndex": 0,
      "coveredUnitIds": ["u1", "u2"]
    },
    {
      "participantId": "p2",
      "familyIndex": null,
      "coveredUnitIds": ["u2"]
    }
  ]
}
```

Semantic rules:

- at most one primary family per non-empty response;
- a hybrid answer may form a hybrid family;
- null family does not force empty coverage;
- families reflect reasoning, method, or position;
- coverage reflects substantive unit presence;
- participant identity, style, verbosity, and confidence are ignored;
- no answer text is repeated in output;
- every declared family is used.

Structural validation:

- exact participant-ID coverage for submitted answers;
- one assignment per submitted answer;
- unique, non-empty family labels;
- family indices are null or in range;
- coverage IDs exist in the question;
- no duplicate coverage IDs;
- no unused family;
- no extra fields.

The server adds null assignments for unanswered participants. Invalid output receives one repair request containing only schema errors. A second failure moves the room to `failed`.

## 11. Input safety and cost controls

Student answers are untrusted model input. The compiler prompt must delimit them as data, prohibit following instructions found inside answers, and require schema-only output. Render all user and model text with HTML escaping.

Enforce configurable limits on question count, participant count, answer length, coverage-unit count, and simultaneous analysis runs. Apply simple per-IP limits to room creation and analysis and a global in-process semaphore around model work. This protects the model budget without Redis or an external gateway.

## 12. Capacity selection

For participant count `n`, enumerate group counts satisfying:

```text
ceil(n / maximum_group_size)
<= group_count <=
floor(n / minimum_group_size)
```

If the range is empty, reject analysis and ask the host to change the size settings.

Choose the count minimizing:

```text
abs(n / group_count - preferred_group_size)
```

Break ties by choosing the larger group count. Build balanced capacities from `floor(n / group_count)` and `ceil(n / group_count)`. Fix capacities before optimization.

## 13. Optimizer

### 13.1 Core variables

```text
x[s,g]              participant assignment
covered[g,q,u]      unit availability
full[g,q]           full question coverage
family[g,q,f]       family presence
```

Hard constraints:

```text
Each participant appears exactly once.
Each group matches its fixed capacity.
covered[g,q,u] is the OR of assigned carriers.
family[g,q,f] is the OR of assigned family members.
```

### 13.2 Coverage solve

Before CP-SAT, report obvious scarcity when a unit has fewer carriers than the number of groups. Then run an exact full-coverage feasibility solve.

If the solve finds a full-coverage assignment, enforce it. If it proves infeasibility, run the fallback. If it returns `UNKNOWN`, run the fallback but record full-coverage status as `unknown`.

Fallback objectives:

```text
maximize worst normalized group-question coverage
maximize minimum fully covered questions per group
maximize total fully covered group-question pairs
maximize total normalized coverage
```

Use integer normalization based on the least common multiple of per-question unit counts.

### 13.3 Teach Each Other

Create internal variables:

```text
contributes[s,g,q,u]
```

For each available group-question-unit, assign exactly one eligible member as a representative carrier. These variables are optimization machinery only and are not persisted.

Then solve:

```text
maximize minimum active contributors per group
minimize maximum representative-unit load per participant
maximize total active contributors
maximize family variety as a final tie-break
```

An active contributor is a participant assigned at least one representative unit.

### 13.4 Explore Different Approaches

For every group-question pair, count distinct non-null families and mark whether at least two are represented.

Then solve:

```text
maximize minimum diverse questions per group
maximize total diverse group-question pairs
maximize normalized additional-family coverage
```

Normalize additional families by the maximum attainable number for the group-question pair.

### 13.5 Lexicographic execution and time limits

For each objective:

1. solve with the remaining global time budget;
2. if status is `OPTIMAL`, fix the objective value and continue;
3. if status is `FEASIBLE`, retain the valid assignment, mark the run feasible, and stop lower-priority optimization;
4. if no valid assignment exists, use the last valid higher-priority result or fail.

Never claim infeasibility from a timeout or `UNKNOWN` status.

Use one solver worker, a fixed seed, stable participant ordering, and a deterministic capacity-respecting initial hint. Canonicalize group labels after solving.

## 14. Analysis execution

The host starts analysis with one atomic state transition:

```sql
UPDATE rooms
SET status = 'analyzing',
    last_error = NULL,
    updated_at = now()
WHERE id = :room_id
  AND status IN ('open', 'ready', 'failed')
RETURNING id;
```

Only the request receiving a row starts work.

Return HTTP `202`. A FastAPI background task runs a synchronous workflow in a worker thread:

```text
1. open a fresh database session
2. load the frozen room snapshot
3. compile questions with a small ThreadPoolExecutor
4. validate and assemble analysis_result
5. run CP-SAT
6. save artifacts and set status to ready in one transaction
```

Policy switching from `ready` skips semantic compilation and replaces only `grouping_result`.

Operational rules:

- deploy one Uvicorn process;
- use a persistent container that does not terminate work after the response;
- never reuse the request database session inside the task;
- catch every exception and move the room to `failed`;
- on startup, mark stale `analyzing` rooms as `failed`;
- treat the task as non-durable.

A process restart can interrupt analysis. Retry is safe because artifacts are replaced atomically. A durable queue becomes necessary only when real concurrency or restart tolerance is required.

## 15. Polling

Use ordinary HTTP and two-second polling for:

- participant count;
- submitted-answer count;
- analysis status;
- publication status.

Stop polling at the relevant terminal state. No shared document, presence protocol, or chat exists, so WebSockets add no value.

## 16. Routes and screens

### Browser routes

```text
GET/POST  /create
GET       /host/{room_id}
POST      /host/{room_id}/question
POST      /host/{room_id}/coverage
POST      /host/{room_id}/open
POST      /host/{room_id}/analyze
POST      /host/{room_id}/optimize
POST      /host/{room_id}/publish
GET/POST  /join/{join_code}
GET/POST  /room/{room_id}/answers
GET       /room/{room_id}/state
GET       /room/{room_id}/group
```

The exact edit and delete form actions may be split. The application does not need a broad public REST API.

### Required screens

#### Create and edit room

- title;
- grouping policy;
- minimum, preferred, and maximum size;
- question prompt;
- optional reference material;
- generated coverage units with edit controls.

#### Host lobby

- join code and QR code;
- participant names and counts;
- answer progress;
- Generate groups action.

#### Participant answer page

- display name;
- question list;
- answer fields;
- saved state.

#### Host group review

- group members;
- coverage and missing units for every question;
- all carriers for each unit;
- represented families;
- expandable original answers for semantic audit;
- policy switch;
- publish action.

#### Participant group page

- group members;
- questions in order;
- coverage checklist;
- members who mentioned each unit;
- represented approaches;
- explicit warning for missing units.

## 17. Build order

### Vertical room loop

- database and migrations;
- signed session access;
- create, join, answer, state, and publish pages;
- room-state enforcement and polling.

### Semantic compiler

- coverage-unit generation and editor;
- response compilation contract;
- one provider call path;
- validation, repair, and recorded fixtures.

### Optimizer

- capacity selection;
- exact coverage feasibility;
- fair coverage fallback;
- Teach Each Other;
- Explore Different Approaches;
- deterministic serialization.

### Completion

- in-process analysis workflow;
- group review;
- policy switching;
- participant agenda;
- two subject fixtures;
- failure and retry behavior.

## 18. Testing

### Access and state

- a browser session controls only rooms it created;
- a participant edits only its room-scoped responses;
- participants cannot retrieve other raw responses;
- only open rooms accept joins and answer writes;
- one atomic transition starts analysis;
- only ready rooms publish.

### Semantic contract

- every submitted participant appears exactly once;
- no invented participant or unit IDs;
- family indices are valid;
- null family can retain coverage;
- unused families are rejected;
- malformed output is rejected or repaired;
- reviewed dynamic-programming and philosophy fixtures remain coherent.

### Optimizer

- capacities are feasible and balanced;
- every participant appears exactly once;
- full coverage is enforced when proven feasible;
- missing units are reported when infeasible;
- Teach Each Other distributes representative contributions;
- Explore Different Approaches increases family diversity after coverage;
- every published assignment satisfies hard constraints;
- identical inputs are reproducible within the pinned build.

### End to end

- host creates a room without registration;
- participants join and answer without accounts;
- analysis writes a valid semantic artifact and partition;
- policy switching does not call the model again;
- host publishes;
- each participant sees only its own group.

## 19. Acceptance criteria

The build is complete when:

- any person can create a room without an account;
- participants join with a code and room-scoped display name;
- coverage units are generated and host-approved;
- answers compile into valid families and per-response coverage;
- group-size constraints are never violated;
- full coverage is enforced whenever the solver proves it feasible;
- infeasible coverage is shown exactly;
- both policies use the same semantic artifact;
- host can review and publish;
- participant pages derive correct coverage and family information;
- the prepared five-question, twenty-four-participant demo completes within the target live-session budget;
- deployment consists of one application container and PostgreSQL.

## 20. Demo plan

### Dynamic programming

Use answers containing top-down, bottom-up, partial, and mistaken approaches with varied coverage of state, recurrence, base cases, order, and complexity.

Show:

1. approved coverage units;
2. response compilation;
3. exact feasibility result;
4. Teach Each Other grouping;
5. participant agenda;
6. policy switching without another model call.

### Philosophy

Use answers containing distinct positions, arguments, objections, and responses. Show that the same artifact and optimizer operate without subject-specific code.

## 21. Deferred work

Add only after a demonstrated need:

- durable queue and separate workers;
- optional accounts and room recovery;
- reusable question sets;
- Canvas or Kahoot integration;
- SSE or WebSockets;
- cross-room analytics and normalized semantic tables;
- versioned analysis runs;
- large-room hierarchical compilation;
- custom model training.

## 22. Configuration

Required environment variables:

```text
DATABASE_URL
SESSION_SECRET
MODEL_API_KEY
MODEL_NAME
PUBLIC_BASE_URL
MAX_ANALYSIS_CONCURRENCY
MAX_PARTICIPANTS_PER_ROOM
MAX_ANSWER_CHARACTERS
```

Run migrations before starting one Uvicorn process. Pin Python dependencies and the model name used for the demo.
