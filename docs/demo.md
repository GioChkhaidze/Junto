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
   disagreements in advance across both fixture questions. Never silently substitute the recorded artifact for a live
   call.

The event demo should prefer the reviewed live run when the provider is healthy and use the recorded run as an
explicitly named fallback.

## Preflight

Complete the [operations release checklist](operations.md#release-checklist), then verify:

- one fresh host browser and one fresh participant browser have no prior Junto cookies;
- the join disclosure appears before the participant enters a name;
- the room retention period is known;
- the model attempt limits and solver timeout are fixed;
- the reviewed fixture completes within the configured analysis timeout;
- the host can explain missing coverage and model uncertainty without calling either a grade;
- the fallback screen and restart/provider-failure drills have been seen by the presenters.

Avoid spending demo time on accounts, WebSockets, database internals, or infrastructure diagrams. The product is the
transition from individual answers to a useful discussion agenda.

## Reviewed room

Use these settings:

| Setting    | Value                                   |
| ---------- | --------------------------------------- |
| Title      | Complementary reasoning workshop        |
| Policy     | Teach each other                        |
| Group size | Minimum 3, preferred 4, maximum 5       |
| Time       | 20 minutes (shorten only for rehearsal) |

Question 1:

> A robot starts at cell 0 and must reach cell n on a line. It may move one or two cells at a time, and some cells are
> blocked. Explain an algorithm that counts the valid routes and give its complexity.

Reference material:

> A complete dynamic-programming explanation should define the route-count state, establish the start state, prevent
> blocked cells from receiving routes, relate each unblocked cell to the two preceding cells (or give the equivalent
> forward propagation), and analyze runtime and storage.

Coverage units:

1. Defines a state as the number of valid routes that reach a particular cell.
2. Establishes one route at the starting cell as the base case.
3. Makes a blocked cell contribute zero routes.
4. Combines the route counts from one-step and two-step predecessors, or propagates them forward equivalently.
5. Explains that processing each cell once gives linear time and states the storage cost.

Question 2:

> Does a university have the moral right to require AI proctoring for remote examinations? Defend a position and address
> the strongest competing considerations.

Reference material:

> The discussion should weigh academic integrity against privacy and autonomy, examine unequal burdens and false flags,
> consider less intrusive alternatives, and address proportional safeguards. Multiple conclusions can be defensible when
> they engage those considerations accurately.

Coverage units:

1. Explains a privacy or autonomy interest affected by remote monitoring.
2. Articulates the university's academic-integrity justification.
3. Addresses unequal accessibility, bias, or false-positive burdens.
4. Considers a less intrusive way to verify learning or deter cheating.
5. Identifies safeguards needed for proportionality, review, or appeal.

These values come directly from the canonical
[programming fixture](../backend/tests/fixtures/semantic/programming_dynamic_programming.json) and
[philosophy fixture](../backend/tests/fixtures/semantic/philosophy_ai_proctoring.json). The loader reads those files at
runtime; this guide does not define a second copy. The first question makes objective technical coverage visible. The
second demonstrates that coverage is not a synonym for a correct conclusion: participants can defend opposing positions,
belong to different response families, and still contribute relevant considerations.

## Two-presenter flow from fresh browsers

Presenter A owns the host browser. Presenter B owns a fresh participant browser and narrates the participant experience.

1. Presenter A opens `/create`, enters both reviewed prompts, reference passages, and coverage units exactly as written
   above, sets the time and group sizes, and creates the invite.
2. Presenter B opens `/join/{code}`, reads the data/model disclosure, enters a room-scoped name, and waits in the lobby.
3. On a loopback rehearsal deployment, load the remaining reviewed cohort through normal HTTP:

   ```powershell
   backend\.venv\Scripts\python.exe backend\scripts\load_demo.py --join-code INVITE_CODE --participants 11
   ```

   The loader joins the lobby and waits. It does not touch the database or receive host access.

4. Presenter A shows the frozen roster and starts once. The shared deadline is server-owned.
5. The loader cycles the exact reviewed fixture responses. Presenter B answers one question per page, moves forward and
   back to show save-before-navigation, checks the numbered completion markers, reviews, and submits. In recorded mode,
   Presenter B must use exact answer text from the linked fixtures so the offline adapter can match it; in live mode
   they may answer naturally.
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

To read the two canonical JSON fixtures, create the room, join 12 participants, cycle their exact answers, submit, wait
for analysis, and report the terminal state through the public API:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\load_demo.py --participants 12 --wait-seconds 300
```

For the supported classroom polling envelope:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\load_demo.py --participants 60 --poll-rounds 3 --wait-seconds 300
```

Success requires `status: published`, exactly-once membership, valid group capacities, diagnostics derived from the
final partition, and no content-bearing logs. A fast response on one laptop is not a production load claim.

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

Create a new room instead of reusing a published fixture. Verify the prior room expires or is deleted under the
configured retention rule. Clear each browser's Junto site data or use fresh profiles, and confirm that neither browser
inherits host or participant access from the previous run.
