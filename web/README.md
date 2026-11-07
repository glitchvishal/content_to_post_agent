# Web UI

A small Next.js (App Router) + TypeScript + Tailwind frontend for the Content-to-Post Agent API. It has no secrets: the OpenAI key stays in the backend `.env`.

## Run

```bash
# 1. Backend (from the repo root, in its own terminal)
uvicorn api.main:app --reload            # http://localhost:8000
# no API key? add LLM_PROVIDER=fake for an offline demo

# 2. Frontend
cd web
cp .env.example .env.local               # optional; defaults work locally
npm install
npm run dev                              # http://localhost:3001
```

Production build: `npm run build && npm start` (port 3001). Type-check: `npm run lint`.

## Environment variables (`web/.env.local`)

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the FastAPI backend. Visible in the browser. |
| `NEXT_PUBLIC_USD_INR` | `88` | Rate used only for the approximate INR cost display. |
| `NEXT_PUBLIC_GITHUB_URL` | the repo | Header link. |

The backend must allow this site's origin: set `ALLOWED_ORIGINS` in the backend `.env` (comma-separated, default `http://localhost:3001,http://localhost:3000`).

## Deploy to Vercel

1. Import the repo in Vercel and set **Root Directory** to `web`.
2. Add `NEXT_PUBLIC_API_URL` pointing at your hosted backend (HTTPS).
3. On the backend, set `ALLOWED_ORIGINS=https://your-app.vercel.app`.

The backend cannot run on Vercel's serverless functions: it keeps runs in memory, uses background threads and long-lived SSE streams. Host it as a container (Render, Railway, Fly.io, a VM) with a single instance. Runs are lost when it restarts.

## How it talks to the API

| Screen | Calls |
|---|---|
| Home `/` | `POST /runs`, then redirects to `/runs/{id}` |
| Run `/runs/{id}` | `GET /runs/{id}`, `GET /runs/{id}/events` (SSE), `POST /runs/{id}/review` |
| Header | `GET /health`, link to `/docs` |

- **Live progress:** the page opens the SSE stream. The stream replays the run's whole history on connect, so a refresh or a finished run still shows the full timeline. If SSE fails twice in a row, it falls back to polling `GET /runs/{id}` every 2 s.
- **Source of truth:** SSE events drive the timeline; the run view (`GET /runs/{id}`) supplies posts, scores and usage.
- **Review:** approve, edit (editable textareas with live character limits) or reject (reason). The optional "Schedule at" picker is local time and is sent as a UTC ISO string.

## Structure

```
app/            pages (home, runs/[id]) and layout
components/     Header, NewRunForm, Timeline, PlanCard, PostCard, ReviewPanel, ScheduledList, UsageCard
lib/api.ts      typed API client
lib/useRun.ts   SSE + polling hook
lib/timeline.ts turns events into progress steps
```

## Screenshots

_Add screenshots here: `docs/web-home.png`, `docs/web-run.png`._
