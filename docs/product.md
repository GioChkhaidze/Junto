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
- reopen rooms while the same browser retains its signed host capability;
- permanently delete a room by confirming its invite code.

### Participant

A participant exists only inside one room. Their browser session can:

- join an open lobby using a display name;
- read question prompts and edit only their own answers while collection is open;
- submit once, making those answers final;
- retrieve only the published group containing their participant ID;
- use a per-question agenda showing covered and missing units, eligible carriers, and represented families for that
  group.

There are no profiles, email addresses, passwords, OAuth providers, teacher accounts, or cross-room participant
identities. Draft and live rooms remain private to their host browser. Once published, an activity becomes a durable,
read-only result in the shared Activities index so it can be reviewed from another browser without granting host access.

## Experience

```text
draft -> lobby -> answering -> analyzing -> published
                                      \-> failed -> bounded retry
```

### 1. Author

The host first receives an optional material step. UTF-8 text, Markdown, PDF, and DOCX files are extracted on the
server; original source bytes are not retained. The host then sets room timing and group bounds and writes one to eight
questions with one to eight coverage units each.

When reference material and a configured provider credential are present, a host may request a suggestion for one
question prompt or one question's coverage units. This authoring capability is independent from the activity-analysis
engine. OpenRouter is preferred when configured; direct OpenAI is the fallback. The request includes the activity title,
reference text, and complete current question-and-unit draft so the suggestion can avoid repetition and stay coherent.
The interface applies only the requested target, keeps the result editable, and asks the host to review it.

Generated questions contain one central task and are limited to 32 words and 280 characters. Generated coverage units
are atomic phrases limited to 10 words and 80 characters, with no more than five returned for one question. These
tighter limits apply to AI suggestions; hosts can still edit the draft through the ordinary authoring limits.

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

When simulation is explicitly enabled, hosts may add a bounded set of simulated participants in the lobby.
Coverage-aware rooms offer an explicit OpenRouter action when configured. It uses the single server-owned full
`google/gemini-2.5-flash` model. Its data boundary is defined in
[Reference material and model disclosure](#reference-material-and-model-disclosure).

Patterned responses are labelled flow-only placeholders. The normal host UI does not offer them, and the backend accepts
them only with placeholder analysis. They contain no semantic-quality claim and are never a fallback for a
coverage-aware run. No simulation runs automatically. Generated students are test actors, not gold answers or evidence
that the semantic classifier is accurate.

OpenRouter generation sends one anonymous student per request, runs at most five requests concurrently, and shows
elapsed time while active. The server applies a two-minute deadline and the browser stops waiting shortly afterward. A
student is submitted only after their complete answer set validates. A timeout or provider failure keeps already
submitted simulated students and lets the host retry only the remaining roster. Success shows the source, model,
participant count, and response count before analysis finishes.

### 5. Discuss

The host first sees each group as one compact roster line. Opening a group reveals its questions; opening a question
reveals numbered coverage units, their short descriptions and carriers, plus a family-to-student map. The answer audit
is an explicit third layer and refers to covered units by number so their full text is not repeated.

The Activities page lists every published result stored in PostgreSQL plus draft or live rooms granted to the current
browser. Published rows open read-only group reports in any browser. Host-granted rows also expose manual deletion. This
is an activity-result index, not an account or submission-event log.

Each participant sees only their own group and a concise discussion agenda. Participants do not receive other groups or
a raw-answer audit.

## Reference material and model disclosure

Room uploads and question-specific reference text provide context to the coverage classifier. They are never exposed
through participant room projections. Material participants need to answer the question should therefore also appear in
the prompt.

When a host explicitly starts OpenRouter simulation, Junto sends the activity title, ordered prompts, anonymous
behavioral traits, and bounded room-wide uploaded or pasted source text. It sends extracted text without upload
filenames, display names, persona labels, room IDs, question IDs, or participant IDs. It also excludes host-only
question notes/reference, coverage units, expected labels, family assignments, and group settings. This does not make
source material visible on human participant pages.

An authoring suggestion is a separate, host-initiated pre-room model call. For an uploaded file, Junto performs the same
bounded server-side extraction and sends extracted text rather than original file bytes. It also sends the activity
title and all current draft prompts and units. It sends no participant data because no participant flow is involved.
Authoring requests use structured output and no tools. OpenRouter requests deny provider data collection and require
zero-data-retention routing; direct OpenAI fallback requests set `store=false`. Suggestions are not stored until the
host later creates the activity through the ordinary draft workflow.

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
