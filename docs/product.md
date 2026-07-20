# Product contract

## Definition

Junto is an accountless, room-based website for forming live discussion groups from submitted answers. A host may be an
instructor, a student, or any facilitator; host is a capability for one room, not a permanent user type.

The product promise is:

> Form capacity-valid groups with the strongest feasible coverage of every question's host-approved ideas and productive
> perspectives.

Random grouping ignores what people bring to a discussion. One answer may provide a definition, another evidence,
another objection, and another competing approach. Junto makes those contributions explicit and composes groups while
the activity is still live.

## Core concepts

### Coverage units

Coverage units are the question-local elements that should be represented inside each group: concepts, reasoning steps,
evidence, arguments, objections, perspectives, mechanisms, tradeoffs, risks, or other useful contributions.

Their meaning is subject-dependent:

- math or programming: state definition, recurrence, base case, or complexity;
- philosophy: position, supporting argument, objection, counterargument, or implication;
- history: evidence, interpretation, competing explanation, or limitation;
- design: user need, approach, tradeoff, or risk.

For an objectively graded question, the host may encode correctness in the units. For an open-ended question, units
describe relevant conceptual or argumentative coverage without prescribing one conclusion. Every question needs at least
one host-approved unit before its room can open.

Coverage belongs only to an individual answer. A participant covers a unit only when that answer substantively supports
it.

### Response families

A response family is a question-local primary method, reasoning pattern, or position. Families capture productive
differences such as top-down versus bottom-up programming approaches or opposing philosophical positions.

Families are independent of coverage:

- people in the same family may cover different units;
- people in different families may cover the same units;
- an answer may cover units while having no usable family;
- family membership never grants correctness or coverage.

### Grouping policies

Coverage is always optimized before the selected policy.

- **Teach Each Other** distributes representative contribution opportunities across members after preserving the
  achieved coverage result.
- **Explore Different Approaches** increases the presence of distinct non-null response families after preserving the
  achieved coverage result.

The policy cannot trade away a higher-priority coverage result.

## Roles and access

### Host

The browser session that creates a room can:

- set its title, duration, policy, and group-size bounds;
- optionally upload reference material;
- author, order, and edit questions and coverage units;
- request editable question or coverage-unit suggestions when reference material is present;
- open the invite lobby and share its code or URL;
- see and manage the lobby roster before the activity starts;
- start the shared timer, monitor submission progress, and finish collection early;
- retry one failed analysis by default;
- view every published group, coverage diagnostics, response families, and the answer audit for those groups;
- delete the room.

### Participant

A participant exists only inside one room. Their browser session can:

- join an open lobby using a display name;
- read question prompts and edit only their own answers while collection is open;
- submit once, making those answers final;
- retrieve only the published group containing their participant ID;
- use a per-question agenda showing covered and missing units, eligible carriers, and represented families for that
  group.

There are no profiles, email addresses, passwords, OAuth providers, teacher accounts, or cross-room participant
identities. Room access is not recoverable on another device unless its signed browser session is transferred, which the
product does not support.

## Experience

```text
draft -> lobby -> answering -> analyzing -> published
                                      \-> failed -> bounded retry
```

### 1. Author

The host first receives an optional material step. UTF-8 text, Markdown, PDF, and DOCX files are extracted on the
server; original source bytes are not retained. The host then sets room timing and group bounds and writes one to eight
questions with one to eight coverage units each.

When reference material is present and the server has an OpenAI credential configured, a host may request a suggestion
for one question prompt or one question's coverage units. This authoring capability is independent from the
activity-analysis engine selected for development. The request includes the activity title, reference text, and the
complete current question-and-unit draft so the suggestion can avoid repetition and stay coherent with the activity. The
interface applies only the requested target, keeps the result editable, and asks the host to review it.

This remains an authoring editor, not an automatic quiz generator. AI suggestions never open a room, persist a question
by themselves, or become approved coverage units without the host continuing through review and creation. Hosts own the
question wording and approve every coverage unit. No authoring-assist control appears in the participant questionnaire
or solution flow.

### 2. Invite

Opening the room creates a six-character invite code and URL. Participants enter a room-scoped display name and wait in
the lobby. Starting the activity freezes the exact participant cohort and is rejected when that count cannot satisfy the
configured group-size bounds.

### 3. Answer

The server records one shared start time and deadline. Each participant sees one question per page, with Previous and
Next controls and a numbered navigator that distinguishes answered from unanswered questions.

Changing pages saves the current response before navigation. The final review page requires explicit submission.
Unanswered questions are allowed; a blank answer has no stored response. Submitted answers are immutable.

Collection closes when every frozen participant submits, the deadline is due, or the host ends it early.

### 4. Analyze

In coverage-aware mode, Junto:

1. freezes the room snapshot and claims one analysis attempt;
2. classifies each non-empty answer against the host-approved units;
3. independently clusters primary response families;
4. validates and merges both structured results by opaque participant ID;
5. runs the coverage-first CP-SAT optimizer;
6. atomically stores and publishes the semantic and grouping artifacts.

The interface reports actual stages, never a fabricated percentage. A semantic or optimizer failure publishes no partial
artifact, changes the room to `failed`, and exposes a sanitized host message. A bounded retry reuses the frozen room
data.

The development-only placeholder mode skips semantic analysis and labels its capacity partition as `placeholder`. The
recorded mode uses reviewed fixture outputs and the real optimizer for deterministic offline testing.

Development hosts may add a deterministic set of 5, 10, or 20 simulated participants in the lobby. After starting, they
explicitly choose either network-free patterned load responses or an OpenRouter run using the configured pinned model
pool. No simulation runs automatically, and generated students are test actors rather than evidence that the semantic
classifier is accurate.

### 5. Discuss

The host sees all groups and enough evidence to audit the result: members, question coverage, missing units, eligible
carriers, represented families, original group answers, solver status, feasibility status, and whether each reported
objective was proven optimal.

Each participant sees only their own group and a concise discussion agenda. Participants do not receive other groups or
a raw-answer audit.

## Reference material and model disclosure

Room uploads and question-specific reference text provide context to the coverage classifier. They are never exposed
through participant room projections. Material participants need to answer the question should therefore also appear in
the prompt.

An authoring suggestion is a separate, host-initiated pre-room model call. For an uploaded file, Junto performs the same
bounded server-side extraction and sends extracted text rather than original file bytes. It also sends the activity
title and all current draft prompts and units. It sends no participant data because no participant flow is involved.
Authoring requests use structured output, `store=false`, and no tools; suggestions are not stored until the host later
creates the activity through the ordinary draft workflow.

In live OpenAI mode, question text, relevant reference text, coverage units, opaque participant IDs, and answer text are
sent to the configured model provider. Display names, join codes, session data, group-size constraints, and tentative
groups are excluded. The join experience discloses external processing before accepting a name in coverage-aware mode.

Hosts should not upload secrets or unnecessary personal data. Junto's anonymous access model minimizes identity
collection; it does not make submitted content non-sensitive.

## Supported envelope

| Input                            |                       Limit |
| -------------------------------- | --------------------------: |
| Questions per room               |                         1-8 |
| Coverage units per question      |          1-8 before opening |
| Participants per room            |                          60 |
| Answer length                    |            1,500 characters |
| Question prompt                  |            4,000 characters |
| Question-specific reference text |            8,000 characters |
| Display name                     |               80 characters |
| Room title                       |              120 characters |
| Activity duration                |               1-180 minutes |
| Group-size bounds                |                         2-8 |
| Uploaded files per room          |                           8 |
| Uploaded file size               |                  5 MiB each |
| Extracted text                   | 100,000 characters per file |

Supported file extensions are `.txt`, `.md`, `.pdf`, and `.docx`. Legacy `.doc`, RTF, image-only or unreadable
documents, invalid UTF-8 text, and unsupported types are rejected. PDF pages and DOCX expanded archive size are bounded
before full extraction.

## Guarantees

For accepted inputs and a healthy configured runtime, Junto guarantees:

- the documented room-state transitions are enforced by the server;
- the cohort, start time, and deadline are frozen once;
- submitted answers cannot change and late writes are rejected;
- every published participant appears in exactly one group;
- each published group matches its predetermined valid capacity;
- coverage is derived only from that participant's validated answer assignment;
- family membership never creates coverage;
- lower-priority policy objectives cannot reduce an optimizer value already fixed as optimal;
- solver timeout, feasibility, fallback, and optimality are labelled without overclaiming;
- semantic and grouping artifacts become public only together with `published`;
- host and participant projections enforce room-scoped access and own-group isolation;
- PostgreSQL-backed rooms and answers survive application restarts;
- room deletion cascades across the room's stored data.

These are software invariants, not claims that every model judgment is correct.

## Non-guarantees and non-goals

Junto does not guarantee:

- complete coverage when there are too few carriers or incompatible constraints;
- semantic infallibility, grading accuracy, teaching ability, engagement, or balanced personalities;
- an optimal solver result after its configured time limit unless the relevant status says so;
- improved learning outcomes without a separate controlled evaluation;
- durable execution of an in-flight analysis across process termination;
- institutional compliance, multi-region availability, or unrestricted production scale.

The current product intentionally omits accounts, saved cross-room history, LMS integration, participant chat, manual
group editing, WebSockets, multiple analysis versions, and cross-room semantic analytics.
