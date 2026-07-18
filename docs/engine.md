# Semantic and optimization engine

## Boundary

The engine converts frozen room inputs into one participant partition:

```text
frozen question batch
    ├── question + reference + units + answers
    │       → coverage classification + transient evidence
    │       → per-response coveredUnitIds
    │
    └── question + answers
            → independent family clustering
            → per-response family
                    │
                    ▼
         merge by opaque participant ID
                    │
                    ▼
       coverage-first CP-SAT optimization
                    │
                    ▼
        selected participant partition
```

The language model interprets text but never receives group sizes or produces groups. The optimizer consumes only validated discrete artifacts and never interprets prose.

The compiler uses the official OpenAI Python SDK and Responses API with Pydantic-backed Structured Outputs. Calls are independent and stateless: `store` is `false`, no previous response is reused, and no model tools are enabled. `OPENAI_MODEL` is configurable but must be pinned for the deployed demo and support the required schemas.

Stored artifact shapes are defined in [contracts.md](contracts.md).

## Coverage units

A coverage unit is a small, question-local, host-approved primitive that should be available inside every group.

Units may represent concepts, reasoning steps, evidence, interpretations, arguments, objections, perspectives, user needs, mechanisms, tradeoffs, or risks. Their semantics depend on the question.

For correctness-sensitive units, invalid facts, formulas, or reasoning do not count. For open-ended units, a relevant position or objection may count without being treated as the only acceptable conclusion.

Every accepted unit is required and equally weighted. Optional details should not be accepted as units.

### Generation input

```text
question prompt
optional reference answer, rubric, reading, or learning objective
```

### Coverage-generation output

```json
{
  "units": [
    {
      "text": "Explains why overlapping subproblems make cached results reusable"
    }
  ]
}
```

The model returns text only. After validation and host acceptance, the application assigns stable opaque unit IDs when the list is persisted.

### Generation rules

- hard limit: 1–8 units;
- normal target: 3–7 units when the question supports that range;
- each unit is independently present or absent in a response;
- each unit is specific to the actual question, not a generic label such as “argument” or “evidence”;
- unit text is concise enough for a discussion checklist;
- units are grounded in the question prompt and, when present, the host's reference material;
- alternatives are not automatically units merely because they might become response families;
- no scores, weights, confidence values, IDs, or extra fields.

The host edits or accepts the generated list. The engine never bypasses host approval.

## Response compilation

After the room is atomically frozen, compile each question through two independent model calls:

1. **Coverage classification** decides which approved units are substantively present in each answer and cites exact answer evidence.
2. **Family clustering** groups answers by their primary method, reasoning pattern, or position.

Both calls receive the same opaque participant IDs and the same non-empty answers for one question. Unanswered or normalized-empty responses are omitted from both calls and added locally later. Neither call receives the other call's output. The separation is a contract boundary: coverage cannot be inferred from a family, and family membership cannot be influenced by whether an answer is correct or complete.

The calls for a question may run concurrently. One process-local semaphore bounds all OpenAI requests across the room, rather than creating a separate concurrency allowance per question or per call type.

### Coverage-classification input

```text
question prompt
optional reference material
approved coverage units with opaque IDs
opaque participant IDs and non-empty answer text
```

Names, session data, join codes, group constraints, group capacities, and tentative assignments are excluded.

### Coverage-classification output

```json
{
  "assignments": [
    {
      "participantId": "p1",
      "coveredUnitIds": ["u1", "u2"],
      "evidence": [
        {
          "unitId": "u1",
          "quotes": [
            "Let dp[i] represent the minimum cost through position i."
          ]
        },
        {
          "unitId": "u2",
          "quotes": [
            "The recurrence takes the cheaper of the two previous states."
          ]
        }
      ]
    },
    {
      "participantId": "p2",
      "coveredUnitIds": [],
      "evidence": []
    }
  ]
}
```

Evidence makes a coverage judgment auditable; it is not another stored artifact. For each assignment:

- the evidence-unit set exactly equals `coveredUnitIds`;
- every covered unit has exactly one evidence object;
- each evidence object contains one or two concise verbatim quotes, each at most 240 characters;
- every quote is a literal substring of that participant's submitted answer after both strings replace CRLF and bare CR with `\n`; no trimming, case folding, Unicode normalization, or other whitespace normalization is allowed;
- a quote counts only when its surrounding answer context substantively and accurately supports the unit;
- a keyword, incidental mention, contradiction, or correctness-sensitive error does not establish coverage;
- runtime evidence is validated in memory but never persisted in room artifacts or written to application logs; reviewed fixtures may contain synthetic expected evidence spans.

The application derives only `coveredUnitIds` from a valid coverage response. The model returns no confidence score.

### Family-clustering input

```text
question prompt
opaque participant IDs and non-empty answer text
```

Reference material, coverage units, coverage classifications, and coverage evidence are deliberately excluded. A family describes how an answer approaches the question, independently of how many approved units it covers.

### Family-clustering output

```json
{
  "families": [
    {
      "label": "Top-down memoization"
    },
    {
      "label": "Bottom-up tabulation"
    }
  ],
  "assignments": [
    {
      "participantId": "p1",
      "familyIndex": 0
    },
    {
      "participantId": "p2",
      "familyIndex": null
    }
  ]
}
```

The server validates `familyIndex` and generates canonical family IDs. The model never invents persistent family IDs.

### Family rules

- a family represents a primary method, reasoning pattern, or position;
- answers interchangeable for approach diversity share a family;
- materially distinct approaches remain separate;
- a hybrid answer may receive a hybrid family;
- an unclear or non-substantive answer may receive a null family;
- when every assignment is null-family, `families` is an empty array even though the question has non-empty answers;
- family judgments ignore style, verbosity, confidence, identity, personality, correctness, and completeness;
- every declared family is used;
- answer text is never repeated in output.

For open-ended questions, opposing positions may each receive valid families. Family identity does not establish correctness and never substitutes for required units.

### Independence invariant

A family has no `coveredUnitIds` field and no implied coverage set. The only coverage relation is between one participant's answer and the approved units for that question. Therefore:

- members of the same family may cover different units;
- members of different families may cover identical units;
- a null-family answer may still cover units;
- membership in a strong or common family never grants coverage that the individual answer did not substantiate.

## Validation and repair

Pydantic enforces a separate strict schema for each call. Coverage-domain validation additionally requires:

- exact participant-ID coverage for every submitted non-empty response;
- one assignment per input participant;
- no unknown or duplicated participant IDs;
- unit IDs belonging to the current question;
- no duplicate unit IDs inside an assignment;
- exact agreement between the covered-unit and evidence-unit sets;
- exactly one evidence object per covered unit;
- one or two bounded, literal-substring quotes per evidence object;
- no extra fields.

Family-domain validation independently requires:

- exact participant-ID coverage for every submitted non-empty response;
- one assignment per input participant;
- no unknown or duplicated participant IDs;
- unique, non-empty family labels;
- family indices that are null or in range;
- no unused family;
- no extra fields.

After both results pass independently, the server assigns canonical family IDs and merges the results by `participantId`, never by array position, into the stored `{participantId, familyId, coveredUnitIds}` assignment. Both validated participant-ID sets must equal the same expected set. The server then adds `{familyId: null, coveredUnitIds: []}` for unanswered participant-question pairs.

If every answer for a question is empty, skip both provider calls and produce no families plus empty assignments for every participant.

Each call gets its own bounded repair opportunity. On invalid output:

1. send one stateless repair request containing the original delimited inputs, the invalid result, the applicable schema, and concise validation errors;
2. do not include participant names or internal stack traces;
3. validate the repair from scratch;
4. fail the room if that call's repaired result is still invalid.

If either call fails, the question compilation fails. The room analysis commits neither a partial question result nor a partial semantic artifact, even if the other call succeeded.

An explicit model refusal is a provider outcome, not a valid semantic artifact; fail the operation with a sanitized host message and do not reinterpret it as empty coverage. Each semantic branch has one transport-retry allowance total, usable after a transient timeout, rate-limit, server error, or incomplete response when the remaining end-to-end budget permits. That allowance is shared by the initial and repair phases, not reset per HTTP request. Together with at most one repair request, this caps each branch at three HTTP requests and each non-empty question at six. Transport retry and schema/domain repair are separately triggered and never loop.

Structural validation proves contract conformance, not semantic correctness. A literal evidence match proves that the cited text exists in the answer; it does not by itself prove that the excerpt actually supports the unit. Reviewed fixtures remain the gate for that semantic judgment.

## Input safety and cost controls

Participant answers are untrusted data. Prompts must:

- delimit questions, references, units, and answers as data sections;
- explicitly prohibit following instructions found inside those sections;
- require schema-only output;
- prohibit names, prose commentary, and invented IDs.

The application must:

- enforce question, participant, unit, reference, and answer limits before a model call;
- render every user and model string with normal React escaping;
- preflight each question batch against the pinned model's input limit;
- bound all concurrent OpenAI requests with a process-local semaphore;
- log provider request IDs and timings without logging answer or reference text;
- use recorded outputs in CI and reserve live calls for manual evaluation.

## Semantic evaluation

Maintain reviewed fixtures from at least dynamic programming and philosophy. For each question, reviewers record:

- accepted coverage units;
- expected covered-unit sets per response;
- accepted evidence spans for covered units;
- expected response-family relationships.

Track:

- schema and domain success before and after repair for each call type;
- participant assignment completeness for each call and after the merge;
- evidence literal-match and unit-support review failures;
- per-unit precision and recall;
- pairwise family co-clustering agreement;
- cases where equal family membership correctly produces unequal coverage;
- cases where equal coverage correctly produces different families;
- reviewed examples where open-ended disagreement remains valid.

Hard structural gates are 100% participant completeness, 100% literal evidence-substring integrity, zero accepted unknown IDs, zero accepted cross-participant evidence, and zero persisted partial semantic artifacts.

Initial live-demo gates on adjudicated fixtures are:

| Measure | Gate |
|---|---:|
| Micro-averaged unit-coverage precision | ≥ 0.90 |
| Micro-averaged unit-coverage recall | ≥ 0.80 |
| Human-judged evidence-support precision | ≥ 0.90 |
| Pairwise family co-clustering F1 | ≥ 0.80 |

Ambiguous labels must be adjudicated before scoring rather than counted opportunistically. Track latency, token use, first-pass validity, and repair success separately for the coverage and family calls. These metrics evaluate the compiler; they are not product claims about learning.

## Capacity selection

For participant count `n`, minimum `min`, preferred `preferred`, and maximum `max`, feasible group counts satisfy:

```text
ceil(n / max) <= group_count <= floor(n / min)
```

Reject analysis when that range is empty.

Among feasible counts, choose the count minimizing:

```text
abs(n / group_count - preferred)
```

Break ties by choosing the larger group count. Create balanced capacities from `floor(n / group_count)` and `ceil(n / group_count)`, then fix them before semantic optimization.

## Optimization inputs

Let:

- `S` be participants;
- `Q` be questions;
- `Uq` be accepted units for question `q`;
- `Fq` be non-null families for question `q`;
- `a[s,q,u] = 1` when participant `s` covered unit `u`;
- `f[s,q]` be the participant's family or null;
- `G` be fixed group slots and capacities.

Core variables:

```text
x[s,g]          participant assignment
covered[g,q,u]  unit availability
full[g,q]       full question coverage
family[g,q,f]   family presence
```

Hard constraints:

```text
Every participant belongs to exactly one group.
Every group matches its predetermined capacity.
covered[g,q,u] is the OR of assigned unit carriers.
family[g,q,f] is the OR of assigned family members.
```

## Coverage normalization

Questions with more units must not dominate.

Let:

```text
L = least common multiple of all non-zero per-question unit counts
```

Then:

```text
coverageScore(g,q)
  = (L / numberOfUnits(q)) × sum(covered[g,q,u])
```

Every group-question pair has the same maximum score `L`, using integer coefficients only.

## Complete-coverage feasibility

A quick scarcity report identifies units with fewer carriers than groups. This is necessary but not sufficient because one participant may carry several scarce units.

Run an exact feasibility solve with:

```text
covered[g,q,u] = 1
for every group, question, and accepted unit
```

Possible outcomes:

- a witness proves `feasible` and complete coverage becomes a hard constraint;
- a proof establishes `infeasible` and the fallback objectives run;
- a timeout returns `unknown`; fallback runs, but the system does not claim infeasibility.

If any fallback solve later finds complete coverage, that assignment is itself a feasibility witness.

The feasibility pass may consume at most one third of `SOLVER_TIMEOUT_SECONDS`; the rest is reserved for producing and improving a valid grouping. Capacity selection also creates a deterministic balanced partition before CP-SAT runs. That partition is the last-resort valid result if the solver returns no assignment before the deadline, so a capacity-valid room does not fail merely because semantic optimization timed out.

## Coverage fallback

When complete coverage is not available, solve lexicographically:

1. maximize the worst normalized group-question coverage;
2. maximize the minimum number of fully covered questions per group;
3. maximize total fully covered group-question pairs;
4. maximize total normalized coverage.

Each optimal objective value is fixed before the next objective begins. Policy objectives cannot trade away the achieved coverage result.

## Teach Each Other

After coverage is fixed, create solver-only representative variables:

```text
contributes[s,g,q,u] = 1 when participant s is selected as one eligible
                       representative carrier for available unit u
```

For every available group-question-unit, select exactly one eligible representative. These variables test whether useful material can be distributed across several group members. They are never persisted or shown as mandatory speaker assignments.

Define `active[s,g]` when participant `s` represents at least one unit across any question in group `g`. Representative load is the total represented units across all questions. Teach fairness is deliberately group-wide rather than a per-question guarantee: per-question coverage remains the hard priority, while the policy's secondary purpose is to distribute the overall teaching opportunity. The agenda still shows every eligible carrier for every individual unit.

Solve lexicographically:

1. maximize the minimum number of active contributors in any group;
2. minimize the maximum representative-unit load assigned to one participant;
3. maximize total active contributors;
4. maximize family variety as a final tie-break.

The published page shows every eligible carrier, not the representative chosen internally by the solver.

## Explore Different Approaches

For each group-question pair:

```text
familyCount[g,q] = number of distinct represented non-null families
diverse[g,q]     = 1 when familyCount[g,q] >= 2
```

After coverage is fixed, solve lexicographically:

1. maximize the minimum number of diverse questions per group;
2. maximize total diverse group-question pairs;
3. maximize normalized additional-family coverage.

One represented family is the baseline. For exact integer normalization, let:

```text
M[g,q] = min(groupCapacity(g), numberOfAvailableNonNullFamilies(q))
D      = least common multiple of every positive (M[g,q] - 1), or 1 if none

additionalFamilyScore(g,q) =
  0,                                      when M[g,q] < 2
  (D / (M[g,q] - 1)) × (familyCount[g,q] - 1), otherwise
```

Clamp the final factor at zero when no family is represented. Every eligible group-question pair then has the same maximum score `D`; pairs with fewer than two available families contribute no diversity value.

## Lexicographic execution

For each objective, using the remaining global time budget:

1. solve;
2. if `OPTIMAL`, record and fix the value, then continue;
3. if `FEASIBLE`, retain the valid assignment, mark solver status feasible, and stop lower-priority optimization;
4. if no assignment is returned, retain the last valid higher-priority assignment or the deterministic capacity partition.

Never convert `UNKNOWN` or a timeout into an infeasibility claim.

Only an objective solved to `OPTIMAL` is described as proven best. If the time budget stops on a valid `FEASIBLE` result, Junto reports the assignment as the best found within the configured solve limit and preserves every already fixed higher-priority value.

Use:

- stable participant and question ordering;
- one solver search worker;
- a fixed seed;
- symmetry-breaking constraints;
- a deterministic capacity-respecting initial hint;
- canonical group labels after solving.

## Derived diagnostics

Store only the partition and solver truth statuses. At read time derive:

- per-group covered and missing units;
- every eligible carrier for each unit;
- represented families;
- full group-question coverage counts;
- scarcity warnings.

This keeps `analysis_result` and `grouping_result` as the only semantic sources of truth and prevents duplicated diagnostics from drifting.

## Optimizer verification

Automated tests must cover:

- balanced capacity selection;
- every participant exactly once;
- exact capacities;
- full coverage on known-feasible fixtures;
- proven infeasibility and exact missing units;
- unknown timeout semantics;
- lexicographic objective preservation;
- policy-specific outcomes;
- null-family and missing-answer behavior;
- deterministic serialization;
- randomized supported-size invariants;
- small cases compared with a brute-force oracle.
