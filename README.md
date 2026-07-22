# Junto

Purposeful discussion groups, built from what participants know and think.

## Inspiration

Instructors know that strong discussion groups are rarely random. Students learn more when each group brings together
complementary knowledge, reasoning, evidence, and perspectives, but reading every response and assembling those groups
takes too much time during a live class.

The name captures the product's purpose: in English, a _junto_ is a small group formed around a shared goal; in Spanish,
_junto_ means "together." Junto began with a practical question: can we remove the administrative burden of grouping
while creating more fruitful discussions?

## What it does

Junto is an accountless, room-based web application that forms discussion groups from participants' submitted answers. A
host creates an activity, optionally uploads reference material, writes the questions, and defines the ideas or
perspectives worth covering. Participants join with an invite code, enter their names, and answer independently.

When responses close, Junto:

1. identifies which host-defined coverage units appear in each answer;
2. recognizes meaningful response families, such as competing positions or different approaches;
3. uses constrained optimization to form capacity-valid groups with the strongest feasible coverage; and
4. gives each participant their group members and a focused discussion plan showing what is represented and who can
   introduce it.

Coverage is subject-agnostic. In programming, units might include a recurrence, base case, and complexity; in history or
literature, they might be evidence, arguments, objections, and perspectives. Junto does not assume every question has
one correct conclusion.

The product promise is deliberately bounded:

> Form capacity-valid groups with the strongest feasible coverage of every question's host-approved ideas and productive
> perspectives.

Junto does not grade participants, guarantee that every requested idea can appear in every group, or claim that grouping
improves learning.

## How we built it

The frontend uses React, Vite, TypeScript, and CSS Modules. The backend uses FastAPI, PostgreSQL, Pydantic, and OR-Tools
CP-SAT. The OpenAI API converts natural-language answers into independently validated coverage and response-family
assignments. The model interprets language; the deterministic optimizer enforces group sizes and makes the final group
assignments.

The workflow includes signed room sessions, CSRF and origin checks, bounded uploads, autosave, role-specific results,
atomic result publication, and recovery from failed analysis. A recorded-provider mode supports repeatable offline
tests. For demos, hosts can add clearly identified simulated participants with varied knowledge, confidence, reasoning
styles, and mistakes; OpenRouter's Gemini 2.5 Flash generates their answers without deciding the groups.

The hackathon deployment runs as a Cloudflare Container with Neon PostgreSQL.

## Challenges we ran into

The hardest problem was defining what makes a group "good." Early versions focused too heavily on correct answers, which
failed for subjects where disagreement is productive. Coverage units broadened the design to include concepts, reasoning
steps, evidence, arguments, objections, and perspectives.

Other challenges included obtaining reliable structured model output, handling incomplete or mistaken answers, keeping
latency and cost practical, and behaving sensibly when perfect coverage is mathematically impossible.

## Accomplishments

Junto now supports the complete workflow from activity creation to auditable, published groups across both objective and
open-ended subjects. It makes grouping decisions understandable through visible coverage reports and includes realistic
simulated cohorts for repeatable demos and stress testing.

## What we learned

AI is most useful here as an interpreter, not an unconstrained decision-maker. Language models recognize ideas and
perspectives in natural language, while a solver enforces group sizes and distributes those ideas consistently. Junto
cannot create knowledge that is absent from the room, but it can search for the strongest feasible distribution of what
participants contributed.

## Built with Codex

OpenAI Codex was used throughout development as a collaborative engineering agent. It helped:

- turn the product idea and constraints into the product, architecture, and operations documentation;
- implement and refine the React frontend, FastAPI backend, semantic-analysis pipeline, and OR-Tools integration;
- write and run automated tests, investigate failures, and iterate on the UI through live browser checks; and
- containerize the application and configure its Cloudflare Workers/Containers and Neon deployment.

The human developer directed the product, selected the tradeoffs, supplied credentials, approved deployments, and
reviewed the results. Codex is a development tool for this repository; Junto's deployed semantic features call the
separately configured model providers described above.

## Documentation

Technical details live in the [product contract](docs/product.md), [architecture](docs/architecture.md),
[semantic engine](docs/engine.md), [evaluation guide](docs/evaluation.md), and [operations guide](docs/operations.md).

## What's next

The next step is classroom evaluation: measuring participation, peer explanation, and discussion quality. Planned work
also includes a stronger semantic benchmark, clearer host controls, improved accessibility and recovery, and optional
learning-management-system integrations.
