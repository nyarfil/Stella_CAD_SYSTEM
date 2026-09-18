# AI-CAD Frontend: "watch the machine think"

Read-only localhost window into `../projects/`.
The filesystem is the API: this app never imports harness code and never writes.

## Launch

```bash
npm install   # first time only
npm run dev   # → http://localhost:5199
```

The dev server is pinned to **port 5199** (`strictPort`).
A strict dedicated port keeps the launch and browser-QA URLs stable
regardless of what else is running locally.
Pinned in three places kept in sync: `vite.config.ts`
(`server.port` / `preview.port`), the `dev` script above, and this line.

## Stack & rationale

**Vite 8 + React 19 + TypeScript + Tailwind CSS v4 + shadcn/ui (Radix) + react-router.**

1. React has the deepest component ecosystem of the candidates:
   run documents render via react-markdown,
   and the same ecosystem carries mature libraries for editable markdown (TipTap/Milkdown)
   and 3D rendering (three.js via react-three-fiber) should the app ever need them.
2. shadcn/ui is copy-in (components live in this repo, fully restylable)
   on Radix a11y primitives;
   Tailwind v4 is its load-bearing substrate,
   a 2025 CSS-first engine whose `@theme` tokens ARE the CSS-variable design-token layer,
   not the legacy Tailwind of old.
3. Vite middleware (`plugins/projects-api.ts`) serves the read-only fs API in-process:
   one command, no second server,
   trivially portable to a standalone file server when static hosting matters.

## Directory map

```
frontend/
├── plugins/projects-api.ts   # read-only fs API (the route list lives in this file's header comment)
├── src/
│   ├── components/
│   │   ├── activity/             # live agent-activity waterfall (ActivityStrip)
│   │   ├── layout/AppShell.tsx   # sidebar + main shell
│   │   ├── negotiation/          # negotiation event cards
│   │   ├── sheet/                # drawing-sheet chrome (render sheet, score badge, verdict stamp)
│   │   └── ui/                   # shadcn components (owned, restylable)
│   ├── features/assembly/        # assembly view + DFA panel
│   ├── features/parts/           # per-part detail view
│   ├── features/projects/        # ProjectPicker + ProjectDashboard (live views)
│   ├── lib/api.ts                # typed client for the fs API
│   ├── lib/model.ts              # project/part domain model the views consume
│   ├── lib/parsers/              # run-artifact parsers; fixture-backed tests encode the contract
│   ├── lib/utils.ts              # cn() helper (shadcn)
│   └── index.css                 # Tailwind v4 + OKLCH token system (CSS variables)
└── vite.config.ts
```

## Design-system handoff (build agents READ THIS)

Before building new surfaces:

1. The design system lives in `.interface-design/system.md`,
   and every token decision is **resolved there**:
   IBM Plex Sans + IBM Plex Mono are the canonical fonts,
   and the tokens are LIVE in `src/index.css` (Tailwind v4 OKLCH variables),
   materialized from `system.md`.
   Read `system.md` before restyling anything.
2. Data-dense surfaces (parts grid, reports) prioritize the token/elevation system;
   drama surfaces (negotiation cards, render heroes) may amplify aesthetically on top of it.
3. A stock-shadcn look is a failure mode:
   this app must not read as a generic template.
   Restyle via the token layer, never inline.
4. Testability: keep semantic DOM + `data-testid` attributes
   (existing convention: `sidebar`, `main`, `project-picker`, `project-link-<name>`).
   Browser QA agents drive this app.
