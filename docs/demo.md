# Demonstration guide

## What the demo proves

The demonstration proves one bounded workflow: independent answers can be compiled into subject-neutral coverage
assignments and response families, then partitioned into capacity-valid groups that receive the strongest feasible
coverage before a policy preference is considered.

It does not prove that the model is always correct, that every group can receive impossible coverage, that Junto grades
students, or that the grouping improves learning. Learning impact needs a separate comparison and outcome measure.

## Choose the evidence mode

Use two runs during rehearsal:

1. **Recorded provider fixture:** deterministic, offline, and suitable for the end-to-end gate. It proves orchestration,
   validation, optimization, persistence, and role projections without pretending to be a live semantic evaluation.
2. **Live provider review:** a separately labelled run using the configured OpenAI model. Review its coverage
   disagreements for the chosen fixture activity. Never silently substitute the recorded artifact for a live call.

The event demo should prefer the reviewed live run when the provider is healthy and use the recorded run as an
explicitly named fallback.

## Preflight

Complete the [operations release checklist](operations.md#release-checklist), then verify:

- one fresh host browser and one fresh participant browser have no prior Junto cookies;
- the join disclosure appears before the participant enters a name;
- the presenter knows how to delete the room after the demonstration;
- the model attempt limits and solver timeout are fixed;
- the reviewed fixture completes within the configured analysis timeout;
- the host can explain missing coverage and model uncertainty without calling either a grade;
- the fallback screen and restart/provider-failure drills have been seen by the presenters.

Avoid spending demo time on accounts, WebSockets, database internals, or infrastructure diagrams. The product is the
transition from individual answers to a useful discussion agenda.

## Reviewed activities

Each reviewed fixture is one independent, one-question activity. Keeping subjects in separate rooms prevents context
leakage and makes a failed classification attributable to one prompt and answer set.

- [Programming](../backend/tests/fixtures/semantic/programming_dynamic_programming.json): objective reasoning steps.
- [Philosophy](../backend/tests/fixtures/semantic/philosophy_ai_proctoring.json): defensible opposing positions.
- [History](../backend/tests/fixtures/semantic/history_western_rome.json): evidence and competing explanations.
- [Design](../backend/tests/fixtures/semantic/design_budgeting_onboarding.json): needs, approaches, and tradeoffs.
- [TRM architecture](../backend/tests/fixtures/semantic/machine_learning_trm_architecture.json): ablation evidence.
- [TRM latent](../backend/tests/fixtures/semantic/machine_learning_trm_latent_reasoning.json): claims and limits.
- [Biology](../backend/tests/fixtures/semantic/biology_antibiotic_resistance.json): selection and gene-transfer
  accounts.
- [Statistics](../backend/tests/fixtures/semantic/statistics_randomized_tutoring.json): qualified causal interpretation.
- [Literature](../backend/tests/fixtures/semantic/literature_ledger_interpretation.json): competing textual readings.
- [Media literacy](../backend/tests/fixtures/semantic/media_literacy_cooling_centers.json): source evaluation and
  claims.

Use Teach each other, group sizes 3/4/5, and 20 minutes. The linked JSON remains the source of truth for each prompt,
reference, coverage units, reviewed answers, and expected relations; this guide does not duplicate them.

## Two-presenter flow from fresh browsers

Presenter A owns the host browser. Presenter B owns a fresh participant browser and narrates the participant experience.

1. Presenter A chooses one reviewed fixture, opens `/create`, enters that prompt, reference, and coverage units, then
   creates the invite.
2. Presenter B opens `/join/{code}`, reads the data/model disclosure, enters a room-scoped name, and waits in the lobby.
3. On a loopback rehearsal deployment, load the remaining reviewed cohort through normal HTTP:

   ```powershell
   backend\.venv\Scripts\python.exe backend\scripts\load_demo.py --join-code INVITE_CODE --participants 11 `
     --fixture backend\tests\fixtures\semantic\programming_dynamic_programming.json
   ```

   The loader joins the lobby and waits. It does not touch the database or receive host access.

4. Presenter A shows the frozen roster and starts once. The shared deadline is server-owned.
5. The loader cycles the exact reviewed fixture responses. Presenter B answers the question, reviews, and submits. In
   recorded mode, Presenter B must use exact answer text from the linked fixture so the offline adapter can match it; in
   live mode they may answer naturally.
6. Presenter A ends collection only if the live participant has submitted. Explain the real stages without a fake
   percentage: coverage classification and family clustering are independent, then the optimizer uses the validated
   artifact.
7. On publication, Presenter B sees only their group and per-question agenda. Presenter A opens the room view and shows
   every group, achieved/missing coverage, represented families, capacity, and original-answer audit.
8. Point to one participant whose answer covers a required idea and a different response family. This demonstrates why
   family membership never grants coverage.
9. If coverage is missing, say so. The guarantee is strongest feasible coverage under capacity and the available
   answers, not universal full coverage.

The fixture loader requires a loopback URL and non-secure cookies, so it is for development and rehearsal only. A public
event deployment keeps secure cookies and uses real participant browsers.

## Full automated rehearsal

Use the commands and data boundary in
[Classroom fixture and load check](operations.md#classroom-fixture-and-load-check). The default suite creates one
20-person activity per reviewed fixture. Reviewed responses are deterministic; OpenRouter responses are unreviewed
generalization inputs and never become gold labels.

Success requires every room to publish, exactly-once membership, valid capacities, and internally consistent coverage
diagnostics; exact groups may differ. Run the 60-participant polling check separately and treat it as a demo-envelope
check, not a production load claim.

## Honest failure language

Use these distinctions on stage:

- **Provider unavailable or invalid output:** "Junto could not validate the answer analysis. No groups were released;
  the host can retry the frozen responses."
- **Full coverage infeasible:** "Every valid partition misses at least some requested coverage with these answers. This
  is the strongest feasible result found."
- **Solver time limit or unknown:** "Junto found a valid result within the solve limit but has not proven it is the best
  possible result."
- **Interrupted analysis:** "The attempt was interrupted and published nothing. The saved response snapshot can be
  retried."

Never call a timeout "optimal," convert missing coverage into family coverage, expose another participant's raw answer
to a participant, or describe the grouping as evidence that learning improved.

## Reset between rehearsals

Create a new room instead of reusing a published fixture. Delete the prior room from Activities by confirming its invite
code. Clear each browser's Junto site data or use fresh profiles, and confirm that neither browser inherits host or
participant access from the previous run.
