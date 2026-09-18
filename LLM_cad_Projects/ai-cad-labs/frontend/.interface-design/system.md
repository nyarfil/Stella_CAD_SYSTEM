# AI-CAD Frontend: Interface Design System

> Canonical design-system artifact. Produced 2026-07-13; every previously-open token decision is resolved HERE; this document is its own canon.
> Build agents: tokens are LIVE in `src/index.css` (materialized 2026-07-13; §3 mirrors it):
> consume the utilities and follow the pattern specs.
> Aesthetic amplification of sheets/negotiation drama belongs to a later aesthetic-amplification pass; these
> tokens are its substrate, not its ceiling. Every contrast figure below is **computed**
> (WCAG 2.1, coloraide), not estimated.

---

## §1 Direction

**The world**: a drawing office. Two rooms, one product:

- **Dark "drafting board"** (DEFAULT: the app boots into this look): white drawing sheets
  glowing on a dark instrument board, like film on a lightbox. Chrome is a cool machined
  green-gray (drafting-table linoleum, hue 175, chroma ≤0.008; felt, not seen).
- **Light "drawing office"**: the same sheets on a warm paper-gray desk (vellum hue 92).
  Calm, archival, daylight.

**The signature: paper is theme-invariant.** The `sheet` token family (paper, ink, rules,
frame) never changes between themes: paper is paper under any light. Only the chrome flips.
This is what makes the white-background render PNGs read as *mounted drawings*, never as
unstyled divs: in dark mode the sheet separates by glow (measured 19.5:1 vs board), in light
mode by hairline frame + paper-lift shadow (1.11:1; lightness alone cannot carry it there).
**Never tint the sheets or the PNGs** (locked decision). No dark-mode image filters, ever.

**Second signature: borders are drafting pens.** The border system is a pen tray: hairline /
object / heavy line weights (ISO 128 pen discipline), not generic border/border-subtle.
Depth is **borders-first, flat instrument**: no card shadows. Shadow is reserved for things
that are physically floating: the sheet on the light-office desk, popovers in light mode,
and the lightbox overlay. Dark mode uses zero shadows except the scrim (borders + lightness
steps carry all structure).

**Voice**: drafting-terse. Uppercase micro-labels (VIEW, REV, SEVERITY), stamped verdicts,
mono for anything that is data. No decoration that isn't drafting grammar: **no blueprint
washes, no faux grid paper, no ruled borders on every panel** (a standing REJECT, upheld).

**Rejected defaults** → replacements:
| Default | Replaced by |
|---|---|
| shadcn zinc neutrals + shadow elevation | ink/vellum + board green-gray; pen-weight borders, surface steps |
| Filled status pills (white-on-green) | outlined ink **stamps**: tinted text + hairline line + faint fill |
| Blueprint-blue decorative wash | drafting grammar in structure only (title blocks, line weights, labels) |
| Geist/Inter house font | IBM Plex Sans + IBM Plex Mono (genuine engineering-industrial heritage) |

---

## §2 Mode strategy

One token set, two value maps. `[data-theme]` attribute switching, dark at `:root`
(materialized in `src/index.css` 2026-07-13):

- **`:root` holds the dark "drafting board" values**; dark is the structural default: the
  app boots into the recorded demo look with zero markup (no class or attribute needed).
- **`:root[data-theme="light"]` holds the light "drawing office"** overrides; its (0,2,0)
  specificity beats `:root`, so the switch is order-independent. A future theme toggle sets
  `document.documentElement.dataset.theme = "light"` and deletes it to return to dark.
- shadcn `dark:` utilities keep working via `@custom-variant dark
  (&:is(:root:not([data-theme="light"]) *))`; they fire whenever light is not set.
- Sheet-family tokens are defined once in `:root` and **not overridden** in the light block;
  the theme-invariance is structural, not a convention to remember.

---

## §3 Token CSS (paste-ready for `src/index.css`)

**MATERIALIZED 2026-07-13: `src/index.css` is the live token layer; this section mirrors
it** (values/selectors identical, diff-verified; only self-reference comment phrasing and
block order differ; the live file puts `:root` dark first; order is free per §2 specificity).
Replaced the provisional Geist import, `@theme inline`, `:root`, and `.dark` blocks; kept
`@import "tailwindcss"`, `tw-animate-css`, `shadcn/tailwind.css`. The `@custom-variant dark`
line is redefined per §2. `--radius-3xl/4xl` retained (scaffold Badge uses `rounded-4xl`).

Fonts: install and import (replaces `@fontsource-variable/geist`):

```bash
npm i @fontsource-variable/ibm-plex-sans @fontsource/ibm-plex-mono
```

```css
@import "@fontsource-variable/ibm-plex-sans";
@import "@fontsource/ibm-plex-mono/400.css";
@import "@fontsource/ibm-plex-mono/500.css";
@import "@fontsource/ibm-plex-mono/600.css";
/* Fallback if the variable package is unavailable: @fontsource/ibm-plex-sans 400/500/600 */
```

```css
/* Dark "drafting board" is the :root default; html[data-theme="light"] switches to the
   light "drawing office". shadcn dark: utilities fire whenever light is not set. */
@custom-variant dark (&:is(:root:not([data-theme="light"]) *));

@theme inline {
    /* type */
    --font-sans: 'IBM Plex Sans Variable', 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
    --font-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', monospace;
    --font-heading: var(--font-sans);
    --text-2xs: 0.6875rem;              /* 11px: micro-labels */
    --text-2xs--line-height: 0.875rem;
    --tracking-label: 0.08em;           /* uppercase micro-label tracking */

    /* shadcn semantic mapping (unchanged names) */
    --color-background: var(--background);
    --color-foreground: var(--foreground);
    --color-card: var(--card);
    --color-card-foreground: var(--card-foreground);
    --color-popover: var(--popover);
    --color-popover-foreground: var(--popover-foreground);
    --color-primary: var(--primary);
    --color-primary-foreground: var(--primary-foreground);
    --color-secondary: var(--secondary);
    --color-secondary-foreground: var(--secondary-foreground);
    --color-muted: var(--muted);
    --color-muted-foreground: var(--muted-foreground);
    --color-accent: var(--accent);
    --color-accent-foreground: var(--accent-foreground);
    --color-destructive: var(--destructive);
    --color-border: var(--border);
    --color-input: var(--input);
    --color-ring: var(--ring);
    --color-chart-1: var(--chart-1);
    --color-chart-2: var(--chart-2);
    --color-chart-3: var(--chart-3);
    --color-chart-4: var(--chart-4);
    --color-chart-5: var(--chart-5);
    --color-sidebar: var(--sidebar);
    --color-sidebar-foreground: var(--sidebar-foreground);
    --color-sidebar-primary: var(--sidebar-primary);
    --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
    --color-sidebar-accent: var(--sidebar-accent);
    --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
    --color-sidebar-border: var(--sidebar-border);
    --color-sidebar-ring: var(--sidebar-ring);

    /* ink hierarchy (4 levels; level 1 = foreground) */
    --color-ink-secondary: var(--ink-secondary);
    --color-ink-tertiary: var(--muted-foreground);
    --color-ink-faint: var(--ink-faint);

    /* drafting pen tray (border colors; widths in §5) */
    --color-stroke-hairline: var(--stroke-hairline);
    --color-stroke-object: var(--border);
    --color-stroke-strong: var(--stroke-strong);
    --color-stroke-heavy: var(--stroke-heavy);

    /* surfaces */
    --color-surface-inset: var(--surface-inset);

    /* sheet family (THEME-INVARIANT: paper is paper) */
    --color-sheet: var(--sheet);
    --color-sheet-ink: var(--sheet-ink);
    --color-sheet-ink-soft: var(--sheet-ink-soft);
    --color-sheet-rule: var(--sheet-rule);
    --color-sheet-frame: var(--sheet-frame);

    /* interactive trace (non-photo pencil blue) */
    --color-trace: var(--trace);

    /* status ink families: ink = text, line = border, fill = tint */
    --color-pass-ink: var(--pass-ink);
    --color-pass-line: var(--pass-line);
    --color-pass-fill: var(--pass-fill);
    --color-fail-ink: var(--fail-ink);
    --color-fail-line: var(--fail-line);
    --color-fail-fill: var(--fail-fill);
    --color-warn-ink: var(--warn-ink);
    --color-warn-line: var(--warn-line);
    --color-warn-fill: var(--warn-fill);
    --color-note-ink: var(--note-ink);
    --color-note-line: var(--note-line);
    --color-note-fill: var(--note-fill);

    /* agent identity dots (9 roles) */
    --color-agent-orchestrator: var(--agent-orchestrator);
    --color-agent-planner: var(--agent-planner);
    --color-agent-cad-designer: var(--agent-cad-designer);
    --color-agent-validator: var(--agent-validator);
    --color-agent-repair: var(--agent-repair);
    --color-agent-assembly-resolver: var(--agent-assembly-resolver);
    --color-agent-sourcing: var(--agent-sourcing);
    --color-agent-reviewer: var(--agent-reviewer);
    --color-agent-dfma-inspector: var(--agent-dfma-inspector);

    /* assembly legend (FIXED renderer inks: never restyle, never theme) */
    --color-legend-red: #ff0000;
    --color-legend-blue: #0000ff;
    --color-legend-green: #008000;
    --color-legend-orange: #ffa500;
    --color-legend-purple: #800080;
    --color-legend-teal: #008080;
    --color-legend-brown: #a52a2a;
    --color-legend-magenta: #ff00ff;
    --color-legend-paper: #ffffff;

    /* misc */
    --color-scrim: var(--scrim);
    --color-wash-hover: var(--wash-hover);
    --radius-sm: calc(var(--radius) * 0.6);
    --radius-md: calc(var(--radius) * 0.8);
    --radius-lg: var(--radius);
    --radius-xl: calc(var(--radius) * 1.4);
    --radius-2xl: calc(var(--radius) * 1.8);
    --radius-3xl: calc(var(--radius) * 2.2);
    --radius-4xl: calc(var(--radius) * 2.6);
    --radius-sheet: 0.125rem;           /* 2px: drawing sheets are near-sharp */
    --shadow-sheet: var(--sheet-lift);
    --shadow-float: var(--float);
}

/* ─── LIGHT: "drawing office" (warm vellum chrome, hue 92), html[data-theme="light"] ─── */
:root[data-theme="light"] {
    --background: oklch(0.965 0.004 92);
    --foreground: oklch(0.22 0.010 95);
    --card: oklch(0.985 0.003 92);
    --card-foreground: oklch(0.22 0.010 95);
    --popover: oklch(1 0 0);
    --popover-foreground: oklch(0.22 0.010 95);
    --primary: oklch(0.27 0.012 95);
    --primary-foreground: oklch(0.97 0.004 92);
    --secondary: oklch(0.94 0.005 92);
    --secondary-foreground: oklch(0.27 0.012 95);
    --muted: oklch(0.94 0.005 92);
    --muted-foreground: oklch(0.48 0.012 95);       /* ink-tertiary */
    --accent: oklch(0.945 0.005 92);                 /* hover wash surface (shadcn) */
    --accent-foreground: oklch(0.22 0.010 95);
    --destructive: oklch(0.50 0.17 27);
    --border: oklch(0.25 0.02 95 / 0.14);            /* object line */
    --input: oklch(0.25 0.02 95 / 0.22);
    --ring: oklch(0.47 0.11 235);
    --chart-1: oklch(0.30 0.010 95);
    --chart-2: oklch(0.42 0.010 95);
    --chart-3: oklch(0.55 0.010 95);
    --chart-4: oklch(0.68 0.008 92);
    --chart-5: oklch(0.80 0.006 92);
    --sidebar: oklch(0.965 0.004 92);                /* = background; border separates */
    --sidebar-foreground: oklch(0.22 0.010 95);
    --sidebar-primary: oklch(0.27 0.012 95);
    --sidebar-primary-foreground: oklch(0.97 0.004 92);
    --sidebar-accent: oklch(0.945 0.005 92);
    --sidebar-accent-foreground: oklch(0.22 0.010 95);
    --sidebar-border: oklch(0.25 0.02 95 / 0.14);
    --sidebar-ring: oklch(0.47 0.11 235);

    --ink-secondary: oklch(0.37 0.010 95);
    --ink-faint: oklch(0.60 0.010 95);
    --surface-inset: oklch(0.94 0.005 92);
    --stroke-hairline: oklch(0.25 0.02 95 / 0.09);
    --stroke-strong: oklch(0.25 0.02 95 / 0.26);
    --stroke-heavy: oklch(0.25 0.02 95 / 0.55);
    --trace: oklch(0.47 0.11 235);
    --wash-hover: oklch(0.25 0.02 95 / 0.04);
    --scrim: oklch(0.25 0.015 95 / 0.45);
    --sheet-lift: 0 1px 2px oklch(0.25 0.02 95 / 0.10), 0 4px 16px oklch(0.25 0.02 95 / 0.08);
    --float: 0 1px 3px oklch(0.25 0.02 95 / 0.10), 0 8px 24px oklch(0.25 0.02 95 / 0.10);

    /* sheet family: intentionally NOT overridden; paper is paper (§1 signature) */

    /* status inks (light) */
    --pass-ink: oklch(0.44 0.13 150);
    --pass-line: oklch(0.55 0.12 150 / 0.50);
    --pass-fill: oklch(0.60 0.12 150 / 0.10);
    --fail-ink: oklch(0.50 0.17 27);
    --fail-line: oklch(0.58 0.16 27 / 0.50);
    --fail-fill: oklch(0.62 0.16 27 / 0.10);
    --warn-ink: oklch(0.50 0.12 70);
    --warn-line: oklch(0.62 0.12 70 / 0.55);
    --warn-fill: oklch(0.70 0.12 70 / 0.12);
    --note-ink: oklch(0.47 0.09 92);
    --note-line: oklch(0.60 0.09 92 / 0.55);
    --note-fill: oklch(0.70 0.09 92 / 0.12);

    /* agent hues (light: L 0.55, C 0.105); hue is the role's identity, constant across themes */
    --agent-orchestrator: oklch(0.55 0.105 290);
    --agent-planner: oklch(0.55 0.105 240);
    --agent-cad-designer: oklch(0.55 0.105 205);
    --agent-validator: oklch(0.55 0.105 180);
    --agent-repair: oklch(0.55 0.105 55);
    --agent-assembly-resolver: oklch(0.55 0.105 310);
    --agent-sourcing: oklch(0.55 0.105 100);
    --agent-reviewer: oklch(0.55 0.105 265);
    --agent-dfma-inspector: oklch(0.55 0.105 340);
}

/* ─── DARK: "drafting board" (cool machined chrome, hue 175), the :root DEFAULT ─── */
:root {
    --background: oklch(0.155 0.006 175);            /* the board */
    --foreground: oklch(0.93 0.005 170);
    --card: oklch(0.19 0.006 175);
    --card-foreground: oklch(0.93 0.005 170);
    --popover: oklch(0.23 0.007 175);
    --popover-foreground: oklch(0.93 0.005 170);
    --primary: oklch(0.93 0.005 170);
    --primary-foreground: oklch(0.17 0.006 175);
    --secondary: oklch(0.245 0.007 175);
    --secondary-foreground: oklch(0.93 0.005 170);
    --muted: oklch(0.245 0.007 175);
    --muted-foreground: oklch(0.665 0.008 173);      /* ink-tertiary */
    --accent: oklch(0.235 0.007 175);                /* hover wash surface (shadcn) */
    --accent-foreground: oklch(0.93 0.005 170);
    --destructive: oklch(0.78 0.14 25);
    --border: oklch(0.85 0.01 175 / 0.16);           /* object line */
    --input: oklch(0.85 0.01 175 / 0.22);
    --ring: oklch(0.74 0.10 235);
    --chart-1: oklch(0.85 0.006 175);
    --chart-2: oklch(0.68 0.008 175);
    --chart-3: oklch(0.55 0.008 175);
    --chart-4: oklch(0.42 0.007 175);
    --chart-5: oklch(0.30 0.006 175);
    --radius: 0.5rem;
    --sidebar: oklch(0.155 0.006 175);               /* = background; border separates */
    --sidebar-foreground: oklch(0.93 0.005 170);
    --sidebar-primary: oklch(0.93 0.005 170);
    --sidebar-primary-foreground: oklch(0.17 0.006 175);
    --sidebar-accent: oklch(0.235 0.007 175);
    --sidebar-accent-foreground: oklch(0.93 0.005 170);
    --sidebar-border: oklch(0.85 0.01 175 / 0.16);
    --sidebar-ring: oklch(0.74 0.10 235);

    --ink-secondary: oklch(0.80 0.006 172);
    --ink-faint: oklch(0.52 0.008 175);
    --surface-inset: oklch(0.125 0.005 175);         /* code wells, control bg; inset = darker */
    --stroke-hairline: oklch(0.85 0.01 175 / 0.10);
    --stroke-strong: oklch(0.85 0.01 175 / 0.28);
    --stroke-heavy: oklch(0.85 0.01 175 / 0.45);
    --trace: oklch(0.74 0.10 235);
    --wash-hover: oklch(0.95 0.005 175 / 0.04);
    --scrim: oklch(0.10 0.005 175 / 0.75);
    --sheet-lift: none;                              /* dark: the 19.5:1 glow IS the lift */
    --float: none;                                   /* dark: borders + lightness carry depth */

    /* sheet family, THEME-INVARIANT (defined once here, never overridden in light):
       paper is paper under any light; --sheet matches render-PNG white exactly */
    --sheet: oklch(1 0 0);
    --sheet-ink: oklch(0.20 0.01 95);
    --sheet-ink-soft: oklch(0.20 0.01 95 / 0.45);
    --sheet-rule: oklch(0.20 0.01 95 / 0.12);        /* quadrant dividers, title-block rules */
    --sheet-frame: oklch(0.20 0.01 95 / 0.35);       /* drafting border frame */

    /* status inks (dark: desaturation via higher L, same hues) */
    --pass-ink: oklch(0.80 0.14 150);
    --pass-line: oklch(0.62 0.13 150 / 0.45);
    --pass-fill: oklch(0.70 0.13 150 / 0.10);
    --fail-ink: oklch(0.78 0.14 25);
    --fail-line: oklch(0.60 0.16 25 / 0.45);
    --fail-fill: oklch(0.62 0.16 25 / 0.10);
    --warn-ink: oklch(0.82 0.12 70);
    --warn-line: oklch(0.66 0.12 70 / 0.45);
    --warn-fill: oklch(0.70 0.12 70 / 0.10);
    --note-ink: oklch(0.80 0.085 92);
    --note-line: oklch(0.64 0.09 92 / 0.45);
    --note-fill: oklch(0.70 0.09 92 / 0.10);

    /* agent hues (dark: L 0.72, C 0.09) */
    --agent-orchestrator: oklch(0.72 0.09 290);
    --agent-planner: oklch(0.72 0.09 240);
    --agent-cad-designer: oklch(0.72 0.09 205);
    --agent-validator: oklch(0.72 0.09 180);
    --agent-repair: oklch(0.72 0.09 55);
    --agent-assembly-resolver: oklch(0.72 0.09 310);
    --agent-sourcing: oklch(0.72 0.09 100);
    --agent-reviewer: oklch(0.72 0.09 265);
    --agent-dfma-inspector: oklch(0.72 0.09 340);
}
```

Keep the existing `@layer base` block; add `html { @apply font-sans; }` antialiasing as-is.

---

## §4 Surfaces & elevation datum

**Depth strategy: borders-first flat instrument** (committed; do not mix in card shadows).

| Level | Token | Dark L | Light L | Used for |
|---|---|---|---|---|
| −1 inset | `surface-inset` | 0.125 | 0.94 | code wells, input/control backgrounds, empty-state wells |
| 0 base | `background` | 0.155 | 0.965 | app canvas + sidebar (same surface, border-separated) |
| 1 panel | `card` | 0.19 | 0.985 | cards, panels, table containers |
| 2 float | `popover` | 0.23 | 1.0 + `shadow-float` | dropdowns, tooltips, popovers |
| ∞ paper | `sheet` | **1.0 (both)** | 1.0 + `shadow-sheet` | RenderSheet, TitleBlock, lightbox content |

- Each chrome step is 3-4 L-points, whisper-quiet (squint test: hierarchy without jumps).
- **Sheet-to-chrome contrast strategy** (resolved + measured): dark,
  sheet vs board **19.5:1** (the lightbox glow; no border needed, keep the drafting frame
  anyway because real sheets have one); light, sheet vs chrome 1.11:1, so separation comes
  from `sheet-frame` (1.5px) + `shadow-sheet` paper lift. PNGs sit directly on `sheet` with
  no seam (both are exactly white). **No filters, no tinting, no dark-mode image inversion.**
- Overlay: `scrim` + Dialog content on `sheet` (lightbox shows the render at full size;
  the one place drama is allowed to be literal: a lit sheet in a dark room).

## §5 Line-weight scale (drafting pens)

Border **color** tokens (above) pair with fixed **widths**; pen discipline, never mixed:

| Pen | Width | Color token | Use |
|---|---|---|---|
| hairline | 1px | `stroke-hairline` | table row rules, quadrant dividers, tag borders |
| object | 1px | `stroke-object` (=`border`) | card/panel/chip borders, sidebar separation |
| strong | 1px | `stroke-strong` | hover-emphasized borders, active card edge |
| heavy | 2px | `stroke-heavy` | title-block frame, section rules, resolution rule |
| sheet-frame | 1.5px | `sheet-frame` | the drawing sheet's border frame (on paper only) |

On-sheet rules always use `sheet-rule`/`sheet-frame` (ink on paper), never chrome strokes.

## §6 Type system

**IBM Plex Sans (variable) + IBM Plex Mono**: chosen for engineering-industrial heritage
(drafting-machine DNA, distinct personality vs default Inter/Geist; passes the swap test).
Both support `tabular-nums`.

| Level | Spec | Use |
|---|---|---|
| micro-label | `text-2xs` (11px) · uppercase · `tracking-label` · weight 500 · ink-tertiary | VIEW/REV/SEVERITY labels, quadrant labels, title-block field names |
| data-small | `text-xs` (12px) · mono | table cells, rule_ids, timestamps, log lines |
| body-ui | `text-sm` (14px) · sans 400 | prose, card body, minutes fields |
| section | `text-lg` (18px) · sans 600 · tight tracking | tab-panel + section headings |
| page | `text-xl` (20px) · sans 600 | screen titles |
| hero | `text-2xl` (24px) · sans 600 | part name in title block |

- **Mono roles**: part names, rule_ids, specs, code, agent names, REV numbers,
  balloon numbers. Mono = "this is data."
- **`tabular-nums` mandatory** on every score, count, qty, and timestamp column.
- Micro-labels are the drafting lettering voice: never bold, never colored decoration.

## §7 Status semantics (all TOKENS-TBD resolved; measured contrast)

Four ink families + neutral. Chip anatomy = **ink stamp**: tinted text (`*-ink`) + 1px
border (`*-line`) + faint fill (`*-fill`); never filled pills. Color is **never the only
channel**: every chip carries its literal text label + `data-state` attribute.

| Semantic | Family | Dark ratio* | Light ratio* |
|---|---|---|---|
| verdict PASSED · issue RESOLVED · outcome success | `pass` (green 150) | 8.98 | 6.29 |
| verdict FAILED · severity critical · issue OPEN · outcome failure | `fail` (red 27) | 7.91 | 5.57 |
| severity major · probationary-warning | `warn` (amber 70) | 9.04 | 5.33 |
| severity minor | `note` (ochre 92) | 8.57 | 5.93 |
| verdict/presence pending · absent | neutral (no hue) | 6.07 (ink-tertiary) | 6.26 |

\* ink over card+fill composite, WCAG 2.1; all ≥4.5 AA with margin (survives popover surfaces too).

- **Verdicts** (`StatusChip` stamp variant): uppercase 11px weight-600 `tracking-label`,
  `px-2 py-0.5 rounded-sm`, family ink/line/fill. PASSED=pass, FAILED=fail,
  PENDING=neutral (ink-tertiary text, `stroke-object` border, no fill).
- **Severity**: critical=fail, major=warn, minor=note. **Probationary-warning** = warn
  family + **dashed border** (dashed = provisional, drafting-native) + label PROBATIONARY.
- **Presence** (`StatusChip` tag variant, quiet): 11px weight-450 lowercase as-logged,
  no fill; present = ink-secondary + solid `stroke-hairline`; pending = ink-tertiary +
  **dashed** hairline; absent = ink-faint + **dotted** hairline. Mid-run absence is calm.
- **Issue OPEN/RESOLVED**: stamp variant, fail/pass families; the red→green stamp flip
  must stay legible at 1080p screen-capture resolution.
- **Resolution emphasis** (NegotiationCard payoff): block with `border-l-2` in `pass-ink`,
  `pass-fill` background, RESOLUTION micro-label in `pass-ink`, body in `foreground`
  at `text-sm`. (a later aesthetic pass may amplify further; keep these tokens as the base.)

## §8 Agent identity: 9 characters, instrument-grade

Locked: distinct persistent hue per role. Execution: **colored index tabs, not colored
files**: the hue lives in a small ink dot, never in filled chips or tinted text.

**AgentChip anatomy**: `inline-flex items-center gap-1.5` · 7px `rounded-full` dot in the
role hue · role name in mono 12px `ink-secondary`, **exactly as logged** (`cad_designer`) ·
optional `stroke-hairline` border · `data-agent="<role>"`. Timeline/negotiation entries may
additionally carry a 2px left rule in the role hue.

| Role | Hue | Mnemonic |
|---|---|---|
| orchestrator | 290 violet | the chairman's ink |
| reviewer | 265 indigo | the margin note |
| planner | 240 blue | the blueprint |
| cad_designer | 205 cyan | the drafting pen |
| validator | 180 teal | the inspection instrument |
| sourcing | 100 olive | the procurement ledger |
| repair | 55 orange | the repair tag |
| assembly_resolver | 310 mauve | the negotiator |
| dfma_inspector | 340 rose | the checker's pencil |

Same hue per role in both themes (identity is the hue); only L/C shift (dark 0.72/0.09,
light 0.55/0.105). All dots measured ≥4.4:1 vs card in both themes (needs only 3:1 non-text).
Chroma is capped at ~0.1 so the agent layer reads muted against the saturated legend layer;
hues avoid the pass-green (130-170) and fail-red (7-47) meaning zones, except repair 55,
which is allowed because dots are never verdict positions and always sit beside a text label.

## §9 Assembly legend: fidelity rule (HARD CONSTRAINT honored)

The renderer strokes parts in literal CSS-named colors; `color_legend.txt` names them. The
UI must show **exactly those inks**: `legend-*` tokens are hex literals, theme-invariant,
and **must never be remapped, desaturated, or themed**.

**LegendTable swatch = a paper chip**: a small `legend-paper` (white) rectangle bearing a
solid bar of the literal legend color, bordered with `sheet-rule`; i.e. the swatch shows
the ink *as it appears on the sheet*, which is where the user's eye will match it. This
sidesteps dark-bg visibility entirely (blue/purple/brown stay legible on their white chip
in both themes) and achieves better-than-"closest accessible swatch" fidelity: zero remap,
constant white context, unmistakably the renderer's colors.

Measured vs white paper: blue 8.59 · purple 9.42 · brown 7.08 · green 5.14 · teal 4.77 ·
red 4.00 · magenta 3.14 · **orange 1.97**. Orange is below the 3:1 non-text line, accepted
as **required presentation** (fidelity to the render is the function); the part-name label
beside every swatch carries identification at full AA, so color is never the sole channel.

## §10 Density registers

| Register | Where | Spec |
|---|---|---|
| **instrument** | DFMA failure rows, RevisionLog, BOM, plan table, legend, attempt timeline, compact issue list | row height 32px (`h-8`), cell `py-1.5 px-3`, `text-xs` mono/tabular where data, hairline row rules, header = micro-label style |
| **gallery** | RenderSheet, PartCards, NegotiationCards, register rows | padding `p-5`-`p-6`, grid gaps `gap-6`, sheet quadrant margins ≥24px, generous line-height |

Spacing base unit: **4px** (Tailwind scale); every gap a multiple. Symmetrical padding.

## §11 Component state patterns

| State | Treatment |
|---|---|
| table-row hover | `wash-hover` background; no border change |
| card hover (linked cards, register rows) | border `stroke-object` → `stroke-strong`; register row also `wash-hover`; no lift/shadow |
| focus-visible (everything) | 2px `ring` (trace) with 2px offset; visible on chrome AND on sheet |
| tab active / inactive | active: `foreground` text + 2px `trace` underline; inactive: `ink-tertiary`, hover → `ink-secondary` |
| toggle-group selected (CLEAN\|WIREFRAME) | group well = `surface-inset`; selected segment = `card` bg + `stroke-object` border + `foreground` text; unselected = `ink-tertiary` |
| skeleton | `surface-inset` base pulsing to `card`; sheet-shaped skeletons keep sheet dimensions but use chrome tokens (the sheet only exists once real) |
| lightbox | `scrim` backdrop; content on `sheet` with `radius-sheet` |
| balloon number | 22px circle, 1.5px border in `foreground`/40%, mono `text-xs` tabular |
| EmptyQuadrant | dashed `sheet-rule` inset border, micro-label "AWAITING RENDER" in `sheet-ink-soft` |
| degraded/error panel | `surface-inset` well, `fail-line` left rule 2px, `fail-ink` micro-label + `ink-secondary` prose; inline, never a blank screen |

**Radius**: `--radius` 0.5rem → chips/inputs `rounded-sm`, buttons `rounded-md`, cards
`rounded-lg`, sheets `rounded-sheet` (2px, near-sharp: paper). Never larger than lg in v1.

**Motion**: 150ms ease-out micro (hover/focus), 200-250ms panels/dialog; no spring/bounce.

## §12 Accessibility & QA contract

- Every status is text + `data-state`; every agent chip `data-agent`; color never sole channel.
- All text tokens measured ≥4.5:1 AA on their surfaces in both themes (§3 values, §7 table);
  `ink-faint` (3.36 dark / 3.78 light) is reserved for disabled/placeholder only.
- Keep semantic DOM + existing `data-testid` conventions; verdicts mirrored as attributes.
- Focus ring on every interactive element (QA fleet tabs; engineers arrow through views).

## §13 Noted, not tokened / deferred

- **Projection arrangement** (third-angle default / first-angle option) is a component-level
  layout toggle on RenderSheet; no tokens involved (locked decision; recorded here so no
  future pass invents "projection tokens").
- `chart-1..5` set to a graphite ramp as placeholders: no charts in v1; retune when one exists.
- Print styles, reduced-motion variants, and theatrical amplification (sheet glow bloom,
  stamp animations) → a later theatrical-amplification pass on the
  assembled whole. These tokens are the substrate that pass works within.
