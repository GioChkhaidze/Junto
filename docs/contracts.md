# Application contracts

## Authority and terminology

FastAPI's Pydantic schemas are the runtime wire authority. TypeScript interfaces under `frontend/src/domain/` mirror
those camelCase responses for the browser. Engine artifacts are strict, immutable Pydantic models and are described in
[engine.md](engine.md).

| Term              | Meaning                                                             |
| ----------------- | ------------------------------------------------------------------- |
| Room              | One question set and one live run                                   |
| Host              | A signed browser-session capability controlling one room            |
| Participant       | A room-local display name and capability                            |
| Coverage unit     | A host-approved question-local idea or perspective                  |
| Response family   | A primary approach or position, independent of coverage             |
| Cohort            | The immutable ordered participant-ID set captured at activity start |
| Answer            | One participant's current text for one question                     |
| Submission        | Irreversible finalization of that participant's answer set          |
| Semantic artifact | Validated per-answer family and covered-unit assignments            |
| Grouping artifact | Capacity-valid partition plus solver truth metadata                 |

## Room state machine

```text
draft --open--> lobby --start--> answering --claim--> analyzing --success--> published
                                                                  \--error----> failed
                                                                                  |
                                                                                  +--retry--> analyzing
```

| State       | Meaning                            | Browser mutations                                   |
| ----------- | ---------------------------------- | --------------------------------------------------- |
| `draft`     | Host is authoring                  | settings, questions, units, materials, open, delete |
| `lobby`     | Invite accepts participants        | join, remove participant, start, delete             |
| `answering` | Frozen cohort is timed             | own-answer save, submit, host early finish, delete  |
| `analyzing` | One attempt owns the room          | delete                                              |
| `published` | Complete result is visible by role | delete                                              |
| `failed`    | No result was published            | bounded retry, delete                               |

There is no separate ready state or publish command. A successful attempt releases groups automatically.

`analysisPhase` is `not_started`, `analyzing_responses`, `forming_groups`, `complete`, or `failed`. `analysisMode` is
`placeholder` or `coverage_aware`; both `recorded` and `openai` runtime modes project as `coverage_aware` because they
use the validated semantic artifact and real optimizer.

### Transition conditions

- `draft -> lobby`: at least one question exists, every question has at least one coverage unit, and coverage-aware
  reference context is within its bound.
- `lobby -> answering`: at least one participant exists and the count has a partition within configured minimum and
  maximum group size.
- `answering -> analyzing`: all frozen participants submit, the deadline is due, or the host ends collection early.
- `analyzing -> published`: one validated artifact pair and capacity-valid partition commit with the published state.
- `analyzing -> failed`: semantic compilation or grouping fails; both artifacts are absent from public state.
- `failed -> analyzing`: the host claims another attempt below `analysisMaxAttempts`.

Opening freezes authoring. Starting freezes cohort order, `startedAt`, and `deadlineAt`. Submission freezes that
participant's answers. An analysis claim freezes which saved room snapshot the attempt reads.

## Input invariants

### Room

- title: 1-120 characters;
- duration: 1-180 minutes;
- policy: `teach` or `explore`;
- group sizes: each 2-8 and `minimum <= preferred <= maximum`;
- questions: at most eight, at least one before opening;
- participants: at most 60;
- join code: six server-generated uppercase non-ambiguous characters, unique in storage.

### Question and units

- prompt: 1-4,000 characters;
- optional question reference: at most 8,000 characters;
- units: at most eight, each 1-300 characters;
- positions: contiguous and server-maintained;
- every question has at least one unit before opening.

New units receive server-owned IDs. An update may retain a known existing ID or omit it to create a unit; unknown and
duplicate retained IDs are rejected.

```json
{
  "position": 0,
  "prompt": "Which tradeoff matters most in this design?",
  "referenceMaterial": null,
  "coverageUnits": [{ "text": "Names the primary user need" }, { "text": "Explains one material tradeoff" }]
}
```

### Reference files

Files are room-level and draft-only:

- extensions: `.txt`, `.md`, `.pdf`, `.docx`;
- maximum count: eight;
- maximum source size: 5 MiB each;
- maximum extracted text: 100,000 characters each;
- PDF page count and DOCX expanded archive size are bounded;
- text and Markdown must be valid UTF-8;
- extraction must produce non-empty readable text.

The multipart request is bounded before framework spooling. The upload response contains metadata and extracted
character count, not extracted text. Original source bytes are not retained.

### AI-assisted authoring

`POST /api/authoring/suggestions` is a session-scoped, CSRF-protected multipart command available before a room is
created. It accepts a JSON `payload` field and, when the reference is an upload, one optional `file` field. The payload
shape is:

```json
{
  "activityTitle": "Responsibility seminar",
  "target": "question",
  "targetQuestionIndex": 0,
  "questions": [
    { "prompt": "", "coverageUnits": [""] },
    { "prompt": "Which argument is stronger?", "coverageUnits": ["Defends a conclusion with evidence"] }
  ],
  "referenceText": "Used only when no file is supplied"
}
```

- `target` is `question` or `coverage`;
- the target index must identify one of the one to eight supplied draft questions;
- activity title is at most 120 characters;
- draft prompts are at most 2,000 characters and draft coverage rows are at most 240 characters;
- pasted reference text is at most 8,000 characters;
- an uploaded reference uses the ordinary supported types, 5 MiB request bound, and bounded extractor;
- supplying both a file and pasted reference is rejected;
- the complete current question-and-unit draft is forwarded as context even though only one target is requested.

The structured response is:

```json
{
  "questionPrompt": "How do the two accounts define responsibility differently?",
  "coverageUnits": ["Compares both definitions of responsibility", "Uses evidence from both accounts"]
}
```

The response always contains one valid prompt and one to eight valid units so the pair is coherent. The browser applies
only the requested target. A successful response creates no room, grant, question, coverage unit, or stored model
artifact; it becomes persistent only if the host later completes the ordinary create-activity workflow. The endpoint is
available whenever `OPENAI_API_KEY` is configured; in development this is independent from the selected analysis engine.
Without that credential it returns `AUTHORING_ASSIST_UNAVAILABLE`.

### Participants and answers

- display name: 1-80 characters;
- answer: 0-1,500 characters;
- normalized blank text deletes the sparse response row;
- only the caller's frozen-cohort participant can save;
- no answer changes after final submission or deadline;
- repeated final submission returns the existing receipt and does not create another attempt.

Unanswered questions are absent responses. The semantic artifact adds local empty assignments for them; it does not
insert fake response rows.

## Time, progress, and polling

Timestamps are ISO 8601 UTC. `remainingSeconds` is the ceiling of `deadlineAt - serverTime`, never below zero. Browser
clocks animate the display but resynchronize from the server.

Host progress contains participant count, submitted-participant count, stored-response count, and the possible response
count. Participant progress contains only the caller's submitted state, answer count, and question count. Counts do not
imply semantic quality.

Clients poll small room or status projections only while waiting for a state transition and stop after loading a
terminal result. Answer writes remain ordinary `PUT` requests. There is no polling write, realtime message, or shared
presence state.

## Session and request security

`GET /api/session` initializes an HTTP-only signed cookie and returns:

```json
{ "csrfToken": "opaque-value", "hostRoomIds": [], "participantRoomIds": [] }
```

The cookie contains a random browser nonce, CSRF value, and at most the configured number of room grants. Creating a
room adds a host grant; joining adds a participant grant. The nonce plus a room-scoped database uniqueness constraint
makes repeat joins idempotent.

Every mutation requires `X-CSRF-Token`. Browser mutations with a supplied foreign Origin or Referer are rejected.
Production requires a session secret of at least 32 characters, HTTPS-only cookies, explicit HTTPS trusted origins,
PostgreSQL, and live OpenAI mode.

Knowledge of a UUID or invite code is not authorization. Protected endpoints return a caller-safe `404` for a missing or
wrong grant. Invite lookup and join are public only while the room is in `lobby`.

Successful JSON uses camelCase, UUID strings, and ISO timestamps. Input schemas reject unknown fields and trim strings.

Errors use one envelope:

```json
{
  "error": {
    "code": "GROUP_SIZE_INFEASIBLE",
    "message": "The current participant count cannot satisfy the configured group sizes.",
    "details": {}
  }
}
```

Common status meanings:

- `403`: invalid CSRF or untrusted origin;
- `404`: unavailable invite, resource, or room grant;
- `409`: valid command in the wrong state or an infeasible current capacity;
- `413`: reference-bearing material or authoring request exceeds the pre-spooling body limit;
- `422`: invalid input, unsupported material, extraction failure, or violated bound;
- `429`: anonymous create, authoring, join, or analysis rate limit reached;
- `502`/`503`: a configured authoring provider failed or is temporarily unavailable; readiness `503` remains
  persistence-only.

Public failures and telemetry contain no answer text, reference text, cookies, join codes, API keys, provider output, or
raw room identifiers.

### Development synthetic classroom

- `GET /api/development/rooms/{roomId}/synthetic-classroom`
  - Returns capability, stage, counts, feasible target sizes, and available response sources.
- `PUT /api/development/rooms/{roomId}/synthetic-cohort`
  - Replaces the deterministic synthetic lobby roster with 0, 5, 10, or 20 participants.
- `POST /api/development/rooms/{roomId}/synthetic-responses`
  - Explicitly generates, validates, atomically saves, and submits every pending synthetic response.

The browser cannot supply model IDs. OpenRouter is offered only when a server key is configured and generation always
requires an explicit host action. Completing the synthetic cohort starts the configured analysis automatically. A
provider failure, malformed matrix, or crossed deadline commits no synthetic answer. Repeating a completed action
performs no model call. The subsystem is available only in development.

## HTTP surface

### Public and session

| Method | Path                   | Result                                                      |
| ------ | ---------------------- | ----------------------------------------------------------- |
| `GET`  | `/api/health`          | process liveness only                                       |
| `GET`  | `/api/ready`           | repository probe; `503` when unavailable                    |
| `GET`  | `/api/session`         | CSRF token and current grant room IDs                       |
| `GET`  | `/api/join/{joinCode}` | public lobby title, duration, question count, analysis mode |
| `POST` | `/api/join/{joinCode}` | idempotent room-local participant grant                     |

### Pre-room authoring

- `POST /api/authoring/suggestions`
  - Returns a transient structured question and coverage suggestion; CSRF and reference are required.

### Host

| Method   | Path                                               | State/result                                |
| -------- | -------------------------------------------------- | ------------------------------------------- |
| `POST`   | `/api/rooms`                                       | create draft and host grant                 |
| `GET`    | `/api/rooms/{roomId}`                              | full host projection                        |
| `PATCH`  | `/api/rooms/{roomId}`                              | update draft settings                       |
| `DELETE` | `/api/rooms/{roomId}`                              | cascade room deletion and revoke this grant |
| `POST`   | `/api/rooms/{roomId}/questions`                    | add draft question                          |
| `PATCH`  | `/api/rooms/{roomId}/questions/{questionId}`       | edit/reorder draft question and units       |
| `DELETE` | `/api/rooms/{roomId}/questions/{questionId}`       | delete and close position gap               |
| `POST`   | `/api/rooms/{roomId}/materials`                    | bounded upload and extraction               |
| `DELETE` | `/api/rooms/{roomId}/materials/{materialId}`       | remove draft material                       |
| `POST`   | `/api/rooms/{roomId}/open`                         | enter lobby                                 |
| `POST`   | `/api/rooms/{roomId}/start`                        | freeze cohort and start deadline            |
| `DELETE` | `/api/rooms/{roomId}/participants/{participantId}` | remove lobby participant                    |
| `POST`   | `/api/rooms/{roomId}/analysis`                     | finish collection early; `202`              |
| `POST`   | `/api/rooms/{roomId}/analysis/retry`               | claim bounded failed-room retry; `202`      |
| `GET`    | `/api/rooms/{roomId}/groups`                       | all published groups and host diagnostics   |

### Participant and shared polling

- `GET /api/rooms/{roomId}/participant`
  - Returns the caller's room, prompts, answers, and submission state.
- `PUT /api/rooms/{roomId}/responses/{questionId}`
  - Returns a save receipt and the updated answer count.
- `POST /api/rooms/{roomId}/submit`
  - Performs idempotent finalization and returns a claim flag.
- `GET /api/rooms/{roomId}/my-group`
  - Returns only the caller's published group and agenda.
- `GET /api/rooms/{roomId}/status`
  - Returns host progress with a host grant; otherwise, it returns the caller's participant progress.

## Result projections

### Placeholder

The capacity-only development adapter returns:

```json
{
  "generationMode": "placeholder",
  "policy": "teach",
  "trigger": "all_submitted",
  "generatedAt": "2026-07-19T10:31:00Z",
  "groups": [{ "id": "g1", "members": [{ "participantId": "participant-uuid", "displayName": "Maya" }] }]
}
```

It guarantees balanced valid capacities and exactly-once membership. It reads no answer meaning and contains no
coverage, family, policy-quality, or solver claim.

### Coverage-aware host result

`generationMode` is `coverage_aware`. The result contains:

- policy, trigger, and generation time;
- solver `status`: `optimal`, `feasible`, or `fallback`;
- `completeCoverageStatus`: `feasible`, `infeasible`, or `unknown`;
- `timedOut`, solve duration, and ordered objective outcomes with `provenOptimal`;
- aggregate fully covered group-question count;
- every group and member;
- for each question: full-coverage flag, every unit with covered state and carriers, represented families with members,
  and a host-only answer audit.

`completeCoverageStatus: infeasible` means the feasibility model proved that every unit cannot be placed in every group.
`unknown` means no proof was obtained within the time limit. `fallback` is still a capacity-valid deterministic
partition, not a semantic optimum.

### Participant result

The participant result includes `generationMode`, policy, generation time, complete-coverage status, and one group. Its
question agenda has units/carriers and represented families. It omits all other groups, raw-answer audits, solver
objective details, and provider evidence.

`trigger` is `all_submitted`, `deadline`, or `host`.

## Projection matrix

- **Title, duration, question count, and analysis mode**
  - Invite: yes; participant: yes; host: yes.
- **Question prompts during and after collection**
  - Invite: no; participant: yes; host: yes.
- **Draft question reference text**
  - Invite: no; participant: no; host: yes.
- **Uploaded material metadata**
  - Invite: no; participant: no; host: yes.
- **Extracted uploaded text**
  - Invite: no; participant: no; host: no API field.
- **Coverage-unit authoring data**
  - Invite: no; participant: published own agenda only; host: yes.
- **Caller's answer**
  - Invite: no; participant: yes; host: coverage result audit after publication.
- **Other participants' answers**
  - Invite: no; participant: no; host: coverage result audit after publication.
- **Lobby roster and aggregate progress**
  - Invite: no; participant: no; host: yes.
- **All groups**
  - Invite: no; participant: no; host: yes.
- **Caller's group**
  - Invite: no; participant: yes; host: included in all groups.
- **Provider evidence quotes**
  - Invite: no; participant: no; host: never persisted or projected.

Authoring-suggestion inputs and outputs are transient request data, not room projections. They are never available
through invite, participant, or host read endpoints. Uploaded source bytes are extracted on the server and are not sent
to the model provider; the extracted or pasted reference text, activity title, all current draft prompts/units, target,
and target index are sent only when the creator explicitly invokes a suggestion.

## Persistence and recovery contract

`RoomRepository` supports add, read by ID/code, row-locked aggregate transaction, readiness, deletion, retention
deletion, and stale-analysis recovery. Two adapters implement it:

- memory, for explicit development and isolated unit tests;
- PostgreSQL, selected when `DATABASE_URL` is set and required in production.

PostgreSQL has `rooms`, `questions`, `coverage_units`, `reference_materials`, `participants`, and `responses`. The
validated semantic and grouping artifacts are versioned JSONB values on the room. This keeps four core collaboration
records while normalizing ordered units and extracted materials where referential constraints matter.

Every mutation locks the room row and commits its aggregate atomically. Room deletion and retention cascade through
children. Startup maintenance changes an old interrupted `analyzing` room to `failed`, clears partial artifact fields,
and makes the bounded retry available. The system does not resume an in-flight model request after restart and must run
as one web process until a durable job design exists.
