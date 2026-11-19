# Screens

React 19 + Vite + Tailwind. Two bundles:

- `index.html` → `src/app/`: the consultant app (dark).
- `client.html` → `src/client/`: client pages (light, small, in the practice's colours).

```bash
npm install
npx vite build      # output in dist/, served by the backend
npm run dev         # live reload on :5173, API proxied to :8765 (run scripts/qa_server.py first)
```

## Where things are

| Path | What |
|---|---|
| `src/brand.js` | Product name. The only place it lives on the screen side. |
| `src/index.css`, `tailwind.config.js` | Design tokens: ink background, gold for actions, teal for AI, red only for overdue. Manrope and JetBrains Mono, self-hosted. |
| `src/lib/api.js` | `act(name, body)` calls one backend action. `useAct` reads, `useDo` writes. |
| `src/app/components/ui.jsx` | Every shared piece: cards, buttons, chips, sheets, inputs, money input, toasts, skeletons. |
| `src/app/pages/` | One file per screen. |
| `src/app/admin/` | Our Admin screen. Loaded only for staff. |
| `src/client/kit.jsx` | Client-side helpers, slot picker with time zone switch. |
| `src/client/pages/` | Lead form, booking, client file, invoice, portal. |

## Rules

- Every screen must work at 390 px wide. The crawl checks this.
- Money is in paise from the server. Format with `inr()` from `src/lib/format.js`.
- Dates always through `date()` / `dt()`, never raw ISO.
- Teal only for AI. Gold for the one main action. Red only for overdue or errors.
