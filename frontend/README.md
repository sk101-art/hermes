# HERMES Frontend

The frontend is a lightweight Vite application for the existing local-first HERMES FastAPI service. It intentionally treats the backend as the source of truth and reads from the implemented routes rather than recreating intelligence logic in the browser.

## Start locally

From the repository root, start the existing API on its configured local port, normally `127.0.0.1:8765`. Then run:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL printed in the terminal. The frontend defaults to `http://127.0.0.1:8765` for the API. To point it at another local API URL, set it in the browser console once:

```js
localStorage.setItem('hermes_api_url', 'http://127.0.0.1:8765')
```

## Implemented experience

The application includes Today, Morning Briefing, Search, My Projects, Saved Library, Changes, Runtime & Source Health, and Story Detail views. It supports loading, empty, offline, and degraded states, responsive navigation, live API-backed cards and tables, story drill-down, search filters, and a local-only star affordance when the current API exposes no mutation route.

The visual system uses restrained translucent materials, calm blue accenting, progressive disclosure, semantic verification/maturity/risk treatments, responsive desktop-first layout, direct press feedback, and reduced-motion/reduced-transparency/high-contrast media queries. Ranking values are not shown as confidence percentages, and saved snapshots remain visually distinct from current state.

## Build verification

```bash
npm run build
```

The production build output is written to `frontend/dist`.
