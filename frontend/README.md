# Screens

React 19 + Vite + Tailwind + TanStack Query. Two bundles, served by the backend from the same origin:

- `index.html` → `src/app/`: the consultant app (dark).
- `client.html` → `src/client/`: client pages (light, small, in the practice's colours). It never loads the editor or the app's code.

```bash
npm ci
npm run dev        # live reload on :5173, API proxied to :8765 (run scripts/qa_server.py first)
npm run lint       # ESLint (hooks rules, undefined names)
npm run build      # output in dist/, served by the backend
npm run check      # lint + build (CI)
```

## Layout

```
src/
  shared/                 used by both bundles
    api/                  client.js (fetch + errors), hooks.js (useAct / useDo), index.js
    lib/                  format.js (money, dates), files.js (uploads, CSV, downloads)
    styles/index.css      design tokens and base styles
    brand.js              product name (the only place it lives on the screen side)
  app/                    consultant app
    main.jsx              entry: providers + routes, nothing else
    providers.jsx         React Query, router, toasts
    router.jsx            every route in one table, each screen code-split
    components/           RequireAuth (login/onboarding guard), ErrorBoundary
    layout/               AppShell (nav, top bar), Chat ("Ask or tell")
    ui/                   design system: cards, buttons, inputs, sheets, toasts, RichText
    widgets/              cross-feature pieces (budget bar, log time, invoice time, client task)
    features/<area>/      one folder per product area: projects, inbox, payments, time, ...
  client/                 client bundle
    main.jsx              client routes (forms, booking, file, invoice, portal, task)
    lib/kit.jsx           client helpers, slot picker with time-zone switch
    pages/                one file per client page type
    styles/client.css
```

Imports use the `@/` alias for `src/` (configured in `vite.config.js` and `jsconfig.json`).
A feature imports from `shared/`, `app/ui`, `app/widgets` and `app/layout`, never from another feature.

## How screens talk to the backend

Every business call is one action: `act("projects.create", body)` → `POST /api/a/projects.create`.

- `useAct(name, body)` reads (query key `[name, body]`).
- `useDo(name, { invalidate })` writes and refreshes every query whose action starts with the given prefixes
  (by default the action's own area, e.g. `projects`).
- Errors arrive as `ApiError` with a stable `code`, a plain `message` and the server's `requestId`.
  A 401 sends the user to `/login?next=<where they were>`.

## Rules

- Every screen must work at 390 px wide. `node ../scripts/crawl.mjs` checks this.
- Money is in paise from the server. Format with `inr()` from `@/shared/lib/format`.
- Dates always through `date()` / `dt()`, never raw ISO.
- Teal only for AI. Gold for the one main action. Red only for overdue or errors.
