# Hearth — Mealplanner 2.0

Hearth is a household meal-planning web app. A household plans dinners on a shared
calendar, keeps a recipe library, a pantry and a profile, and gets help from an AI
kitchen assistant that can read and — with the user's approval — modify all of it.

The assistant's toolbox is exposed two ways: **in-process** and over the
**Model Context Protocol (MCP)**, so any MCP-compatible client (Claude, ChatGPT,
other agents) can drive it with the user's Supabase login.

> The MCP integration is the subject of a degree thesis: the *same* shared tool core
> is reached both in-process and over MCP, so the two integration mechanisms can be
> compared directly, with the toolset held constant.

---

## Features

- **Recipe library** — save, search, and LLM-generate recipes with USDA-backed nutrition.
- **Shared calendar** — plan dinners by date / slot / portions; a week wizard builds a coherent menu.
- **Pantry & shopping list** — household staples shape an auto-generated shopping list.
- **Household profile** — dietary needs, likes/dislikes, allergies, cuisines, cook-time and batch-cook preferences.
- **Explore** — a public recipe pool; like and import community + starter recipes.
- **AI assistant** — natural-language chat that calls tools to manage all of the above. Every write is a *proposal* the user accepts or rejects; nothing auto-mutates.
- **MCP server** — the same toolbox over Streamable HTTP, reachable by any MCP client with a Supabase JWT.
- **Capped AI** — per-household monthly credits plus a global spend kill-switch.

---

## Architecture

```
React SPA ──HTTP──▶ FastAPI ──asyncpg (RLS)──▶ Supabase Postgres
                      │
                      ├─ PydanticAI chat agent
                      │     ├─ in-process tools  (api/agent_tools.py)   ◀ default
                      │     └─ MCP client ──HTTP──▶ MCP server (api/mcp_server.py)
                      │
                      └─ shared tool core (api/agent_core/tools.py)   ◀ single source of truth
```

- **Shared tool core** (`api/agent_core/tools.py`) — pure, transport-agnostic tool functions; their docstrings are the canonical tool descriptions.
- **Two adapters** expose that core identically: in-process (PydanticAI) and the MCP server (FastMCP, Streamable HTTP, per-request Supabase JWT). Pick one with the `HEARTH_AGENT_TRANSPORT` env var.
- **Human-in-the-loop writes** — tools return proposals buffered as `pending_actions`; a per-kind executor applies them only after the user accepts.
- **Identity & isolation** — every request carries a Supabase JWT; Postgres Row-Level Security (RLS) scopes all data to the caller's household.

---

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite; `@supabase/supabase-js`; `lucide-react`; in-house primitive UI library |
| Backend | Python 3.11+, FastAPI, Uvicorn; PydanticAI (OpenAI); MCP SDK (FastMCP); asyncpg; PyJWT |
| Database | Supabase — Postgres + Auth + Row-Level Security |
| Data | USDA FoodData Central + Open Food Facts; DuckDB + dlt + dbt for the product catalogue |
| Tooling | uv, ruff, pytest |

---

## Project structure

```
Mealplanner-2.0/
├── backend/
│   ├── api/                     # FastAPI application
│   │   ├── main.py              # app entry — routers + mounted MCP server (/mcp)
│   │   ├── agent_core/          # shared, transport-agnostic tool core
│   │   │   ├── tools.py         #   the 22 tool implementations (single source of truth)
│   │   │   └── context.py
│   │   ├── agent_tools.py       # in-process tool adapter (PydanticAI)
│   │   ├── mcp_server.py        # MCP server adapter (FastMCP, Streamable HTTP)
│   │   ├── chat.py              # chat agent orchestration + sessions
│   │   ├── pending_actions.py   # propose → accept → execute pipeline
│   │   ├── recipe_gen.py        # LLM recipe generation (structured output)
│   │   ├── public_pool.py       # Explore public recipe pool
│   │   ├── credits.py           # capped-AI credit ledger
│   │   ├── db.py / auth.py       # asyncpg pool (RLS) + Supabase JWT auth
│   │   └── …                    # recipes, meals, shopping, staples, profile, households, …
│   ├── scripts/                 # seeding / data-pipeline scripts
│   ├── seeds/                   # committed seed data (recipes, USDA aliases)
│   ├── pipeline/                # legacy Open Food Facts → DuckDB ingestion
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                    # React + Vite single-page app
│   └── src/
│       ├── components/          # feature screens + ui/ primitive library
│       ├── auth/                # Supabase auth + onboarding
│       └── lib/                 # Supabase client + API helpers
├── supabase/
│   ├── config.toml
│   └── migrations/              # Postgres schema + RLS migrations
└── README.md
```

---

## Getting started

### Prerequisites

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/)
- **Node 20+** and npm (required by Vite 8)
- A **Supabase** project and the [Supabase CLI](https://supabase.com/docs/guides/cli) (for migrations)
- An **OpenAI** API key

### 1. Database

Apply the schema + RLS migrations to your linked Supabase project:

```bash
supabase db push        # applies supabase/migrations/
```

### 2. Backend

```bash
cd backend
uv sync
cp .env.example .env     # fill in your Supabase + OpenAI values
uv run uvicorn api.main:app --reload --port 8000
```

- API: <http://127.0.0.1:8000> — health at `/health`, interactive docs at `/docs`.
- The MCP server is mounted at **`/mcp`**.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env     # VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
npm run dev
```

App: <http://localhost:5173>.

### Routing the assistant through MCP

The chat agent uses in-process tools by default. To make it reach the *same* tools
over the MCP server instead:

```bash
HEARTH_AGENT_TRANSPORT=mcp uv run uvicorn api.main:app --port 8000
```

Any MCP client can also connect directly to `http://127.0.0.1:8000/mcp/` with an
`Authorization: Bearer <supabase-jwt>` header.

---

## Data & seeding

The ingredient catalogue is USDA-based; the (dev-only) product browser data comes
from Open Food Facts. Seeding/pipeline scripts live in `backend/scripts/` — run them
from `backend/`, e.g. `uv run python -m scripts.seed_public_pool`:

| Script | Purpose |
|---|---|
| `build_starter_corpus.py`, `seed_public_pool.py` | Build + load the starter recipe pool |
| `extract_swedish_ingredients.py` → `build_amcoff_pool_seed.py` → `ingest_amcoff_pool.py` | Swedish (amcoff/ICA) recipe pipeline that produces `backend/seeds/` |
| `backfill_amcoff_images.py` | Backfill pool recipe images from source `og:image` |
| `seed_more_units.py` | Seed per-piece display units |

The legacy OFF → DuckDB ingestion lives in `backend/pipeline/`
(`uv run python -m pipeline.run`).

---

## Environment variables (backend)

See [`backend/.env.example`](backend/.env.example) for the full list. The essentials:

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Anon public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role key (backend only — never commit) |
| `SUPABASE_JWT_SECRET` | JWT secret (HS256) used to validate access tokens |
| `DATABASE_URL` | Direct Postgres connection (transaction pooler, port 6543) |
| `OPENAI_API_KEY` | Required for recipe generation, chat, and the planner |
| `OPENAI_RECIPE_MODEL` | LLM model (default `gpt-4o-mini`) |
| `HEARTH_PUBLIC_URL` | Base URL for invite links (the frontend in dev) |
| `HEARTH_AGENT_TRANSPORT` | `in_process` (default) or `mcp` |
| `MONTHLY_CREDIT_GRANT` / `MONTHLY_BUDGET_USD` | Capped-AI tuning (optional) |

**Frontend** (`frontend/.env`): `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.

---

## Conventions

- Frontend UI is composed from the primitives in `frontend/src/components/ui/` — see
  [`frontend/CLAUDE.md`](frontend/CLAUDE.md) for the rules.
- `backend/_*.py`, `backend/query_ing*.py`, and `backend/check_cuisines.py` are
  throwaway scratch scripts, not part of the application.
```
