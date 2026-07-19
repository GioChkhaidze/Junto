# Product contract

## Product definition

Junto is an accountless, room-based website for forming live discussion groups from submitted answers.

Any person can host a room: an instructor running a class activity, a student organizing a study session, or a facilitator collecting ideas. A participant joins with a code and room-scoped display name, completes a timed questionnaire, and receives a group.

The intended product promise is:

> Form valid groups with the strongest feasible coverage of every question's host-approved ideas and productive perspectives.

The current first slice proves the complete room workflow, access model, timing, answer collection, and group delivery. Its grouping is a deterministic capacity-valid placeholder. It does not yet interpret answers or fulfill the coverage promise.

## Problem

Random grouping ignores what participants actually know or argue. One answer may supply a definition, another a reasoning step, another evidence, and another a competing position. A useful discussion group should collectively contain as much question-relevant material as possible while respecting group size.

Manually reading a complete response set and satisfying those constraints is slow during a live activity. Junto is designed to make that composition step fast, explicit, and auditable.

## Roles and access

### Host

Host is a capability for one room, not a permanent account type. The person who creates a room can:

- prepare its material, timing, questions, coverage units, policy, and group-size bounds;
- open an invite lobby and share its code or URL;
- see the lobby roster and remove accidental participants before the activity starts;
- start the shared timer, monitor progress, and finish collection early;
- see every published group and every member.

### Participant

A participant exists only inside one room. They can:

- join an available lobby with a display name;
- retrieve and edit only their own answers while collection is active;
- submit once and wait for the result;
- retrieve only the published group containing their participant ID.

There are no profiles, passwords, email addresses, OAuth providers, teacher accounts, or cross-room participant identities.

## Coverage units

Coverage units are the concepts, reasoning steps, evidence, arguments, objections, perspectives, or other elements that should be represented inside each group.

Examples differ by subject:

- math or programming: state definition, recurrence, base case, or complexity;
- philosophy: position, supporting argument, objection, counterargument, or implication;
- history: evidence, interpretation, competing explanation, or limitation;
- design: user need, approach, tradeoff, or risk.

For an objectively graded question, a host can encode correctness in the units. For an open-ended question, units describe relevant conceptual or argumentative coverage without requiring one conclusion.

Every question must have at least one host-approved coverage unit before the room can enter the lobby. The current placeholder stores and validates these units but does not classify answers against them. That classification belongs to the future semantic engine.

## Reference material

Reference material is optional, room-level context for authoring and future semantic analysis. The authoring flow accepts UTF-8 text, Markdown, PDF, and DOCX files and extracts readable text on the server. Upload metadata is visible to the host; participants receive only question prompts.

Material participants need in order to answer should therefore be written into the prompt. Uploaded material should not contain secrets or sensitive personal data.

## First-slice workflow

```text
draft -> lobby -> answering -> analyzing -> published
                                      \-> failed
```

### 1. Author

The host completes a focused sequence:

1. optionally upload room reference material;
2. set the room title, shared duration, policy, and group-size bounds;
3. write one to eight questions and one to eight coverage units for each;
4. review the activity and create its invite.

Draft authoring is the only editable configuration state.

### 2. Gather

Opening the room creates the invite lobby. Participants follow the URL or enter the join code, provide a display name, and wait. The host sees the roster.

Starting the activity freezes that exact participant cohort. New participants cannot join and existing members cannot be removed afterward. Start is rejected if the cohort cannot be divided within the configured group-size bounds.

### 3. Answer

The server records one shared start time and deadline. Each participant sees one question per page, with Previous and Next controls and a numbered question navigator showing answered state.

Moving between questions saves the current response before navigation. The final page summarizes completion and requires an explicit final submission. Blank text removes the stored response; unanswered questions are allowed.

After final submission, that participant's answers are immutable. Collection closes when every frozen participant submits, the server deadline expires, or the host ends it early.

### 4. Form and release groups

The room enters `analyzing`, then the current placeholder divides the frozen cohort into balanced groups near the preferred size while respecting minimum and maximum size. It uses stable join order, not answer content.

Groups are released automatically. The host room shows all groups and members. A participant room shows only that participant's group.

The interface must not call this placeholder output semantic, coverage-aware, AI-generated, optimized, optimal, or evidence that learning improved.

## Current operating limits

| Input | Limit |
|---|---:|
| Questions per room | 1-8 |
| Coverage units per question | 1-8 before opening |
| Participants per room | 60 |
| Answer length | 1,500 characters |
| Display name | 80 characters |
| Room title | 120 characters |
| Activity duration | 1-180 minutes |
| Group size bounds | 2-8 |
| Uploaded files per room | 8 |
| Uploaded file size | 5 MiB each |
| Extracted text | 100,000 characters per file |

Supported file extensions are `.txt`, `.md`, `.pdf`, and `.docx`. Text files must be UTF-8. Legacy `.doc`, RTF, image-only documents, unreadable files, and unsupported types are rejected.

## Current guarantees

Within one running FastAPI process, the first slice guarantees:

- one room follows only the documented state transitions;
- the participant roster is frozen exactly once when the activity starts;
- the server owns start time, deadline, remaining time, and allowed actions;
- a submitted participant cannot change answers;
- no response is accepted after collection closes;
- every published participant appears in exactly one group;
- every placeholder group respects the configured minimum and maximum size;
- no partial groups are visible before `published`;
- host and participant projections enforce room-scoped access;
- a participant cannot enumerate other groups or retrieve other participants' answers;
- reference files are parsed as real content rather than represented by cosmetic upload records.

The first slice does not guarantee durability across a process restart, semantic correctness, coverage quality, policy-specific grouping, optimality, teaching ability, participation quality, or improved learning outcomes.

## Future semantic and optimization engine

The planned engine will replace only the grouping seam:

1. the OpenAI API will classify each answer's covered unit IDs and independently cluster question-local response families;
2. server validation will reject malformed or unsupported judgments;
3. OR-Tools CP-SAT will form capacity-valid groups, prioritizing coverage before policy-specific objectives.

Coverage will remain attached only to individual answers. A response family will represent a primary approach or position and will never own, grant, or imply coverage units. The model will interpret text but will never directly choose groups.

That engine is specified in [engine.md](engine.md) and deliberately not implemented in this slice.

## First-slice acceptance

The prototype slice is accepted when:

- a fresh browser can create and host a room without registration;
- three or more browser sessions can complete the lobby, timed questionnaire, submission, waiting, and group-result flow;
- desktop and narrow-screen layouts preserve the one-question-per-page interaction;
- navigation waits for a save result and exposes save failure honestly;
- the deadline and all-submitted paths each start grouping once;
- infeasible group sizes prevent activity start with a clear error;
- host-only, participant-only, cross-room, CSRF, validation, and post-submit mutations are rejected;
- automated backend tests, frontend tests, type checking, and production build pass;
- documentation and UI label the grouping result as a placeholder wherever technical provenance is shown.

OpenAI quality evaluation, OR-Tools invariants, PostgreSQL durability, deployment hardening, and evidence for improved learning are later acceptance gates, not hidden requirements of this first slice.
