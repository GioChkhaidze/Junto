# Junto: Product and Optimization Proposal

## 1. Product definition

Junto is an anonymous, room-based discussion orchestration system. It turns a set of submitted answers into groups whose members collectively represent the concepts, reasoning steps, evidence, arguments, objections, perspectives, or other elements needed for a productive discussion.

The core guarantee is precise:

> Every group receives the strongest feasible coverage of the question's required ideas and productive perspectives.

Each coverage unit should be carried by at least one member of every group whenever the submitted responses make that feasible. Different members may carry different units. When full coverage is mathematically impossible, Junto produces the strongest feasible distribution and reports exactly what each group is missing.

Junto is host-agnostic:

- a professor can create a classroom room;
- a student can create a study room;
- a hackathon participant can create an idea-matching room;
- any person can create questions and invite others.

`Host` is a capability inside one room, not a permanent user type. Participants and hosts do not need accounts or profiles.

The initial product is a standalone web application. Its primary Build Week use case is education, but its room model does not encode institutional roles.

## 2. Problem

A host can distribute questions quickly but cannot reliably inspect dozens of open-ended answers and form high-coverage groups before a discussion begins.

Random grouping may leave some groups without required concepts, evidence, reasoning steps, or productive perspectives. Manual grouping can address that problem, but reading every response and satisfying group-size constraints takes too long during a live activity. Coarse answer buckets also lose useful structure: two responses may reach similar conclusions through different approaches, while two responses in one approach family may differ substantially in coverage.

Junto performs two separate operations:

1. a language model compiles anonymous written answers into a discrete, auditable semantic artifact;
2. a deterministic optimizer constructs valid groups from that artifact.

The language model does not create groups. The optimizer does not interpret prose.

Junto guarantees group composition properties, not conversation behavior or learning outcomes. Its immediate value is making question-dependent coverage fast, explicit, and verifiable.

## 3. The room model

One room contains one question set and one live run:

```text
room
├── host capability
├── questions and accepted coverage units
├── anonymous participants
├── submitted responses
├── semantic analysis result
└── selected grouping result
```

A room moves through this lifecycle:

```text
draft → open → analyzing → ready → published
                         ↘ failed
```

- `draft`: the host edits questions and coverage units;
- `open`: participants join and edit their own answers;
- `analyzing`: responses are frozen while semantic compilation and optimization run;
- `ready`: the host can inspect the proposed grouping;
- `published`: each participant can retrieve their own group;
- `failed`: the host can inspect the failure and retry.

Room creation returns two capabilities:

```text
join code   shared with participants
host token  retained privately by the creator
```

Joining creates a participant-scoped capability:

```text
participant token  identifies one participant inside one room
```

Possession of the host token grants room control. Possession of a participant token grants access only to that participant's answers and published group.

## 4. Primary workflow

1. A host creates a room.
2. The host adds one or more questions and reference material.
3. Junto derives the required coverage units for each question.
4. The host reviews and edits those units.
5. The host opens the room and shares its join code.
6. Participants join anonymously and submit their normal written answers.
7. The host presses **Generate groups**, which atomically freezes responses.
8. Junto maps each response to its covered units and response family.
9. Junto tests whether every group can fully cover every question.
10. The optimizer produces the selected grouping policy from the semantic artifact.
11. The host reviews coverage and publishes the groups.
12. Each participant sees their group, the coverage checklist, the members who carried each unit, and the represented approaches.

No second submission, survey, confidence score, or permanent participant record is required.

## 5. Semantic model

Junto uses two independent question-local structures:

- **Coverage units** define the concepts, reasoning steps, evidence, arguments, objections, perspectives, or other elements that should be represented inside each group.
- **Response families** describe the approach, reasoning pattern, or position expressed by an answer.

A response also records which coverage units it substantively represents.

This separation matters. Two participants may use the same approach with different coverage, while two high-coverage responses may use different approaches.

### 5.1 Coverage units

Coverage units are small, self-contained elements that matter to the question and intended discussion. They are derived from the question and its reference answer, rubric, source material, or learning objectives before participants respond.

For a math or programming question, the units might be:

```text
U1  State definition
U2  Recurrence
U3  Base cases
U4  Evaluation order
U5  Time and space complexity
```

For a philosophy question, they might be:

```text
U1  Central position
U2  Supporting argument
U3  Objection
U4  Counterargument
U5  Implication
```

For a history question, they might be:

```text
U1  Relevant evidence
U2  Interpretation of that evidence
U3  Competing explanation
U4  Limitation of the interpretation
```

For a design question, they might be:

```text
U1  User need
U2  Proposed approach
U3  Tradeoff
U4  Risk
```

Coverage units define what full coverage means for that question inside the room. They are not scores, weights, keywords, confidence estimates, or a permanent subject ontology.

Coverage semantics follow the question:

- for objectively answerable questions, the host can define units that encode correctness;
- for open-ended questions, units encode relevant argumentative, evidentiary, conceptual, or perspectival coverage without prescribing one correct conclusion;
- response families capture competing approaches or positions independently of unit coverage.

Each unit must be:

- grounded in the host-provided reference material;
- aligned with the host's intended scope for the question;
- atomic enough to be independently present or absent;
- substantial enough to matter to the answer;
- understandable to the host and participants;
- limited to a compact set, normally three to seven units per question.

The host can edit, delete, or regenerate units before opening the room. Opening is blocked until every question has at least one accepted unit.

### 5.2 Coverage in a response

A response covers a unit only when it substantively represents the element described by that unit.

These do **not** count as coverage:

- merely repeating a related keyword;
- referring to an element only incidentally without developing it;
- mischaracterizing an element relative to the host-approved unit definition;
- including the idea only in quoted reference material without using it in the answer.

When an objective unit itself requires a valid formula, fact, or reasoning step, an invalid version does not cover that unit. For an open-ended unit such as a position, objection, or competing explanation, substantive representation can count even when another participant defends the opposite view.

The artifact uses the subject-neutral field `coveredUnitIds`.

### 5.3 Response families

After responses freeze, Junto compiles one question at a time. A family represents a shared core approach, reasoning pattern, or position. It does not represent writing style, confidence, personality, or general ability.

Examples include:

```text
Top-down memoization
Bottom-up tabulation
Greedy construction
Consequentialist argument
Rights-based objection
Geometric solution
Algebraic solution
```

Each substantive response receives one primary family. A blank or incoherent response has no family. Opposing positions can each form valid families, and neither becomes incorrect merely because the other is represented.

Families support the **Explore Different Approaches** policy. They complement but do not substitute for coverage units.

## 6. Minimal AI artifacts

### 6.1 Coverage compilation

```ts
type CoverageCompilation = {
  questionId: string;
  units: Array<{
    id: string;
    text: string;
  }>;
};
```

### 6.2 Response compilation

```ts
type ResponseCompilation = {
  questionId: string;
  families: Array<{
    id: string;
    label: string;
  }>;
  assignments: Array<{
    participantId: string;
    familyId: string | null;
    coveredUnitIds: string[];
  }>;
};
```

Family membership and unit carriers are derived from `assignments`. The artifact contains no duplicated member arrays, confidence values, mastery scores, embeddings, pairwise student relations, predicted learning gains, or custom-trained model outputs.

Missing answers are represented locally as:

```json
{
  "participantId": "p7",
  "familyId": null,
  "coveredUnitIds": []
}
```

No fake empty response row is persisted.

## 7. Language-model responsibilities

The language model acts as a room-level semantic compiler.

### Coverage compilation input

```text
Question
Reference answer, rubric, source text, or learning objectives
```

### Coverage compilation output

```text
A compact set of required coverage units
```

### Response compilation input

```text
Question
Reference material
Accepted coverage units
Anonymous participant IDs and submitted answer text
```

### Response compilation output

```text
Question-local response families
One family assignment per substantive response
Coverage units substantively represented by each response
```

The model never receives host tokens, participant tokens, or participant display names. Every output is validated against a strict schema.

Validation requires:

- the exact question ID;
- every submitted participant ID exactly once;
- no invented participant IDs;
- unique family IDs;
- valid family references;
- valid coverage-unit references;
- no duplicate unit IDs inside an assignment;
- no extra fields.

Malformed output receives one repair attempt containing the validation errors. A second failure marks the room failed and preserves a host-visible diagnostic.

The model does not receive group constraints or tentative assignments and does not create groups.

## 8. Grouping policies

Both policies use the same saved semantic artifact and share the same non-negotiable first objective: the strongest feasible coverage of the question's required elements.

### 8.1 Teach Each Other

Purpose:

> Give every group complete coverage when feasible, then avoid making one participant the sole carrier of most of the group's useful contributions.

This is the default policy for worksheets, lecture checks, exam review, problem sets, and general peer instruction.

### 8.2 Explore Different Approaches

Purpose:

> Preserve the strongest feasible coverage, then expose groups to more distinct submitted approaches or positions.

This policy fits alternative solution methods, competing interpretations, opposing arguments, and different design strategies.

The host selects one policy. Junto generates and stores only that grouping. Changing the policy reruns only the optimizer from the saved semantic artifact; it does not call the language model again.

## 9. Group-size model

The host provides:

```text
minimum group size
preferred group size
maximum group size
```

Junto fixes the number and capacities of groups before semantic optimization. This prevents the optimizer from creating fewer, oversized groups merely because larger groups make coverage easier.

For `n` participants, Junto selects a feasible group count closest to the preferred size, then creates balanced capacities that differ by at most one and remain within the allowed range.

Example:

```text
23 participants
minimum 3
preferred 4
maximum 5

capacities: 4, 4, 4, 4, 4, 3
```

Group size is an optimizer constraint and is never sent to the semantic compiler.

## 10. Optimization model

Junto uses CP-SAT with Boolean and integer variables.

### 10.1 Inputs

Let:

- `S` be participants;
- `Q` be questions;
- `Uq` be required coverage units for question `q`;
- `Fq` be response families for question `q`;
- `a[s,q,u]` be `1` when participant `s` covered unit `u`;
- `f[s,q]` be the response family of participant `s` for question `q`;
- `G` be fixed group slots and capacities.

### 10.2 Assignment variables

```text
x[s,g] = 1 when participant s is assigned to group g
```

Hard constraints:

```text
Every participant belongs to exactly one group.
Every group has its predetermined capacity.
```

### 10.3 Coverage variables

```text
unit[g,q,u] = 1 when at least one member of group g covered unit u
full[g,q]   = 1 when every required unit for question q is present in group g
```

Unit availability is the logical OR of the assigned members who covered that unit.

For every fully covered group-question pair:

```text
For every required unit u,
at least one assigned participant has a[s,q,u] = 1.
```

This is Junto's central invariant.

### 10.4 Exact full-coverage feasibility

The solver first tests:

```text
unit[g,q,u] = 1
for every group g, question q, and required unit u
```

If feasible, those constraints remain hard for the rest of the solve.

If infeasible, Junto does not pretend the groups are complete. It solves lexicographically:

1. maximize the worst normalized coverage of any group-question pair;
2. maximize the minimum number of fully covered questions received by any group;
3. maximize the total number of fully covered group-question pairs;
4. maximize total normalized coverage.

Normalization prevents questions with more units from dominating the objective.

The result includes a coverage report identifying every missing group-question-unit combination.

## 11. Teach Each Other optimization

After the common coverage objectives are fixed, the default policy improves the distribution of useful knowledge.

For each group, a participant is an active coverage contributor when they carry at least one required unit for at least one question.

The policy continues lexicographically:

1. maximize the minimum number of active coverage contributors in any group;
2. maximize the total number of active contributors;
3. minimize the largest concentration of uniquely carried units on one participant;
4. maximize response-family variety as a final tie-breaker.

Junto does not appoint formal explainers or decide who must speak. The group page shows all members whose submissions carried each unit, and the group decides how to conduct the discussion.

## 12. Explore Different Approaches optimization

After the common coverage objectives are fixed, this policy uses response-family identity.

For each group and question:

```text
represented families = distinct non-null families among group members
```

The policy continues lexicographically:

1. maximize the minimum number of questions on which every group contains at least two families;
2. maximize total group-question pairs containing at least two families;
3. maximize normalized distinct-family count;
4. minimize the largest normalized concentration of one non-null family;
5. maximize coverage-contributor distribution as a final tie-breaker.

Response-family variety never substitutes for required-unit coverage.

## 13. Solver execution

Recommended execution:

```text
1. Fix balanced group capacities.
2. Build assignment, coverage, family-presence, and contributor variables.
3. Test exact full coverage.
4. Lock full coverage or solve the coverage fallback objectives.
5. Solve the selected policy objectives lexicographically.
6. Persist the selected grouping and its objective values as one JSON artifact.
7. Derive the group pages from the analysis and grouping artifacts.
```

For each lexicographic objective:

1. solve;
2. record the optimum;
3. add a constraint fixing that value;
4. solve the next objective.

Do not combine educational objectives with arbitrary weighted sums.

Equivalent group labels create search symmetry. Use stable participant ordering, stable group labels, a deterministic seed, one CP-SAT search worker, and symmetry-breaking constraints. If the solve limit expires, publish only a valid feasible result and record that optimality was not proven.

## 14. Discussion output

The participant group page contains one section per question.

### Teach Each Other

```text
Question 2: Construct a response using every required element.

Required coverage units:
✓ State definition — present in Maya and Alex's submissions
✓ Recurrence — present in Maya's submission
✓ Base cases — present in Omar's submission
✓ Evaluation order — present in Noor's submission
✓ Complexity — present in Noor and Alex's submissions

Group coverage: complete
```

### Explore Different Approaches

```text
Question 2: Address every required element, then compare approaches.

Required coverage: complete

Approaches represented:
- top-down memoization;
- bottom-up tabulation;
- greedy construction.
```

The agenda is derived from accepted coverage units, response families, covered units, and group membership. It requires no post-group language-model call and no persisted explainer assignments.

## 15. Product boundaries

The hackathon product includes:

- anonymous room creation;
- question and reference-material entry;
- coverage-unit generation and host review;
- join-code participation;
- answer submission;
- semantic response compilation;
- exact coverage feasibility testing;
- Teach Each Other and Explore Different Approaches;
- constrained group optimization;
- host review and publication;
- participant-specific group pages and coverage agendas.

The hackathon product does not include:

- teacher, student, or organization profiles;
- OAuth, magic links, passwords, or permanent accounts;
- reusable activity ownership hierarchies;
- LMS integrations;
- permanent participant history;
- custom model training;
- vector databases;
- confidence or mastery scoring;
- formal speaker assignment;
- post-discussion assessment;
- claims that group composition alone guarantees learning.

## 16. Scaling path

The room model is deliberately small but not disposable.

Add infrastructure only after a concrete need appears:

- add optional accounts when hosts need saved rooms across devices;
- add a duplicate-room action when question-set reuse matters;
- add a durable queue and separate workers when concurrent analyses exceed one application process;
- add SSE or WebSockets when polling traffic becomes material;
- normalize semantic artifacts when cross-room analytics require relational queries;
- add Canvas, Kahoot, or other integrations after the standalone room workflow is validated;
- add versioned runs when audit history, model comparison, or experiments require them.

The durable strategic asset is the subject-flexible engine that converts open-ended responses into:

```text
required coverage units
response families
per-response coverage
valid coverage-maximizing groups
question-level discussion agendas
```

Junto occupies the step between collecting answers and beginning a productive group discussion.
