# Semantic evaluation

Junto evaluates coverage classification and response-family clustering against ten reviewed synthetic fixtures across
biology, design, history, literature, machine learning, media literacy, philosophy, programming, and statistics.
Lifecycle rehearsal creates one activity per fixture; it never combines their context or answers into one room. The
evaluator emits only fixture IDs, subject labels, counts, scores, latency, token usage, and sanitized error codes. It
does not emit questions, reference material, answers, coverage-unit text, or evidence quotes.

## Test suites and claims

Keep these suites separate so a convenient generated answer cannot become its own answer key:

- **Gold:** separately reviewed semantic fixtures establish coverage and family accuracy only against frozen labels.
- **Reviewed lifecycle:** the same fixtures drive separate deterministic activities through room creation, simulated
  identities, submission, analysis, optimization, and publication. This proves orchestration, not live generalization.
- **Challenge:** 12 independent one-question activity specs assign adversarial variants to 20 varied personas; they test
  diverse, empty, hostile, and long inputs but do not establish semantic accuracy.
- **Scale:** deterministic 5-, 10-, and 20-person payloads test identity, source, and tag preservation and record
  assembled payload sizes; they do not run provider or compiler preflight or establish whether answers are correct.

Never generate an answer and a label with the same model, score one against the other, and call that accuracy. A new
accuracy fixture enters the gold suite only after independent review records the expected coverage relations, family
relations, and evidence judgments.

## Run it

From `backend/`, run the deterministic contract evaluation:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_semantic.py --mode recorded
```

Recorded mode uses the adjudicated outputs already stored in the fixture files. It proves that schemas, validation,
merging, scoring, and reporting work without a network. Its perfect scores are not evidence that a language model makes
correct judgments.

For a manual OpenAI evaluation, supply a key and pin the model explicitly:

```powershell
$env:OPENAI_API_KEY = "..."
.\.venv\Scripts\python.exe scripts\evaluate_semantic.py --mode live `
  --live-provider openai --model gpt-5.6-luna --reasoning-effort high `
  --output output\semantic-live.json
```

For a manual OpenRouter evaluation:

```powershell
$env:OPENROUTER_API_KEY = "..."
.\.venv\Scripts\python.exe scripts\evaluate_semantic.py --mode live `
  --live-provider openrouter --model google/gemini-2.5-flash `
  --output output\semantic-openrouter-live.json
```

Repeat `--fixture PATH` to run selected files once each in sorted path order. Use the mutually exclusive
`--fixtures DIRECTORY` option to discover every JSON fixture in one directory.

For OpenAI evaluator runs, `--max-output-tokens` explicitly caps each structured response and defaults to 20,000 so a
manual investigation can opt into more headroom. The application default is 8,000 per response. For either live
provider, `--max-total-tokens` sets the evaluator's aggregate usage gate and defaults to 250,000. Token totals include
every coverage batch, repair, retry that returned usage, and the cohort-wide family call.

Live mode deterministically shuffles participants and replaces question, participant, and coverage-unit identifiers with
opaque values before a provider call. `--seed` controls this blinding and defaults to `41`; the report records the seed
but never the private identifier map or raw fixture text. Recorded mode bypasses blinding so it remains an exact fixture
contract test. CI must use recorded mode; live runs are manual because results may change with a model revision.
Provider and model selection are explicit CLI arguments; only the provider secret is read from the environment.

## Offline structural stress

Run the deterministic challenge and scale suites from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_synthetic_stress.py
```

To save a fresh machine-readable report:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_synthetic_stress.py `
  --output ..\output\synthetic-stress-offline.json
```

The command constructs no provider client and makes zero network calls. It checks 12 subjects and question types,
assigns 240 challenge responses from 49 source variants to 20 identities, and covers negation, plausible errors,
semantic paraphrases, fragments, Spanish and Arabic text, prompt injection, empty and duplicate responses, and long
answers. Each scenario has its own activity title, prompt, and four or five coverage units; an API test materializes
each as a separate draft room.

The scale matrix checks 365 answer slots across 5-by-1, 10-by-4, and two 20-by-8 classroom payloads. Its largest
assembled stress payload is 58,456 UTF-8 bytes. This is an offline serialization measurement, not a compiler or provider
request.

An offline pass means the corpus is diverse and structurally within tested limits. It reports
`semanticAccuracyClaim: "none"` by design. Use the gold evaluator for accuracy metrics and keep generated reports in the
ignored `output/` directory rather than committing them.

## Automated gates

- **Schema and domain success — 1.00:** every fixture compiles after at most one repair per coverage batch and family
  call.
- **Assignment completeness — 1.00:** every frozen participant appears exactly once.
- **Evidence literal integrity — 1.00:** every quote occurs in its answer and matches a covered unit.
- **Family-unit matrix integrity — 1.00:** reviewed relationship cases retain their intended results.
- **Unit-coverage precision — at least 0.90:** predicted participant-unit relations match adjudicated relations.
- **Unit-coverage recall — at least 0.80:** adjudicated participant-unit relations recovered by the compiler.
- **Pairwise family F1 — at least 0.80:** agreement on whether each participant pair belongs to the same non-null
  family.
- **Latency within limit — 1.00:** every fixture finishes within `--max-fixture-latency-ms`, which defaults to 180,000
  milliseconds.
- **Token usage within limit — pass:** live calls report usage and stay within `--max-total-tokens`.

First-pass validity, repair calls, and the input/output/reasoning breakdown remain diagnostic. Change latency or token
limits deliberately for the pinned model and expected classroom size; do not loosen semantic-quality gates to make a run
pass.

## Report contract

The JSON report contains:

- `mode`, `provider`, `model`, `generatedAt`, `fixtureCount`, and the live-only `blindSeed`;
- one fixture record with structural booleans, confusion counts, privacy-safe mismatch IDs, relationship checks,
  sanitized error code, and wall-clock latency;
- aggregate coverage precision/recall, family F1, structural rates, repair count, latency percentiles, and provider
  token usage;
- one threshold and pass/fail result per automated gate;
- `overallStatus`, which is `pass` only when every automated gate passes.

A recorded pass means the deterministic contract is intact. A live automated pass means the model met the
machine-checkable fixture gates for that run. Neither establishes that grouping improves learning.

## Required human review

Literal evidence matching proves that a quote exists; it does not prove that the quote genuinely supports the unit.
Before a model is declared demo-ready, a reviewer must inspect live evidence without seeing participant names and record
evidence-support precision. The initial gate is 0.90, as defined in [engine.md](engine.md). Ambiguous examples must be
adjudicated rather than counted in the model's favor. Record the model ID, date, fixture revision, disagreements, and
reviewer decision alongside the generated JSON report.

## Evidence discipline

Generated live reports are dated run artifacts, not permanent claims about the product or model. A report becomes
release evidence only when its inputs and model are pinned, all automated gates pass, and the required human review is
recorded beside it. Transport failures, malformed structured output, partial batches, and unreviewed generated labels
are failed or incomplete evidence, never successful fixtures.

OpenRouter-generated students may feed challenge or scale runs, but not the gold suite until a person adjudicates them.
Keep model IDs server-owned and pinned, deny provider data collection, require structured-output-capable routes, and
trigger generation only through an explicit host action. Never start generation from page load or polling, and never
save a partial synthetic cohort after a failed student request. A live generalization run may compare generated answers
with the reviewed expectations afterward, but the generator never receives coverage units, expected labels, or family
assignments, and its answers do not become gold automatically.
