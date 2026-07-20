# Semantic evaluation

Junto evaluates coverage classification and response-family clustering against four reviewed synthetic fixtures:
programming, philosophy, history, and design. The evaluator emits only fixture IDs, subject labels, counts, scores,
latency, token usage, and sanitized error codes. It does not emit questions, reference material, answers, coverage-unit
text, or evidence quotes.

## Test suites and claims

Keep these suites separate so a convenient generated answer cannot become its own answer key:

- **Gold:** separately reviewed semantic fixtures establish coverage and family accuracy only against frozen labels.
- **Challenge:** adversarial templates assigned to 20 varied personas test diverse, empty, hostile, and long inputs;
  they do not establish semantic accuracy.
- **Scale:** deterministic 5-, 10-, and 20-person payloads test identifier integrity, supported question counts, and
  input-size headroom; they do not establish whether answers are correct.

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
  --live-provider openai --model gpt-5.6-sol `
  --output output\semantic-live.json
```

For a manual OpenRouter evaluation:

```powershell
$env:OPENROUTER_API_KEY = "..."
.\.venv\Scripts\python.exe scripts\evaluate_semantic.py --mode live `
  --live-provider openrouter --model a-reviewed-pinned-model-id `
  --output output\semantic-openrouter-live.json
```

Live mode never prints the API key or raw fixture text. CI must use recorded mode; live runs are manual because results
may change with a model revision. Provider and model selection are explicit CLI arguments; only the provider secret is
read from the environment.

## Offline structural stress

Run the deterministic challenge and scale suites from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_synthetic_stress.py
```

To save a fresh machine-readable report:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_synthetic_stress.py `
  --output ..\docs\evidence\synthetic-stress-offline.json
```

The command constructs no provider client and makes zero network calls. It checks 12 subjects and question types,
assigns 240 challenge responses to 20 identities, and covers negation, plausible errors, semantic paraphrases,
fragments, Spanish and Arabic text, prompt injection, empty and duplicate responses, and long answers.

The scale matrix checks 365 answer slots across 5-by-1, 10-by-4, and two 20-by-8 classroom payloads. Its largest current
serialized input is 42,556 UTF-8 bytes against the compiler's 240,000-byte preflight ceiling. The reviewed baseline is
the committed [offline report](evidence/synthetic-stress-offline.json).

An offline pass means the corpus is diverse and structurally within tested limits. It reports
`semanticAccuracyClaim: "none"` by design. Use the gold evaluator for accuracy metrics and preserve live outputs as
dated evidence rather than replacing fixture labels.

## Automated gates

- **Schema and domain success — 1.00:** every fixture compiles after at most one bounded repair per branch.
- **Assignment completeness — 1.00:** every frozen participant appears exactly once.
- **Evidence literal integrity — 1.00:** every quote occurs in its answer and matches a covered unit.
- **Family-unit matrix integrity — 1.00:** reviewed relationship cases retain their intended results.
- **Unit-coverage precision — at least 0.90:** predicted participant-unit relations match adjudicated relations.
- **Unit-coverage recall — at least 0.80:** adjudicated participant-unit relations recovered by the compiler.
- **Pairwise family F1 — at least 0.80:** agreement on whether each participant pair belongs to the same non-null
  family.
- **Latency within limit — 1.00:** every fixture finishes within `--max-fixture-latency-ms`, which defaults to 180,000
  milliseconds.
- **Token usage within limit — pass:** live calls report usage and stay within the configured limit.

First-pass validity, repair calls, and the input/output/reasoning breakdown remain diagnostic. Change latency or token
limits deliberately for the pinned model and expected classroom size; do not loosen semantic-quality gates to make a run
pass.

## Report contract

The JSON report contains:

- `mode`, `provider`, `model`, `generatedAt`, and `fixtureCount`;
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
save a partial synthetic cohort after a failed batch.
