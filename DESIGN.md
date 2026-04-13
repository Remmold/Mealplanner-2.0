# Mealplanner 2.0 — Design & Progress Document

> Living document. Updated continuously as the project evolves. Intended as both
> an architectural reference and a presentation companion for the final school demo.

---

## 1. Vision

A full-stack meal planning application that turns a curated ingredient pantry
into concrete, cookable recipes and an organised, store-ready shopping list —
with AI assistance for recipe generation and pantry curation.

**Core user flows**
1. **Build a recipe** manually from a curated ingredient picker, or generate one
   with an LLM from a natural-language prompt.
2. **See real-time nutrition** aggregated from USDA nutrient data as ingredients
   are added and quantities adjusted.
3. **Plan meals** by selecting saved recipes and portions.
4. **Generate a shopping list** that consolidates ingredients across recipes,
   converts units where appropriate (eggs → pcs, milk → dl, flour → dl), and
   orders items in the user's chosen store layout.

---

## 2. Architecture

```
┌─────────────────┐   HTTP    ┌──────────────────┐
│ React + Vite    │ ────────▶ │ FastAPI          │
│ (frontend)      │ ◀──────── │ (backend)        │
└─────────────────┘           └────┬──────┬──────┘
                                   │      │
                          ┌────────▼─┐  ┌─▼──────────┐
                          │ DuckDB   │  │ SQLite     │
                          │ (read)   │  │ (user data)│
                          └──────────┘  └────────────┘
                                ▲
                                │ dbt seeds + models
                                │
                          ┌─────┴──────┐
                          │ dlt        │ Open Food Facts dump
                          │ pipelines  │ USDA nutrition
                          └────────────┘
```

### 2.1 Storage split

| Store      | Role                                                              | Contents                                                                 |
|------------|-------------------------------------------------------------------|--------------------------------------------------------------------------|
| **DuckDB** | Read-heavy analytical store, populated by dlt + dbt               | OFF products, USDA ingredients, curated `common_ingredients` (dbt seed)  |
| **SQLite** | User/transactional data, written by the API                       | households, recipes, recipe_ingredients, pantry_ingredients, ingredient_units, store_layout |

This split means dbt rebuilds never touch user data, and the API never corrupts
the analytical side. The "curated ingredients" the app sees at runtime is the
**UNION** of the dbt seed and the user pantry, with the user pantry winning on
conflict (so users can override naming/categorisation).

### 2.2 Backend (Python 3.11+)

- **FastAPI** for the HTTP API, **Uvicorn** for serving.
- **DuckDB** in-process analytics database.
- **dlt** (data load tool) pulls Open Food Facts + USDA dumps on a daily check.
- **dbt-duckdb** handles staging → marts, plus the `common_ingredients` seed.
- **PydanticAI** wraps OpenAI for structured recipe generation and pantry
  curation (gpt-4o by default, configurable via `OPENAI_RECIPE_MODEL`).

### 2.3 Frontend (TypeScript)

- **React 19** + **Vite**, branded as **Hearth**.
- **Warm-kitchen design system** — custom CSS in `src/styles.css` with design
  tokens (cream `#faf6f1`, sage `#4a6b46`, terracotta `#c8633e`, warm taupe
  ink). Fraunces serif headlines + Inter body, soft shadows, rounded cards.
  No CSS framework — keeps the bundle lean and styling consistent across
  components via semantic classes (`.card`, `.btn-primary`, `.chip`,
  `.shop-cat-header`, etc.).
- Sticky header with brand mark + tab nav; max-width content well; subtle
  gradient backdrop. Each view leads with a hero strip explaining what it does.
- No state manager — `useState` + fetch. Simple and fast to demo.

---

## 3. Data model

### 3.1 SQLite (user data)

```sql
households (id PK, name, created_at)

recipes (id PK, household_id FK, name, instructions JSON,
         servings INTEGER DEFAULT 4, created_at, updated_at)

recipe_ingredients (id PK, recipe_id FK, fdc_id, quantity_g,
                    UNIQUE(recipe_id, fdc_id))

pantry_ingredients (fdc_id PK, simple_name, category, subcategory,
                    created_at)

ingredient_units (fdc_id PK, display_unit, grams_per_unit, round_step)

store_layout (household_id FK, category, sort_index,
              PRIMARY KEY (household_id, category))

meal_plans (id PK, household_id FK, name, start_date,
            created_at, updated_at)

meal_plan_entries (id PK, meal_plan_id FK ON DELETE CASCADE,
                   recipe_id FK, plan_date, slot, portions)

chat_sessions (id PK, household_id FK, title, message_history JSON,
               created_at, updated_at)

chat_messages (id PK, session_id FK ON DELETE CASCADE, role, content,
               tool_calls JSON, created_at)
```

Key design choices:
- **`fdc_id` as the ingredient identity.** Every recipe ingredient points back
  to a USDA Food Data Central row, so nutrition lookup is always deterministic.
- **Per-household store layout.** A family's grocery store has a specific aisle
  order; the shopping list sorts items into that order.
- **Unit overrides live separately** from the recipe. A recipe stores grams;
  the shopping list converts to human units at render time using `ingredient_units`.

### 3.2 DuckDB (analytical)

- `usda.ingredients` (~7.8k rows) — full USDA SR Legacy nutrition database.
- `main.common_ingredients` (86 rows) — hand-curated "blessed" pantry, a dbt
  seed (`transform/seeds/common_ingredients.csv`).
- `main_marts.dim_products` — Open Food Facts products with cleaned
  category/subcategory labels.

---

## 4. Features implemented

### 4.1 Product database (OFF)
- Ingested ~50k products via dlt, transformed with dbt.
- `/products` endpoint with search, category/subcategory filters, nutriscore,
  dietary flags, sorting, pagination.

### 4.2 Curated ingredient picker
- `/ingredients` returns the union of dbt seed + user pantry, joined with USDA
  nutrition per 100g.
- Real-time nutrition aggregation as items are added/resized.

### 4.3 Recipe CRUD
- SQLite-persisted, scoped to a default single household (multi-household-ready
  schema).
- Create / read / update / delete. Includes servings, instructions, ingredient
  list with per-ingredient grams.

### 4.4 AI recipe generation
- `POST /recipes/generate` with a natural-language prompt.
- PydanticAI agent uses a `search_ingredients` tool that queries the curated
  pantry first, falling back to the full USDA database (~8k items) when curated
  has no match.
- System prompt enforces 8–15 ingredients, 6–12 detailed steps with technique,
  temperature, timing, sensory cues.
- Returns structured `{name, ingredients[{fdc_id, name, quantity_g}], instructions[]}`.

### 4.5 Pantry expansion
- `POST /pantry` promotes any USDA row into the curated pantry with a clean
  display name and category.
- `GET /ingredients/usda-search?q=` — fuzzy search the full USDA database.
- **One-shot LLM bootstrap script** (`scripts/expand_pantry.py`):
  interleaves across food groups, asks the LLM to pick good pantry candidates
  and produce clean names. Grew the curated set from **86 → 819 ingredients**
  in one run. Idempotent (uses `ON CONFLICT DO NOTHING`).

### 4.6 AI weekly plan generator
- `POST /meal-plans/generate` takes a free-text brief + start_date + slots
  (any combination of breakfast/lunch/dinner) + days (1–14) + servings.
- **Two-stage pipeline:** a "planner" PydanticAI agent receives the brief and
  the household's existing recipe list; it returns structured `_PlannedMeal`
  decisions per slot, choosing between `use_recipe_id` (pick an existing
  recipe) or `new_recipe_prompt` (a description for a fresh recipe). For every
  "new" decision, the existing `generate_recipe()` is invoked to actually
  create and persist the recipe. Identical prompts within a single plan are
  cached so the same dish doesn't get generated twice.
- Result is a fully-saved meal plan; the editor loads it immediately.
- Trade-off: stage-1 + N stage-2 calls is many round-trips and 30–60s typical.
  Worth it for the demo since the output looks magical.

### 4.7 Conversational agent (chat)
- `POST /chat/sessions/{id}/messages` runs a tool-equipped PydanticAI agent.
  Tools live in `api/agent_tools.py` and wrap every meaningful operation:
  list/get/update/delete recipe, generate-and-save recipe, list/get/create/
  update/delete meal plan and entries, search pantry, search USDA, household
  summary. Each tool returns a compact human-readable string for the LLM and
  pushes an `AuditEvent` for the UI.
- **Persistence:** PydanticAI's `ModelMessagesTypeAdapter` serialises the full
  message history (including tool calls and returns) as JSON on
  `chat_sessions.message_history`. Sessions resume across page reloads.
- **Audit-driven UI feedback:** the API returns `audit: AuditEvent[]` along
  with the assistant reply. The chat panel shows them as honey-tinted cards
  ("Renamed 'Pasta' → 'Lemon-Garlic Spaghetti'"), and dispatches a global
  `dataChanged()` event so other views refetch their data automatically.
- **System prompt** instructs the agent to: always look things up before
  claiming facts, never invent IDs, actually do what the user asks (don't
  just describe), confirm destructive ops.

### 4.8 Shopping list generation
- `POST /shopping-lists/generate` takes `[{recipe_id, portions}]`, scales by
  `portions / recipe.servings`, consolidates ingredients by `fdc_id`, applies
  unit conversions (eggs → pcs, milk/cream/oil/soy → dl, flour/rice/sugar →
  dl, onions/carrots/potatoes → pcs, garlic → cloves), rounds up sensibly
  (never buy too little), and groups items by category in the household's
  store-layout order.
- `GET|PUT /shopping-lists/store-layout` — read/edit the household's category
  order with a drag-free up/down UI.
- Fallback for un-promoted USDA ids (e.g. LLM used something not in pantry):
  the generator still groups them correctly via `food_group → category` mapping.

---

## 5. Key engineering decisions

### Why split DuckDB / SQLite
- DuckDB is read-optimised analytical engine, great for joins over the USDA
  + OFF datasets. Embedding writes in the same file would mean locking
  conflicts with dbt and hurt demo reliability.
- SQLite handles small, user-specific transactional data well and keeps the
  API's read path simple (`with get_recipe_db() as conn`).

### Why `fdc_id` everywhere
- USDA's Food Data Central IDs are stable, universal, and carry nutrition
  data for free. The alternative — storing free-text ingredient names — would
  force a normalisation step on every read. Using `fdc_id` means the shopping
  list, nutrition aggregator, and unit converter all share one key.

### Why a dbt seed *and* a SQLite pantry (the hybrid curated list)
- The dbt seed is version-controlled, reproducible, and ships with the
  project.
- The pantry is user-mutable: promotions, renames, deletes don't survive a
  dbt rebuild but persist across API restarts.
- UNION at read time gives the app a single logical curated list while
  keeping writes clean.

### Unit conversion strategy
- Grams stored in the DB (uniform, machine-friendly).
- Display units (`dl`, `pcs`, `clove`) applied at shopping-list render time
  from a sparse override table. Ingredients without an override stay in grams.
- Round *up* to a sensible step (whole eggs, 0.5 dl, 10 g) so users always
  buy enough.

### Why let the LLM search USDA too
- 86 curated ingredients is a demo-sized list. Letting `search_ingredients`
  fall back to USDA unblocks richer recipes without forcing the user to
  pre-populate the pantry.
- Un-promoted USDA ids are still valid recipe ingredients — nutrition works,
  shopping-list grouping works (via `food_group` mapping). Promotion is for
  *display polish*, not for functional correctness.

---

## 6. Roadmap

### Near-term polish
- [ ] Pantry edit UI: rename items (many LLM-seeded items kept "Raw" suffix),
      re-categorise, delete.
- [ ] Error handling polish on recipe generation (currently a generic 500 if
      OpenAI is down).
- [ ] Expand `ingredient_units` seed list to cover the full 819-item pantry.

### Feature expansion
- [ ] Multi-household: schema already supports it; wire a household picker UI
      + auth.
- [ ] Named store layouts per household ("Home ICA", "Weekend Lidl") and a
      picker on the shopping screen.
- [ ] Auto-promote USDA ingredients to pantry on recipe save (currently manual).

### Data / infra
- [ ] Migrate SQLite to Supabase Postgres for real multi-user deployments.
- [ ] Add pytest coverage (no tests yet; testing scaffold exists in dev deps).
- [ ] Add DB migration framework (currently lightweight `PRAGMA table_info`
      checks in `init_db`).

### UX / presentation
- [ ] Mobile-friendly shopping list (big tap targets, swipe-to-check).
- [ ] Print / PDF export of a generated shopping list.
- [ ] Recipe image via DALL·E or a stock fallback.
- [ ] Dashboard / landing view on first open (today's meals, this week
      at a glance).
- [ ] Empty-state illustrations (instead of italic "No X yet" text).

---

## 7. Progress log

> Newest entries on top. Keep each entry short — one or two lines on *what
> changed* and *why*. Leave dates approximate when unsure.

### 2026-04 — Conversational agent + AI weekly plan generator
Two big AI features ship together. (1) `POST /meal-plans/generate` — a
two-stage pipeline: planner agent decides what to cook each day (reusing
saved recipes when sensible, prompting for new ones otherwise), then we
sequentially call the recipe generator for each missing dish and assemble
the plan. New "✦ Generate week with AI" button on the meal plan tab
opens a modal: brief, start date, days, servings, slot pickers. (2) Global
chat assistant with full tool access — `api/agent_tools.py` exposes
recipe/plan/pantry CRUD as PydanticAI tools; `api/chat.py` persists
conversation history per session via `ModelMessagesTypeAdapter` so chats
resume across reloads. Each turn returns an audit log of mutations; the chat
panel renders them as honey-tinted action cards and dispatches a global
`dataChanged()` event so MealPlan and RecipeBuilder auto-refresh. Floating
terracotta launcher in the bottom-right opens the slide-out drawer with
typing indicator, suggestion chips, session list.

### 2026-04 — Frontend rebrand: "Hearth" warm-kitchen design system
Full visual overhaul. App rebranded "Hearth — your kitchen, planned". New
`styles.css` design system with cream/sage/terracotta palette, Fraunces serif
headlines + Inter body, semantic component classes (cards, pills, chips,
buttons, week-grid, shop-row, modal). Sticky header with brand mark + pill
nav, hero strip on each view, soft shadows and rounded cards throughout.
Every component (RecipeBuilder, MealPlan, ShoppingList, ProductList,
ProductDetail, Categories, NutritionAggregator) rewritten to use the system —
no more inline styles.

### 2026-04 — Meal plan (week view) + one-click shopping list
New `meal_plans` + `meal_plan_entries` tables and full CRUD. Frontend week
grid: 7 days × breakfast/lunch/dinner cells, click "+" to drop in any saved
recipe with its default servings, edit portions per entry. Plans list across
the top (create / switch / delete). "Shopping List" button on a saved plan
calls `POST /meal-plans/{id}/shopping-list` which sums portions per recipe
and reuses the existing consolidator — entries for the same recipe across
multiple days collapse into one shopping-list line.

### 2026-04 — LLM pantry bootstrap (86 → 819)
Built `scripts/expand_pantry.py`: pre-filters USDA for branded/prepared junk,
interleaves across food groups, asks the LLM to accept/reject with clean
display names. Ran twice to work around OpenAI TPM limits. Result: 733 pantry
rows plus 86 dbt-seeded = 819 curated ingredients spanning all 12 categories.

### 2026-04 — Hybrid curated pantry
Made the curated ingredient list a UNION of the dbt seed and a new SQLite
`pantry_ingredients` table. Users can promote any of ~8k USDA rows into their
pantry without touching the dbt seed. Added USDA search endpoint + "+ Find
more (USDA)" panel in the recipe builder. LLM's `search_ingredients` tool now
falls back to USDA when curated has no hits.

### 2026-04 — Shopping list end-to-end
Added `servings` column to recipes. New tables `ingredient_units` and
`store_layout`. `POST /shopping-lists/generate` takes
`[{recipe_id, portions}]`, scales, consolidates, unit-converts, orders by
household store layout. New Shopping tab with recipe picker, portions input,
per-category grouped list, and inline layout editor.

### 2026-04 — Richer recipe generation
Bumped default model to gpt-4o, rewrote the recipe-gen system prompt to
require 8–15 ingredients, 6–12 detailed steps with technique / temperature /
timing / sensory cues. Persisted `instructions` on recipes (was ephemeral).
Editable instructions UI in RecipeBuilder.

### 2026-04 — Recipe AI generation shipped
PydanticAI agent with `search_ingredients` tool calls OpenAI, returns
structured recipe with fdc_id-based ingredients.

### 2026-03 — Recipe builder + USDA picker
Curated 86 common ingredients via dbt seed. React recipe builder with
category filter, search, real-time nutrition aggregation.

### 2026-02 — Product database
dlt pipeline ingesting Open Food Facts dump into DuckDB. dbt staging/marts
models produce `dim_products` with cleaned categories, subcategories, dietary
flags, quality scores.

---

## 8. Things to say during the demo

*(Talking points — not code. Used to rehearse.)*

1. **Open with the problem.** "Meal planning apps are either recipe silos or
   shopping-list silos. I wanted one pipeline from ingredient → recipe →
   portions → store-ordered shopping list, with nutrition that's actually
   correct."
2. **Show the data layering.** 50k OFF products for discovery, 8k USDA items
   for accurate nutrition, 819 curated pantry for the picker — all unified
   by `fdc_id`.
3. **Demo the AI generation.** Prompt something like "Thai red curry for 4".
   Watch the system return 12 ingredients + 8 detailed steps — then save it,
   scale portions, generate a shopping list.
4. **Demo the shopping list.** Show consolidation (same onion across 3
   recipes → one line), unit conversion (100g milk → 1 dl, 50g egg → 1 pcs),
   and the store-layout editor reordering categories live.
5. **Talk architecture.** The DuckDB/SQLite split. Why `fdc_id`. The hybrid
   pantry and why dbt-seed-plus-UNION beats a single mutable table.
6. **Talk the LLM bootstrap.** 86 → 819 in one script. This is the kind of
   task where an LLM is dramatically better than a regex — subjective
   "should this be in a pantry?" calls across 2000 candidates.
7. **Close on what's next.** Meal plans, Supabase, mobile shopping view.
