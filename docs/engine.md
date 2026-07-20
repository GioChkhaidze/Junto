# Semantic and optimization engine

## Boundary

The implemented engine converts one frozen room snapshot into one participant partition:

```text
question + reference + approved units + answers
  -> coverage classification + transient evidence
  -> coveredUnitIds per answer -------------------+
                                                   +-> merge by opaque participant ID
question + answers                                 |
  -> independent family clustering                |
  -> family per answer ----------------------------+
                  |
                  v
         immutable SemanticArtifact
                  |
                  v
      coverage-first CP-SAT optimization
                  |
                  v
         immutable GroupingArtifact
```

The language model interprets prose but never receives group sizes or selects groups. The optimizer receives validated
IDs and relations but never sees answer text. These are separate failure and trust boundaries.

The live adapter uses the official OpenAI Python SDK, the Responses API, and Pydantic-backed Structured Outputs.
Requests are stateless (`store=false`), use no tools or previous response, and pin an explicit configured model.
`recorded` mode supplies reviewed responses through the same validation path without network access.

The development-only OpenRouter adapter implements the same `SemanticProvider` contract through strict JSON-schema Chat
Completions. It requires structured-output-capable routing, denies provider data collection, and uses a server-owned
pinned model pool shared with synthetic students.

## Coverage units and families

A coverage unit is a small, question-local, host-approved element that should be available inside each group. It may be
a concept, reasoning step, fact, argument, objection, perspective, mechanism, tradeoff, or risk. Hosts approve every
unit, and the semantic compiler never generates or changes them. A separate pre-room authoring assistant may suggest
editable unit text from host-provided reference material and the full current draft; that suggestion has no
semantic-artifact or persistence authority.

For correctness-sensitive units, a contradiction or material error does not count. For open-ended units, a relevant
position or objection may count without being the only acceptable conclusion. Every accepted unit is equally required by
the current optimizer; optional details should not be encoded as required units.

A response family describes the central answer: a primary method, position, recommendation, causal weighting, or
algorithmic strategy. It is independent of correctness and completeness. Answers with the same central answer stay
together when they differ only in supporting evidence, rationale, safeguards, caveats, or detail; those distinctions
belong in coverage. Answers split when their conclusion, recommended default, causal weighting, or defining method
differs. A relevant fragment that never supplies a central answer may remain null-family while still covering units. The
only coverage relation is between one participant's answer and the approved units for that question:

- same-family answers may cover different units;
- different-family answers may cover identical units;
- a null-family answer may still cover units;
- family membership never grants a covered unit.

## Per-question semantic calls

Each question with at least one non-empty answer runs two independent operations. The calls may run concurrently, while
one process-wide limiter bounds provider requests across questions and compiler instances.

### Coverage classification

Input:

```text
question prompt
relevant question and room reference text, when present
approved coverage units with opaque IDs
opaque participant IDs and non-empty answers
```

Output schema:

```json
{
  "assignments": [
    {
      "participantId": "opaque-id",
      "coveredUnitIds": ["u1", "u2"],
      "evidence": [{ "unitId": "u1", "quotes": ["Let dp[i] be the minimum cost through position i."] }]
    }
  ]
}
```

For every assignment:

- the participant ID must be supplied and appear exactly once;
- unit IDs must belong to the current question and contain no duplicates;
- the evidence-unit set must exactly equal `coveredUnitIds`;
- each covered unit has one evidence object with one or two quotes;
- every quote is at most 240 characters and is a literal substring of that participant's answer after line-ending
  normalization only;
- a keyword, incidental mention, contradiction, or correctness-sensitive error does not establish coverage.

Evidence makes a judgment auditable during validation. It is not persisted, logged, or returned to the browser. A
literal match proves location, not semantic support; human-reviewed fixtures remain the quality gate.

### Family clustering

Input:

```text
question prompt
opaque participant IDs and non-empty answers
```

Reference material, coverage units, coverage classifications, and evidence are deliberately excluded.

Output schema:

```json
{
  "families": [{ "label": "Top-down memoization" }, { "label": "Bottom-up tabulation" }],
  "assignments": [
    { "participantId": "opaque-id-1", "familyIndex": 0 },
    { "participantId": "opaque-id-2", "familyIndex": null }
  ]
}
```

Families must have unique, non-empty labels, every declared family must be used, and each assignment index must be null
or in range. An unclear, fragmentary, or non-substantive answer may be null-family. When every assignment is null, the
family array is empty. Family objects deliberately do not contain coverage units: coverage belongs to individual
answers, not to a cluster. The model never invents persistent family IDs; the compiler deterministically derives them
from question ID and label after validation.

### Excluded data

Neither semantic call receives display names, session values, join codes, room ownership, group-size bounds, selected
policy, tentative groups, or another branch's private inputs. Prompts serialize user content as escaped JSON inside
explicit data sections and instruct the model not to follow embedded instructions.

All-empty questions make no provider calls. The compiler locally creates null-family, empty-coverage assignments for
every frozen participant.

## Validation, retry, and repair

Pydantic first enforces strict schemas with unknown fields forbidden. Domain validation then enforces exact participant
sets, known units, evidence integrity, family indices, label uniqueness, and used families independently for each
branch.

After both results pass, the compiler merges by `participantId`, never array position. It adds local empty assignments
for unanswered participant-question pairs, orders units according to the host-approved list, and emits canonical family
IDs. Every question artifact must contain the same frozen participant set.

Each branch has two bounded recovery mechanisms:

1. one transport retry total for timeout, rate limit, server error, or incomplete response;
2. one stateless repair request after schema or domain failure.

The transport allowance is shared by the initial and repair phases, so a branch makes at most three HTTP requests.
Repair includes the original delimited input, sanitized validation errors, invalid structured result, and required
schema; it revalidates from scratch. A second invalid result fails the room.

Provider refusal, permanent error, repeated transient failure, semantic input overflow, room timeout, and invalid output
map to distinct internal outcomes and sanitized host messages. If either branch fails, no partial question or semantic
artifact is stored.

Input limits are checked before provider calls, including a conservative UTF-8 byte limit over messages and schema.
Repair requests receive the same preflight check. Logs may contain branch, model identifier, request ID, bounded timing,
token counts, and validation outcome; they exclude prompts, answers, reference text, evidence, names, and raw provider
output.

## Stored semantic artifact

Only the compact, validated relation is stored:

```json
{
  "schemaVersion": "1",
  "compiledAt": "2026-07-19T10:30:00Z",
  "model": "configured-model-id",
  "questions": [
    {
      "questionId": "question-uuid",
      "unitIds": ["u1", "u2"],
      "families": [{ "id": "f_canonical", "label": "Top-down memoization" }],
      "assignments": [{ "participantId": "participant-uuid", "familyId": "f_canonical", "coveredUnitIds": ["u1"] }]
    }
  ]
}
```

The artifact is strict, immutable, versioned, prose-free except for bounded family labels, and complete for the frozen
cohort. It contains no answer text or evidence quotes.

## Capacity selection

For participant count `n` and bounds `min`, `preferred`, `max`, feasible group counts satisfy:

```text
ceil(n / max) <= groupCount <= floor(n / min)
```

Among feasible counts, Junto minimizes the distance between average group size and `preferred`, breaking ties toward the
larger group count. It then fixes balanced capacities using only `floor(n/groupCount)` and `ceil(n/groupCount)`.
Capacity is never left for a semantic objective to distort.

Before CP-SAT starts, stable participant order is placed into those capacities as a last-resort valid partition.

## CP-SAT model

The core binary relations are:

```text
x[s,g]          participant s belongs to group g
covered[g,q,u]  group g has at least one carrier for unit u on question q
full[g,q]       every approved unit for q is covered in g
family[g,q,f]   group g contains family f on question q
```

Hard constraints place every participant in exactly one group, fill every predetermined capacity, and make
coverage/family presence the logical OR of individual validated assignments. A family variable never influences a
coverage variable.

Questions with more units must not dominate. Junto scales each question's covered-unit count to a shared integer maximum
using the least common multiple of non-zero unit counts.

## Complete-coverage feasibility and fallback

Up to one third of the global solve time limit tests the exact constraint that every group covers every unit on every
question.

- `feasible`: a solver witness establishes complete coverage; it becomes a hard constraint for later objectives.
- `infeasible`: CP-SAT proves the exact complete-coverage model impossible.
- `unknown`: no proof within the feasibility time limit.

A later fallback solution that happens to cover everything is itself a feasibility witness. Timeout or `UNKNOWN` is
never described as infeasible.

When complete coverage is not fixed, objectives run lexicographically:

1. maximize the worst normalized group-question coverage;
2. maximize the minimum fully covered question count in any group;
3. maximize total fully covered group-question pairs;
4. maximize total normalized coverage.

An objective advances only after its achieved value is proven optimal and fixed. If CP-SAT returns a valid but
non-optimal assignment, Junto keeps it, reports `feasible`, and stops lower-priority optimization. If no solver
assignment is available, it returns the deterministic capacity partition with solver status `fallback` and
complete-coverage status `unknown`.

## Policy objectives

Policy objectives run only after the achieved coverage priorities are fixed.

### Teach Each Other

Solver-only representative variables select one eligible carrier for every available group-question-unit. They are not
persisted and do not appoint speakers in the UI; published agendas show every eligible carrier.

The policy then:

1. maximizes the minimum active contributor count across groups;
2. minimizes the largest representative-unit load on one person;
3. maximizes total active contributors;
4. maximizes family variety as a final tie-break.

This distributes overall contribution opportunity while coverage remains the hard priority.

### Explore Different Approaches

For each group-question pair, the model counts represented non-null families and marks whether at least two appear. It
then:

1. maximizes the minimum number of diverse questions across groups;
2. maximizes total diverse group-question pairs;
3. maximizes normalized additional-family coverage.

Pairs with fewer than two available families receive no diversity value. Family variety cannot compensate for missing a
fixed coverage objective.

## Determinism and truth labels

The optimizer uses stable participant/question ordering, one search worker, a fixed seed, equal-capacity symmetry
breaking, a deterministic initial hint, a single global time limit, and canonical group IDs `g1`, `g2`, and so on.

The stored grouping artifact is:

```json
{
  "schemaVersion": "1",
  "generationMode": "coverage_aware",
  "policy": "teach",
  "trigger": "all_submitted",
  "generatedAt": "2026-07-19T10:31:00Z",
  "groups": [{ "id": "g1", "participantIds": ["participant-uuid"] }],
  "solverStatus": "optimal",
  "completeCoverageStatus": "feasible",
  "timedOut": false,
  "solveMilliseconds": 38,
  "objectives": [{ "name": "coverage.total_full_pairs", "value": 4, "provenOptimal": true }]
}
```

`solverStatus` is `optimal`, `feasible`, or `fallback`. Only an objective whose `provenOptimal` is true is described as
proven best. Host and participant diagnostics are derived at read time from this partition plus the semantic artifact;
missing units, carriers, represented families, and coverage counts are not duplicated in storage.

## Verification and quality boundary

Automated semantic tests cover four reviewed subjects (programming, philosophy, history, and design), exact fixture
remapping, branch independence, all-empty questions, strict IDs, evidence matching, bounded repair/retry,
prompt-delimiter safety, request-size preflight, privacy-safe errors/logs, adapter parameters, provider outcomes, and
process-wide concurrency.

Optimizer tests cover capacity selection, exactly-once membership, known-feasible and proven-infeasible fixtures,
unknown/fallback truth labels, a brute-force coverage oracle, policy separation, lexicographic preservation, missing
answers, null families, deterministic serialization, and randomized supported-size invariants.

Recorded fixtures prove the implementation contract without network access. They do not measure a live model. Live model
readiness requires the adjudicated metrics and human evidence review in [evaluation.md](evaluation.md); no live
evaluation can be claimed without an API key and recorded report.
