# Product contract

## Product definition

Junto is an accountless, room-based system for forming live discussion groups from submitted answers.

Any person can host a room: a professor running a class activity, a student organizing a study session, or a facilitator collecting ideas. Participants join with a code, answer the room's questions, and receive a group after Junto analyzes the response set.

Junto's core promise is:

> Form valid groups that collectively contain the strongest feasible coverage of every question's host-approved ideas.

When complete coverage is proven feasible, every group receives it. When complete coverage is impossible or cannot be proven within the solve limit, Junto returns the strongest valid assignment found and identifies missing units without claiming completeness.

Junto optimizes group composition. It does not claim that a discussion occurred successfully or that learning was achieved.

## Problem

Open-ended answers contain information that random grouping ignores. One participant may supply a definition, another a reasoning step, another a piece of evidence, and another a different approach or position. A useful discussion group should collectively contain as much of that question-relevant material as possible.

A host can perform this grouping manually, but reading a full response set while satisfying group-size constraints is too slow during a live activity.

Junto separates the work:

1. a language model independently classifies per-answer coverage and clusters answers into response families;
2. a deterministic optimizer partitions participants from that artifact.

The model interprets text. The optimizer enforces group size, coverage, and policy objectives.

## Actors

### Host

The person who creates one room. The host can:

- edit questions, reference material, coverage units, policy, and group-size bounds while the room is a draft;
- open the room and share its join code;
- see participation and submission progress and remove an unwanted participant while open;
- freeze responses and start analysis;
- review diagnostics, switch policy without additional model calls, and publish one grouping.

Host is a room-scoped capability, not a permanent user role.

### Participant

A person who joins one room with a display name. A participant can:

- submit and edit their own answers while the room is open;
- wait for analysis and publication;
- retrieve only the published group containing their participant ID.

A participant has no global profile or cross-room identity.

Junto is accountless and pseudonymous, not fully anonymous: it stores room-local display names and answers, and answer text is processed through the OpenAI API. Participants must see that disclosure before joining and should not submit sensitive personal information.

## Core concepts

### Coverage units

Coverage units are small, host-approved elements that matter to a question's intended discussion. They may represent:

- concepts or reasoning steps;
- evidence or interpretations;
- arguments, objections, or implications;
- perspectives or competing explanations;
- design needs, mechanisms, tradeoffs, or risks.

For correctness-sensitive questions, a unit may encode an objectively valid fact, formula, or reasoning step. For open-ended questions, units represent relevant coverage without prescribing one correct conclusion.

Coverage units are generated from the question and optional reference material, then edited or accepted by the host. Opening the room is the final approval boundary.

Reference material is host-only semantic context and may contain a rubric or answer key. Anything participants need to read belongs in the question prompt.

### Response families

A response family is a question-local label for a primary method, reasoning pattern, or position. Families capture approach diversity independently of coverage.

Two responses may share a family while covering different units. Two responses may cover the same units through different families.

A family itself has no coverage units. Coverage is attached only to an individual answer and must never be copied from, averaged across, or inferred from family membership. A null-family answer may still cover units.

Every positive coverage judgment must cite exact supporting text from that answer for server validation. This makes the judgment auditable, but a matching quote alone does not prove that the model interpreted the answer correctly.

### Grouping policies

Both policies optimize coverage first.

**Teach Each Other** favors groups whose available units can be represented across more members without overloading one contributor.

**Explore Different Approaches** favors groups containing more distinct non-null response families after coverage is fixed.

The host selects one policy. Switching policy reuses the stored semantic artifact and replaces only the grouping result.

## Primary workflow

```text
draft
  Create room
  Add questions and optional reference material
  Generate, edit, and approve coverage units
      │
      ▼
open
  Share join code
  Participants join and answer
      │
      ▼
analyzing
  Freeze joins and responses
  Classify coverage and cluster families independently
  Optimize the selected policy
      │
      ▼
ready
  Review groups and diagnostics
  Optionally switch policy
      │
      ▼
published
  Participants receive their discussion groups
```

Failure during analysis moves the room to `failed`, from which the host may retry.

## Required experience

### Host experience

1. Create a room without registration.
2. Configure title, policy, and group sizes.
3. Add questions and optional reference material.
4. Generate and edit coverage units.
5. Open the room and share a join code or QR code.
6. Watch participant and response counts update.
7. Remove an accidental or unwanted participant before analysis if needed.
8. Generate groups.
9. Review group membership, coverage, missing units, carriers, families, and original answers.
10. Switch policy without recompiling responses if desired.
11. Publish.

### Participant experience

1. Join with a code and room-scoped display name.
2. Submit answers from a responsive web page.
3. Wait while the host analyzes and reviews.
4. Receive group members, a per-question coverage checklist, unit carriers, represented approaches, and any missing-unit warning.

## MVP operating envelope

| Limit | Default |
|---|---:|
| Questions per room | 1–8 |
| Participants per room | 4–60 |
| Answer length | 1,500 characters |
| Coverage units per question | 1–8 |
| Group size | 2–8 |
| Main demo | 5 questions, 24 participants |

These limits are configurable safety boundaries, not permanent product claims.

## Product guarantees

Given a validated semantic artifact, Junto guarantees:

- every participant appears in exactly one group;
- every group satisfies its fixed capacity;
- complete coverage is enforced when a solver witness proves it feasible;
- missing coverage is reported rather than silently generated;
- policy objectives run only after the achieved higher-priority coverage values are fixed;
- a time-limited result is described as the best assignment found within the solve limit, not as proven optimal;
- published diagnostics are derived from the stored partition and semantic artifact.

Junto does not guarantee:

- that every model judgment is semantically correct;
- that a participant can teach every unit detected in their response;
- that group members will participate effectively;
- that learning outcomes will improve.

## MVP boundaries

Included:

- accountless room creation and joining;
- question authoring and optional reference material;
- coverage-unit generation and host approval;
- answer collection;
- independent per-answer coverage classification and response-family clustering;
- both grouping policies;
- host review and publication;
- participant discussion agenda;
- two subject fixtures and one deployed demo.

Deferred:

- permanent accounts and cross-device room recovery;
- reusable question libraries;
- Canvas, Kahoot, or institutional integrations;
- durable queues and separate workers;
- realtime presence, chat, or collaborative editing;
- cross-room analytics and normalized semantic tables;
- versioned analysis runs;
- custom model training or vector databases;
- post-discussion assessment.

## Product acceptance

The MVP is complete when:

- any person can complete the host flow without an account;
- participants can join and answer without accounts;
- room-scoped access prevents cross-room and cross-participant data access;
- host-approved coverage units compile into validated per-response coverage, independently of validated response families;
- group-size constraints are never violated;
- full coverage is enforced whenever a witness proves it feasible;
- partial coverage and unknown feasibility are represented honestly;
- policy switching reuses semantic analysis;
- host and participant screens derive consistent diagnostics;
- the five-question, twenty-four-participant fixture completes within the configured analysis budget;
- the same contracts work for dynamic-programming and philosophy fixtures.
