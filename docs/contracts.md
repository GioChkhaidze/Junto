# Application contracts

This document is the canonical contract for domain terminology, room state, persistence, stored artifacts, and HTTP behavior. Once implementation exists, Alembic migrations and generated OpenAPI schemas become executable counterparts to this document.

## Terminology

| Term | Meaning |
|---|---|
| Room | One question set, one participant set, and one live grouping run |
| Host | A signed session authorized to control one room |
| Participant | A room-local display name and opaque ID |
| Coverage unit | A host-approved, question-local element that should be available inside groups |
| Response family | A question-local primary method, reasoning pattern, or position |
| Analysis result | Per-question families and per-participant unit coverage |
| Grouping result | The selected policy, solver truth status, and participant partition |

Canonical field names are `coverage_units` in PostgreSQL and `coveredUnitIds` in JSON. Do not introduce correctness-specific field names.

A response family has no coverage-unit set. Coverage belongs only to an individual participant-question answer and is never inferred from family membership.

API and stored-artifact JSON use `camelCase`. Database columns use `snake_case`. UUIDs are serialized as strings, timestamps as RFC 3339 UTC strings, and unknown fields are rejected on mutation payloads.

## Room state machine

```text
                 ┌────────────────────────────┐
                 │                            │
draft → open → analyzing → ready → published │
                  │          │                │
                  └→ failed ─┘                │
                         retry → analyzing ───┘

ready → analyzing → ready   # full rerun or policy-only optimization
```

`published` is terminal in the MVP.

| From | Command | To | Preconditions |
|---|---|---|---|
| `draft` | Open room | `open` | At least one question; every question has 1–8 units; size bounds valid |
| `open` | Start analysis | `analyzing` | Feasible group count exists; atomic claim succeeds |
| `analyzing` | Complete analysis | `ready` | Valid analysis and grouping artifacts committed |
| `analyzing` | Fail analysis | `failed` | Error recorded; partial artifacts not exposed |
| `ready` | Rerun analysis | `analyzing` | Host capability; existing artifacts replaceable |
| `ready` | Switch policy | `analyzing` | Analysis artifact exists; optimizer-only mode |
| `ready` | Publish | `published` | Grouping result validates against current participants |
| `failed` | Retry full analysis | `analyzing` | Host grant; atomic claim succeeds |
| `failed` | Retry optimization | `analyzing` | Host grant; valid analysis artifact exists |

Mutation rules:

- `draft`: host may edit room and question content; participants cannot join.
- `open`: participants may join and upsert their own answers; room settings and question content are immutable.
- `analyzing`: joins and writes are rejected.
- `ready`: host may inspect, rerun, switch policy, or publish; participants wait.
- `published`: participants may read only their own group; all inputs and grouping are immutable.
- `failed`: only host diagnostics and retry are available.

### Freeze and artifact transactions

Joining and response writes take a shared lock on the room row, verify `status = 'open'`, and then insert or update in the same transaction. Starting analysis takes the conflicting room-row lock, validates the participant count and capacity range, clears `last_error`, and changes the status to `analyzing` in that transaction. It therefore waits for already-started writes and rejects every later write, producing one complete frozen snapshot.

Invalid participant count or capacity returns `409` and leaves the room `open`.

Full analysis writes `analysis_result`, `grouping_result`, clears `last_error`, and changes the room to `ready` in one final transaction. Optimizer-only work preserves `analysis_result` and atomically replaces `grouping_result`. Failure changes the room to `failed` with a sanitized `last_error`; a partially produced new artifact is never committed or returned. Existing artifacts are hidden from room APIs while status is `analyzing` or `failed`.

Only `ready` can publish. Publication validates the partition against the frozen participants and changes status to `published` in one transaction. Published inputs and the partition are immutable.

## PostgreSQL schema

Use PostgreSQL UUID generation, `timestamptz`, database checks, and cascade deletion for room-local data.

### `rooms`

```text
id                    uuid primary key default gen_random_uuid()
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
created_at            timestamptz not null default now()
updated_at            timestamptz not null default now()
```

Checks:

```text
minimum_group_size >= 2
minimum_group_size <= preferred_group_size
preferred_group_size <= maximum_group_size
maximum_group_size <= 8
status in ('draft', 'open', 'analyzing', 'ready', 'published', 'failed')
join_code = upper(join_code)
```

`analysis_result` and `grouping_result` are replaceable derived artifacts. Rerunning semantic analysis replaces both. Policy-only optimization preserves `analysis_result` and replaces `grouping_result`.

### `questions`

```text
id                  uuid primary key default gen_random_uuid()
room_id             uuid not null references rooms(id) on delete cascade
position            integer not null
prompt              text not null
reference_material  text null
coverage_units      jsonb not null default '[]'::jsonb

unique(room_id, position)
unique(id, room_id)
```

`coverage_units` must validate as an ordered array of 1–8 units before opening. The model returns text; the server assigns opaque IDs.

Add a database check that `jsonb_typeof(coverage_units) = 'array'`; Pydantic owns deeper item-shape validation. `reference_material` is optional, host-only semantic context. It may contain a rubric or answer key and is never returned by participant endpoints. Participant-visible reading material belongs in `prompt` for the MVP.

Coverage-unit IDs are question-local. Editing unit text preserves its ID, deleted IDs are not reused within the current draft, and accepting a newly generated list may replace the full list while the room remains `draft`. Opening freezes the approved IDs.

### `participants`

```text
id            uuid primary key default gen_random_uuid()
room_id       uuid not null references rooms(id) on delete cascade
display_name  text not null
joined_at     timestamptz not null default now()

unique(id, room_id)
index(room_id)
```

Display names need not be unique. The UI may append a short visual suffix when duplicates exist.

### `responses`

```text
room_id         uuid not null references rooms(id) on delete cascade
participant_id  uuid not null
question_id     uuid not null
text            text not null
updated_at      timestamptz not null default now()

primary key(participant_id, question_id)
foreign key(participant_id, room_id)
  references participants(id, room_id) on delete cascade
foreign key(question_id, room_id)
  references questions(id, room_id) on delete cascade
index(room_id)
```

The composite foreign keys prevent cross-room responses. A blank answer has no row. The application adds a null family and empty coverage locally when assembling the complete participant-question matrix.

## Stored JSON

### Coverage units

```json
[
  {
    "id": "u1",
    "text": "Defines the subproblem represented by each state"
  },
  {
    "id": "u2",
    "text": "Explains how the recurrence combines smaller states"
  }
]
```

Production IDs are opaque and generated by the application. The short IDs above are documentation fixtures.

### Analysis result

```json
{
  "schemaVersion": 1,
  "model": "pinned-model-name",
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

The stored artifact contains one assignment for every participant and question, including locally created empty assignments for unanswered questions. It is the server-side merge of two separately validated model results: per-answer coverage and per-answer family membership. Transient coverage evidence is deliberately absent from the stored artifact. This split does not change `schemaVersion` because the persisted shape is unchanged.

Unit and family IDs are question-local. The application, never the model, creates persistent IDs. Every non-empty submitted answer appears exactly once in each applicable model output, and both outputs must contain the same expected participant-ID set before the application merges them. The application adds unanswered entries. An all-empty question skips both provider calls and produces no families plus empty assignments for every participant.

Family objects contain only an ID and label; they never contain unit IDs. Only a final participant assignment contains both independent dimensions, `familyId` and `coveredUnitIds`. Transient provider DTOs and evidence are specified in [engine.md](engine.md#response-compilation), not persisted here.

### Grouping result

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

`solverStatus` is:

```text
optimal   optimality proven for every completed objective
feasible  valid assignment found without complete optimality proof
```

`fullCoverageStatus` is:

```text
feasible    a complete-coverage witness exists
infeasible  infeasibility was proven
unknown     solve limit expired without a witness or proof
```

A timeout is never stored as `infeasible`. If a later fallback solve finds a complete-coverage assignment, that assignment is a witness and status becomes `feasible`.

Do not duplicate per-group coverage, missing units, unit carriers, or represented families in `grouping_result`. Derive them from the participant partition, question units, and `analysis_result`.

## Browser routes

The Vite application owns these routes:

```text
/
/create
/host/:roomId
/join/:joinCode
/room/:roomId
```

Direct navigation to any browser route returns the compiled application shell. The React router selects the page after loading caller-appropriate state from `/api`.

## API conventions

- All endpoints are same-origin under `/api`.
- Mutations accept and return JSON unless no response body is needed.
- State-changing requests require the signed session and `X-CSRF-Token` matching the session value.
- Protected room resources return `404` when the record is absent or the caller lacks the required room grant, avoiding unnecessary room disclosure.
- `403` is reserved for failed CSRF or origin validation. The accountless API does not issue a `401` login challenge.
- State conflicts return `409` with a stable code.
- Validation failures return `422`.
- Accepted background work returns `202`.
- Rate limits return `429`.

Error shape:

```json
{
  "error": {
    "code": "ROOM_NOT_OPEN",
    "message": "Answers can only be changed while the room is open.",
    "details": {}
  }
}
```

Messages are safe for users. Provider responses, stack traces, session contents, answer text, and reference material are never included in public errors.

## API data shapes

These are the stable JSON shapes the first implementation must expose. Generated OpenAPI becomes the executable detail, but it must remain compatible with these fields and visibility rules.

`GET /api/session` returns the CSRF value needed for mutation headers and the bounded room IDs used to route the current browser:

```json
{
  "csrfToken": "random-session-value",
  "hostRoomIds": ["room-uuid"],
  "participantRoomIds": ["room-uuid"]
}
```

### Room commands

Create-room request:

```json
{
  "title": "Dynamic programming review",
  "policy": "teach",
  "groupSize": {
    "minimum": 3,
    "preferred": 4,
    "maximum": 5
  }
}
```

Create-room response (`201`):

```json
{
  "roomId": "room-uuid",
  "joinCode": "J7KM4P",
  "status": "draft"
}
```

`PATCH /api/rooms/{roomId}` accepts any non-empty subset of `title`, `policy`, and `groupSize`. Question creation and update use:

```json
{
  "position": 0,
  "prompt": "Explain when dynamic programming is useful.",
  "referenceMaterial": "Host-only rubric or null.",
  "coverageUnits": [
    {
      "text": "Identifies overlapping subproblems"
    }
  ]
}
```

For question mutations, an existing unit includes its current `id`; a newly typed unit omits `id`, and the server assigns one. Supplying an unknown ID is rejected. Omitting a previously stored unit deletes it. The endpoint returns the saved question with canonical IDs, so the browser never invents persistent identifiers.

`POST .../coverage-generation` returns `{"coverageUnits": [{"text": "..."}]}` with no IDs. It does not persist or approve the candidates; the host saves the accepted list through the question update endpoint, where canonical IDs are assigned. No response artifact exists while this replacement is allowed.

The host room projection contains `id`, `joinCode`, `title`, `policy`, `groupSize`, `status`, ordered `questions`, `progress`, `allowedActions`, and nullable `lastError`. Host questions include `referenceMaterial` and `coverageUnits`. `progress` contains `participantCount`, `submittedResponseCount`, and `possibleResponseCount`.

### Participant command shapes

Join-code lookup returns only:

```json
{
  "title": "Dynamic programming review",
  "status": "open"
}
```

Unknown and non-open join codes both return `404`; the public route does not reveal another room state.

Join request and response:

```json
{
  "displayName": "Maya"
}
```

```json
{
  "roomId": "room-uuid",
  "participantId": "participant-uuid",
  "displayName": "Maya"
}
```

If the current signed session already has a valid participant grant for the room, repeating the join returns that participant, ignores a replacement display name, and creates no duplicate. Display names are fixed for the MVP; a host can remove the participant before they rejoin under a corrected name.

The participant room projection contains `roomId`, `title`, `status`, ordered questions, the caller's own answers, and permitted actions. Before publication a participant question contains only `id`, `position`, `prompt`, and nullable `answer`; it never contains `referenceMaterial` or `coverageUnits`.

Answer writes use `{"text": "..."}` and return `204`. Empty normalized text deletes the row.

### Status and analysis commands

The compact status projection always contains `status` and `allowedActions`. Host status also contains the three progress counts. Participant status contains `answeredQuestionCount` and `questionCount`. It does not return analysis or grouping artifacts.

Full analysis accepts no body. Optimizer-only execution accepts:

```json
{
  "policy": "explore"
}
```

Both return `202` with `{"status": "analyzing"}` after the atomic state claim.

### Group projections

The host group response contains the stored top-level policy and truth statuses plus derived group views:

```json
{
  "policy": "teach",
  "solverStatus": "optimal",
  "fullCoverageStatus": "feasible",
  "groups": [
    {
      "id": "g1",
      "members": [
        {
          "participantId": "p1",
          "displayName": "Maya"
        }
      ],
      "questions": [
        {
          "questionId": "q1",
          "prompt": "Explain when dynamic programming is useful.",
          "units": [
            {
              "unitId": "u1",
              "text": "Identifies overlapping subproblems",
              "covered": true,
              "carriers": ["p1"]
            }
          ],
          "families": [
            {
              "familyId": "f1",
              "label": "Top-down memoization",
              "members": ["p1"]
            }
          ],
          "answers": [
            {
              "participantId": "p1",
              "text": "..."
            }
          ]
        }
      ]
    }
  ]
}
```

The participant `my-group` response uses the same members, units, carriers, and families for only the caller's group. It includes opaque IDs for those group members so carrier and family references resolve, and the UI maps them to display names. It omits `answers`, host diagnostics, and every other group.

## API surface

### Session

| Method | Path | Caller | Purpose |
|---|---|---|---|
| `GET` | `/api/session` | Anyone | Return CSRF token and current room grants needed by the UI |

### Host authoring

| Method | Path | State | Purpose |
|---|---|---|---|
| `POST` | `/api/rooms` | — | Create a draft room and grant host access |
| `GET` | `/api/rooms/{roomId}` | Any host-visible state | Return host view of room, questions, counts, and permitted actions |
| `PATCH` | `/api/rooms/{roomId}` | `draft` | Update title, policy, and group-size bounds |
| `POST` | `/api/rooms/{roomId}/questions` | `draft` | Add a question |
| `PATCH` | `/api/rooms/{roomId}/questions/{questionId}` | `draft` | Update prompt, reference material, position, or units |
| `DELETE` | `/api/rooms/{roomId}/questions/{questionId}` | `draft` | Delete a question and compact positions |
| `POST` | `/api/rooms/{roomId}/questions/{questionId}/coverage-generation` | `draft` | Return unpersisted candidate units |
| `POST` | `/api/rooms/{roomId}/open` | `draft` | Approve current units and open joining |

### Participant collection

| Method | Path | Caller/state | Purpose |
|---|---|---|---|
| `GET` | `/api/join/{joinCode}` | Anyone, `open` | Return public room title and joinability |
| `POST` | `/api/join/{joinCode}` | Anyone, `open` | Create participant and grant participant access |
| `GET` | `/api/rooms/{roomId}/participant` | Participant | Return questions and own answers while open, otherwise current participant state |
| `PUT` | `/api/rooms/{roomId}/responses/{questionId}` | Participant, `open` | Upsert or delete the caller's answer |
| `DELETE` | `/api/rooms/{roomId}/participants/{participantId}` | Host, `open` | Remove one participant and their responses |

An empty normalized answer deletes the response row.

### Status, analysis, and publication

| Method | Path | Caller | Purpose |
|---|---|---|---|
| `GET` | `/api/rooms/{roomId}/status` | Host or participant | Compact status and caller-appropriate counts/actions |
| `POST` | `/api/rooms/{roomId}/analysis` | Host, `open`, `ready`, or `failed` | Atomically start full analysis; freeze inputs when open; return `202` |
| `POST` | `/api/rooms/{roomId}/optimization` | Host, `ready`, or `failed` with analysis | Switch policy and optimize from saved analysis; return `202` |
| `GET` | `/api/rooms/{roomId}/groups` | Host, `ready` or `published` | Derive host review diagnostics and raw-answer audit data |
| `POST` | `/api/rooms/{roomId}/publish` | Host, `ready` | Publish the current grouping |
| `GET` | `/api/rooms/{roomId}/my-group` | Participant, `published` | Return only the caller's group and derived agenda |

## Response privacy matrix

| Data | Host | Participant before publish | Participant after publish |
|---|---:|---:|---:|
| Room title and question prompts | Yes | Yes | Yes |
| Host reference material | Yes | No | No |
| Approved coverage units | Yes | No | Own group agenda only |
| Participant names | Yes | No | Own group only |
| Raw answers | Yes | Own only | Own only |
| Analysis families and coverage | Yes | No | Own group agenda only |
| Full grouping | Yes | No | Own group only |
| Host diagnostics and errors | Yes | No | No |

Both model calls receive the question, opaque participant IDs, and non-empty answer text, never display names, cookie data, join codes, group constraints, or tentative groups. Only coverage classification receives optional reference material and approved units. Family clustering receives neither coverage input nor coverage output.
