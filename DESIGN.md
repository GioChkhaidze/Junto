# Junto interface system

## Product constraints

Junto is a live, accountless education and discussion tool. A room host may be an instructor, student, facilitator, or
hackathon participant; a participant joins by code, answers independently, and receives only their own discussion group.
Both roles must succeed under classroom time pressure without onboarding, profiles, or institutional setup.

The interface helps a discussion begin with complementary material already present in the room. It does not grade
participants, promise that every requested idea can appear in every group, or claim that grouping improves learning.
Every design decision preserves these principles:

1. Room before identity: access is anonymous and scoped to one room.
2. Thinking before grouping: participants answer independently before the cohort is composed.
3. One decision at a time: authoring and answering are sequential, legible workflows rather than dashboards.
4. Explain results honestly: distinguish model judgments, solver guarantees, feasibility, and uncertainty.
5. Protect the room: participants see only their own answers and group; hosts see only what they need to facilitate.
6. Let the interface disappear: use restrained white surfaces, green wayfinding, and familiar controls.

The product is calm, rigorous, collegial, and direct. Target WCAG 2.2 AA: support keyboard operation, visible focus,
narrow-screen reflow without horizontal page scrolling, 44-pixel touch targets, reduced motion, semantic labels and
headings, meaningful live announcements, and state indicators that do not depend on color alone.

## Design scene

Junto is used in a bright classroom or seminar room while a host prepares an activity and participants write under a
shared deadline. The host needs a calm, structured workspace with strong wayfinding. Participants need an almost
distraction-free writing surface where the question, response, timer, save state, and next action are immediately clear.

The interface combines two complementary modes:

- **Seminar console:** deep forest framing for host-controlled authoring and room management.
- **Editorial focus:** a white, typographic writing surface for participant questions and responses.

This is an academic tool, not a generic admin dashboard. Familiar controls and predictable navigation take priority over
novelty.

## Visual register

- White is the primary working canvas; deep forest green frames host-controlled areas.
- Green communicates primary action, current location, answered state, and completion. It is not decorative filler.
- Mona Sans Variable carries all application UI, labels, controls, headings, and data.
- Newsreader is reserved for participant question prompts. It never appears in navigation, buttons, labels, timers, or
  status text.
- Geometry is restrained: 6px controls, 10px panels, and true circles only when shape encodes a step or question.
- Borders organize editable regions. Shadows are limited to genuinely elevated elements.
- The existing Junto wordmark remains text-led until a separate logo direction is approved.

## Core tokens

All authored colors use OKLCH. The implemented source of truth is `frontend/src/styles/tokens.css`.

```css
:root {
  --canvas: oklch(1 0 0);
  --app-background: oklch(0.972 0.008 155);
  --surface-subtle: oklch(0.958 0.012 155);
  --line: oklch(0.875 0.014 155);
  --ink: oklch(0.205 0.022 155);
  --ink-secondary: oklch(0.39 0.022 155);
  --green-950: oklch(0.225 0.062 158);
  --green-800: oklch(0.36 0.105 155);
  --green-100: oklch(0.94 0.04 155);
}
```

Text and placeholders meet WCAG AA contrast on their surfaces. Muted text is never used for essential instructions.

## Typography

- UI body: Mona Sans, 1rem/1.5.
- Secondary UI: 0.875rem/1.45.
- Labels and controls: Mona Sans semibold, never uppercase-tracked decoration.
- Page heading: Mona Sans bold at a fixed application scale.
- Participant question: Newsreader semibold, approximately 2.25rem/1.18 on desktop and 1.65rem/1.25 on small screens.
- Long prose stays within 65–72 characters per line.
- Numeric timers use tabular figures.

Fonts are bundled through Fontsource packages rather than loaded from a third-party stylesheet at runtime.

## Spatial system

- 4px base unit.
- Dense control spacing: 8px and 12px.
- Standard component spacing: 16px, 20px, and 24px.
- Section rhythm: 32px, 48px, and 64px.
- Application header: 64px.
- Host workflow rail: 256–272px on wide screens.
- Host editor measure: approximately 960px.
- Participant writing measure: 760–880px, with the question kept narrower for comfortable reading.

## Host authoring pattern

The authoring route uses the seminar-console composition:

1. a deep forest application header;
2. a matching left workflow rail;
3. four numbered circular steps with checkmarks for completed steps;
4. a bright, spacious editor plane;
5. a stable bottom decision row for Back/Cancel and Continue/Create.

The four steps remain reference material, activity details, questions, and review. Completed steps are revisitable.
Future steps are visible but inactive. The rail becomes one horizontal four-step sequence below tablet width.

Questions remain proper form content, not decorative cards. Every question includes a multiline prompt, explicit editing
actions, coverage-unit rows, limits, validation, and an add-question action. One room-wide duration controls the
questionnaire.

When reference material exists, authoring assistance uses two quiet 44px icon controls: a drafting icon at the top-right
of each question and a list-edit icon beside its coverage-unit count. Native hover titles and accessible names change
between Draft/Suggest and Improve according to existing content. Loading disables competing suggestions; success reminds
the host to review; failure stays inline and leaves the draft unchanged. The controls never appear in participant
answering or solution surfaces and do not use sparkle, gradient, or promotional AI styling.

## Public entry pattern

The home and invitation routes establish the product before a room starts:

- The home route uses a full-height forest introduction beside a white action plane. It explains the prepare, respond,
  and group sequence with numbered circular steps, then separates creating from joining without a generic card.
- The invitation route uses the same split composition. Activity context stays on the forest side; the participant name
  field and privacy disclosure stay on the white side.
- Neither route uses promotional metrics, illustration, testimonial copy, accounts, or profile language.
- At tablet width the split becomes a vertical sequence, with activity context always preceding the form.

## Host room lifecycle pattern

Draft review, invitation lobby, response collection, group preparation, failure recovery, and published results share
one seminar-console shell:

- A forest header carries room identity and live state.
- The active room is one bordered white working surface on a quiet green-neutral application background.
- The invitation code is the dominant forest panel in the lobby. Readiness and roster information are subordinate report
  sections.
- Response collection promotes the shared timer and completion measure without becoming an analytics dashboard.
- Analysis communicates only the active backend phase and retains the same restrained work surface.
- Results use report hierarchy, dividers, rosters, and coverage rows. Capacity-only output is explicitly distinguished
  from coverage-aware output.
- Failure and unavailable states remain recoverable inside the same host shell.

## Participant questionnaire pattern

The participant route uses the editorial-focus composition:

- A slim white header contains Junto, the activity title, and the shared timer.
- One question appears per page.
- The question prompt uses Newsreader; every functional element remains Mona Sans.
- The response editor is a large, quiet writing plane with an explicit label, save state, character count, and autosave
  explanation.
- A fixed navigation bar places **Previous** at the left and **Next question** or **Review responses** at the right.
- All numbered question controls sit on one horizontal line centered between those actions.
- The current question is a filled forest circle.
- A completed non-current question displays a checkmark in a softly filled circle; unanswered questions display their
  numbers.
- Every navigation action saves the current response before moving.
- The final review page owns the only Submit responses action.

On narrow screens, question circles remain horizontal and scroll when necessary. Action buttons move to a second row so
touch targets and labels do not shrink.

## Participant lifecycle pattern

Join waiting, submitted, analysis, failure, and group-result states extend Editorial Focus beyond the questionnaire:

- Waiting states use a single editorial message, clear status line, and one progress rule when analysis is active.
- Submitted answers are described as locked; the page makes the automatic room update explicit.
- A published participant view shows only that participant's group, members, and question-by-question agenda.
- Coverage rows name the people who can introduce an idea without presenting coverage as a grade.
- Question prompts in a published agenda may use Newsreader because they are still source questions; navigation,
  members, statuses, and controls remain Mona Sans.

## Route composition matrix

| Route or state                       | Composition         | Primary surface                                   |
| ------------------------------------ | ------------------- | ------------------------------------------------- |
| Home                                 | Public split        | Forest explanation + white create/join actions    |
| Join invitation                      | Public split        | Forest activity context + white name form         |
| Create activity                      | Seminar console     | Forest workflow rail + white editor               |
| Host draft/lobby/answering           | Seminar console     | Forest header + one white room workspace          |
| Host analysis/failure/results        | Seminar console     | Forest header + restrained process/report surface |
| Participant lobby/submitted/analysis | Editorial focus     | White reading measure with explicit live state    |
| Participant questions/review         | Editorial focus     | White writer + fixed horizontal navigation        |
| Participant group                    | Editorial report    | White group roster and discussion agenda          |
| Not found                            | Public system state | Forest recovery page                              |

## Interaction vocabulary

- Primary button: one forest-green filled action per decision area.
- Secondary button: white background and neutral or forest border.
- Quiet action: text-led, with a restrained tinted hover surface.
- All controls implement hover, focus-visible, active, disabled, loading, and error states.
- Focus remains visible with a three-pixel green ring and sufficient offset.
- Motion lasts 150–220ms, communicates state only, and becomes effectively instant under `prefers-reduced-motion`.
- Loading content uses skeleton structure. Errors remain inline and recoverable.

## Results

- A participant sees only their group and member names.
- A host sees every group in a readable roster view.
- Coverage-aware results describe represented material and do not present coverage as a grade.
- Processing states report only stages the backend has actually entered.

## Explicit bans

- No account-heavy institutional SaaS patterns, administrator dashboards, or permanent teacher/student identities.
- No quiz-show noise, celebratory clutter, streaks, leaderboards, urgency theater, avatar piles, or dense analytics.
- No chips, tag clouds, pill-shaped status labels, gradient text, gradients, glass effects, decorative illustrations, or
  marketing metrics.
- No glowing accents, sparkle icons, fake progress, tiny uppercase tracked headings, “AI-powered” copy, conversational
  filler, fake quotes, or slogan fragments.
- No decorative card grids or nested cards. Prefer page sections, dividers, rosters, and field groups.
- No display font in functional UI.
- No hidden autosave behavior: Saving, Saved, Editing, and recoverable error states remain visible.
- No desktop layout compressed unchanged onto mobile; responsive behavior must recompose structurally.
