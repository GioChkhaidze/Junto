# Junto interface system

## Design scene

A bright seminar room at midday: whiteboards, course packets, and unhurried green wayfinding. The interface should feel familiar to someone who uses Canvas, Piazza, or a university learning portal, with the directness and control discipline of Microsoft web products.

The design serves a timed academic task. It must disappear behind writing, navigation, progress, and group coordination.

## Visual register

- Restrained, white-first product interface.
- Green communicates primary action, current location, answered state, and completion—not decoration.
- One sans-serif family throughout: Inter when bundled, then `Segoe UI`, `system-ui`, and `sans-serif`.
- Fixed type scale with quiet hierarchy; no display typography or marketing-style headlines inside the application.
- Square-to-moderately-rounded geometry: 6px controls, 10px panels, circular progress steps only where the circle encodes a question number.
- Borders organize editable regions. Shadows are reserved for elevated menus and dialogs, never paired decoratively with bordered panels.

## Core tokens

All authored colors use OKLCH.

```css
:root {
  --color-bg: oklch(1 0 0);
  --color-surface: oklch(0.975 0.006 120);
  --color-surface-strong: oklch(0.945 0.012 120);
  --color-ink: oklch(0.225 0.025 130);
  --color-ink-muted: oklch(0.45 0.025 130);
  --color-border: oklch(0.86 0.012 120);
  --color-primary: oklch(0.43 0.105 120);
  --color-primary-hover: oklch(0.36 0.095 120);
  --color-primary-soft: oklch(0.94 0.045 120);
  --color-focus: oklch(0.58 0.14 135);
  --color-danger: oklch(0.5 0.18 28);
  --color-warning: oklch(0.7 0.14 80);
}
```

Text on the primary fill is white. Body and placeholder text must meet WCAG AA contrast on their surfaces. Muted text is not used for essential instructions.

## Spatial system

- 4px base unit.
- Dense control spacing: 8px and 12px.
- Standard component spacing: 16px and 20px.
- Section rhythm: 24px, 32px, and 48px.
- Reading measure: 65–72 characters.
- Application content width: 1180px maximum; writing measure remains narrower.

## Interaction vocabulary

- Primary button: one green filled action per decision area.
- Secondary button: neutral border, white background.
- Tertiary action: text button with a conventional underline on hover.
- All controls implement hover, focus-visible, active, disabled, loading, and error states.
- Focus remains visible with a two-pixel green ring and sufficient offset.
- Motion lasts 150–220ms, communicates state only, and becomes instant under `prefers-reduced-motion`.
- Loading content uses skeleton structure; destructive or irreversible actions require clear inline confirmation or a native dialog.

## Required product patterns

### Host authoring

The authoring surface is a sequential workspace, not a dashboard of cards:

1. optional reference-material upload;
2. room title and timing;
3. ordered question editor;
4. final review and room creation;
5. invite code and participant lobby.

Questions use a proper multiline editor with explicit labels, expected-time input, duplicate/delete/reorder actions, character count, and validation beside the field.

### Participant questionnaire

- One question per page.
- Previous and Next controls preserve the current answer before navigation.
- Keyboard shortcuts may supplement, never replace, visible controls.
- Numbered circular steps at the bottom encode question position and answered state. They are navigation controls, not decorative badges.
- The final page reviews completion and owns the single Submit answers action.
- A persistent timer announces remaining time accessibly without demanding constant attention.

### Results

- A participant sees only their group and member names.
- A host sees every group in a readable roster view.
- Analysis and optimization are separate visible stages even while their services are placeholders.

## Explicit bans

- No chips, tag clouds, pill-shaped status labels, gradient text, gradients, glass effects, decorative illustrations, or marketing metrics.
- No tiny uppercase tracked headings, “AI-powered” copy, conversational filler, fake quotes, or contrasting slogan fragments.
- No nested cards. Prefer page sections, dividers, tables, rosters, and field groups.
- No color used merely to make a neutral screen more exciting.
- No hidden autosave behavior: show `Saving`, `Saved`, or a recoverable error near the questionnaire navigation.
