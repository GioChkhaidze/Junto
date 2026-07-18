# Junto: Product and Optimization Proposal

## 1. Product definition

Junto is an accountless, room-based system for forming live discussion groups from submitted answers.

Any person can host a room: a professor running a class activity, a student organizing a study session, or a facilitator collecting ideas. Participants join with a code, answer the room's questions, and receive a group after Junto analyzes the response set.

Junto's core promise is:

> Form valid groups that collectively contain the strongest feasible coverage of every question's host-approved ideas.

When complete coverage is proven feasible within the supported room limits, every group receives it. When complete coverage is impossible, Junto distributes the available ideas as fairly as possible and identifies what each group is missing.

Junto supports two grouping policies:

- **Teach Each Other:** preserve coverage and distribute useful contributions across group members;
- **Explore Different Approaches:** preserve coverage and increase the number of distinct response approaches represented in each group.

Junto optimizes group composition. It does not claim that a discussion occurred successfully or that learning was achieved.

## 2. Problem

Open-ended answers contain information that random grouping ignores. One participant may supply a definition, another a missing reasoning step, and another a different method or position. A useful group should contain enough of those pieces to discuss every question.

A host can perform this grouping manually, but reading a full response set and satisfying group-size constraints is too slow during a live activity.

Junto separates the work:

1. a general-purpose language model compiles the current room's answers into a small semantic artifact;
2. a deterministic optimizer partitions participants from that artifact.

The language model interprets text. The optimizer enforces coverage, group size, and policy objectives.

## 3. Room workflow

```text
Create room
Add questions and optional reference material
Generate and approve coverage units
Open room
Collect answers
Freeze responses
Compile response families and per-response coverage
Choose balanced group capacities
Optimize the selected policy
Review and publish groups
Discuss
```

The discussion ends the Junto workflow. The product does not require confidence ratings, a second answer, a group submission, or a post-discussion survey.

## 4. Semantic contract

Each question has two independent semantic structures:

- **coverage units** describe the important ideas that should be available inside every group;
- **response families** describe the primary approach, reasoning pattern, or position expressed by each answer.

Every response also records which coverage units it substantively contains.

Two answers can use the same approach while covering different ideas. Two answers can cover the same ideas through different approaches.

### 4.1 Coverage units

A coverage unit is a small, host-approved primitive that matters to the question's intended discussion.

For a dynamic-programming question:

```text
State definition
Recurrence
Base cases
Evaluation order
Time and space complexity
```

For a philosophy question:

```text
Central position
Supporting argument
Principal objection
Response to the objection
Practical implication
```

For a design question:

```text
User need
Proposed mechanism
Differentiator
Tradeoff
Primary risk
```

Coverage units are generated from the question and optional reference material, then accepted or edited by the host before the room opens. Host approval makes the resulting set the room's operational definition of complete coverage.

A question should normally contain one to eight units. Each unit must be:

- question-local;
- independently present or absent in an answer;
- meaningful to the intended discussion;
- specific to the actual content rather than a generic slot such as “argument” or “evidence”;
- concise enough to display in a group agenda;
- grounded in the supplied question, answer, rubric, reading, or learning objective when such material is provided.

All accepted units are required and equally important. Optional details should not be included as coverage units.

Coverage units remain hidden while participants answer. They appear after grouping as the discussion checklist.

### 4.2 Per-response coverage

A response covers a unit when it substantively expresses that unit.

For correctness-sensitive units, an invalid formula, false fact, or broken reasoning step does not count. For open-ended questions, a relevant position or objection can count without being treated as the only acceptable conclusion.

Coverage is binary and question-local:

```text
response contains unit
response does not contain unit
```

There are no confidence values, mastery values, edge weights, or partial-credit coefficients.

### 4.3 Response families

A response family is a question-local label for a shared primary approach, reasoning pattern, or position.

Examples:

```text
Top-down memoization
Bottom-up tabulation
Geometric construction
Consequentialist justification
Rights-based objection
Institutional explanation
Economic explanation
```

Each non-empty response receives at most one primary family. A materially hybrid response can receive its own hybrid family. A response with no coherent approach can have no family while retaining any coverage units it clearly expresses.

Families are used for **Explore Different Approaches** and as a late tie-break in **Teach Each Other**. Family identity never substitutes for required coverage.

### 4.4 Minimal semantic artifact

For each question, Junto stores:

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
```

The artifact contains one family assignment and one coverage set per participant-question response. Its size is linear in participants and questions; it contains no pairwise response matrix, duplicated member arrays, embeddings, model confidence, or predicted learning score.

## 5. Semantic compilation

### 5.1 Coverage compilation

Before the room opens, the model receives:

```text
question
optional reference answer, rubric, reading, or learning objective
```

It returns an ordered list of unit texts. The application assigns unit IDs. The host can edit, delete, regenerate, or approve the units.

For correctness-sensitive questions, the host should provide authoritative material or manually verify the units. Junto does not independently establish a universal answer key.

### 5.2 Response compilation

After responses freeze, Junto makes one model call per question. The model receives:

```text
question
optional reference material
accepted coverage units with fixed IDs
opaque participant IDs and non-empty answers
```

It returns:

```text
family labels
one family index or null per response
covered unit IDs per response
```

The application validates family indices and converts them to canonical family IDs.

The compiler follows these rules:

- cluster by primary reasoning, method, or position;
- use one family for answers interchangeable for approach diversity;
- preserve materially different approaches as separate families;
- ignore writing style, verbosity, confidence, identity, and personality;
- count only substantively expressed coverage units;
- include every submitted participant ID exactly once;
- return no participant names and no repeated answer text;
- return no unused families.

A schema-invalid result receives one repair attempt. A second failure stops analysis and returns a host-visible error.

### 5.3 Semantic limitation

Schema validation can prove that IDs and fields are structurally correct. It cannot prove that the model's semantic judgment is correct.

The semantic compiler must be evaluated on reviewed examples from multiple subjects. Junto's optimizer is only as accurate as the coverage and family artifact it receives.

## 6. Group-size model

The host supplies:

```text
minimum group size
preferred group size
maximum group size
```

For `n` participants, a group count `m` is feasible when:

\[
\left\lceil \frac{n}{\text{maximum}} \right\rceil
\le m \le
\left\lfloor \frac{n}{\text{minimum}} \right\rfloor
\]

If no feasible `m` exists, Junto asks the host to change the size range. It never violates the stated bounds.

Among feasible counts, Junto chooses the count whose average size is closest to the preferred size. Ties prefer the larger number of groups. Capacities are balanced using `floor(n / m)` and `ceil(n / m)` and fixed before semantic optimization.

Example:

```text
23 participants
minimum 3
preferred 4
maximum 5

capacities: 4, 4, 4, 4, 4, 3
```

The language model never receives group-size information.

## 7. Optimization model

Junto uses an integer constraint solver. OR-Tools CP-SAT is the proposed implementation.

Let:

- `S` be participants;
- `Q` be questions;
- `Uq` be accepted units for question `q`;
- `Fq` be response families for question `q`;
- `a[s,q,u]` equal `1` when participant `s` covered unit `u`;
- `f[s,q]` be the participant's family or null;
- `G` be fixed group slots and capacities.

### 7.1 Assignment variables

```text
x[s,g] = 1 when participant s belongs to group g
```

Hard constraints:

```text
Every participant belongs to exactly one group.
Every group matches its fixed capacity.
```

### 7.2 Coverage variables

```text
covered[g,q,u] = 1 when at least one member of group g covered unit u
full[g,q]      = 1 when every accepted unit for question q is covered
```

`covered[g,q,u]` is the logical OR of the assignment variables for participants who carry that unit.

For exact normalization, let:

\[
L = \operatorname{lcm}(|U_q| : q \in Q)
\]

Then:

\[
coverageScore(g,q)
=
\frac{L}{|U_q|}
\sum_{u \in U_q} covered[g,q,u]
\]

Every question has the same maximum score `L`, using integer coefficients only.

### 7.3 Complete-coverage feasibility

A necessary precheck requires every unit to have at least as many carriers as there are groups. This is not sufficient because the same participants may carry overlapping units.

Junto therefore runs an exact feasibility solve with:

```text
covered[g,q,u] = 1
for every group, question, and accepted unit
```

If a full-coverage assignment is found, complete coverage becomes a hard constraint.

If infeasibility is proven, Junto solves these objectives lexicographically:

1. maximize the worst `coverageScore(g,q)` across all group-question pairs;
2. maximize the minimum number of fully covered questions received by any group;
3. maximize the total number of fully covered group-question pairs;
4. maximize total normalized coverage.

If the feasibility solve times out without a witness or proof, status is `unknown`; it is never reported as infeasible.

Each proven objective value is fixed before the next objective begins. No weighted educational score is used.

## 8. Teach Each Other policy

After the best feasible coverage is fixed, the policy favors groups whose useful material can be distributed across more members.

The solver creates temporary variables:

```text
contributes[s,g,q,u] = 1 when participant s is selected as one carrier
                       of unit u for group g and question q
```

For every available group-question-unit, exactly one eligible member is selected. These variables exist only inside the solver and are not persisted or shown as mandatory speaking assignments.

A participant is active when at least one available unit is allocated to them. The policy then solves:

1. maximize the minimum number of active contributors in any group;
2. minimize the maximum number of units allocated to any participant;
3. maximize the total number of active contributors;
4. maximize response-family variety as a final tie-break.

This tests whether the group's coverage can be distributed across several members rather than depending on one response for nearly everything.

The participant page still shows every eligible carrier for each unit. The group decides who explains it.

## 9. Explore Different Approaches policy

After the best feasible coverage is fixed, the policy favors distinct non-null response families.

For each group and question:

```text
familyCount[g,q] = number of distinct represented families
diverse[g,q]     = 1 when familyCount[g,q] >= 2
```

The policy solves:

1. maximize the minimum number of diverse questions received by any group;
2. maximize the total number of diverse group-question pairs;
3. maximize normalized additional-family coverage.

For normalization, one represented family is the baseline:

\[
\frac{\max(0, familyCount(g,q)-1)}
     {\max(1, \min(capacity_g, |F_q|)-1)}
\]

Questions with fewer than two non-null families contribute no diversity value.

The optimizer does not classify a difference as a debate, contradiction, or motif. It preserves coverage and distributes distinct observed approaches.

## 10. Solver execution

```text
1. Validate participant count and group-size feasibility.
2. Fix balanced group capacities.
3. Build assignment, coverage, family-presence, and policy variables.
4. Run the complete-coverage precheck and exact feasibility solve.
5. Lock complete coverage or solve the coverage fallback objectives.
6. Solve the selected policy objectives lexicographically.
7. Canonicalize group labels and store only the participant partition.
```

The solver uses stable participant ordering, one search worker, and a fixed seed. A time-limited optimization result is labeled `feasible` unless optimality is proven.

## 11. Published discussion view

The grouping artifact contains only the partition:

```json
{
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

`fullCoverageStatus` is `feasible`, `infeasible`, or `unknown`.

Coverage, missing units, unit carriers, and represented families are derived when the page is rendered.

Teach Each Other:

```text
Question 2 — Build the complete explanation together

State definition — mentioned by Maya and Alex
Recurrence — mentioned by Maya
Base cases — mentioned by Omar
Evaluation order — mentioned by Noor
Complexity — mentioned by Noor and Alex

Coverage: complete
```

Explore Different Approaches adds:

```text
Approaches represented
- top-down memoization
- bottom-up tabulation
- greedy construction
```

Incomplete coverage is shown explicitly. Junto never converts a missing unit into a generated answer.

## 12. Product guarantees

Given a validated semantic artifact, Junto can guarantee:

- every participant appears exactly once;
- every group satisfies its fixed capacity;
- complete coverage is enforced when the solver proves it feasible;
- infeasible coverage is distributed according to the stated lexicographic objectives;
- the selected policy is applied after coverage;
- published diagnostics match the stored responses and semantic artifact.

Junto cannot guarantee:

- that the language model interpreted every answer correctly;
- that a participant can teach every idea detected in their response;
- that discussion quality or learning will improve.

Those claims require empirical evaluation rather than additional optimizer fields.

## 13. Hackathon validation

### Semantic validation

Use reviewed response sets from at least two unrelated subjects. Compare model `coveredUnitIds` and family assignments with human judgments.

### Optimization validation

Use generated and hand-built fixtures to verify group sizes, full coverage when feasible, fair fallback when infeasible, and policy-specific behavior.

### Product validation

Run the full room flow with approximately twenty-four participants and five questions. Measure latency and confirm that a host can understand why each group was formed.

A structurally valid grouping built from a wrong semantic artifact is still a wrong result.

## 14. Strategic path

The hackathon product is standalone and accountless. Its durable core is independent of the question-entry and answer-collection interface:

```text
questions and reference material
participant responses
semantic compilation
coverage-constrained grouping
published discussion agenda
```

A later Canvas or Kahoot integration can supply questions and responses and receive the grouping result without changing the semantic or optimization contracts.
