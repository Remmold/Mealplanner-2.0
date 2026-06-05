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
- **React primitive layer** in `src/components/ui/` (`Button`, `Card`, `Input`,
  `Modal`, `Chip`, `List`, …) wraps those CSS classes. Pages compose from
  primitives (`<Button variant="primary">`) rather than raw classes; visual
  identity lives in the primitive/token, so look changes are one-file edits.
  Conventions are enforced via `frontend/CLAUDE.md`: no inline styles, colors
  only from tokens, icons from `lucide-react` (no emoji glyphs).
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

shopping_list_template (household_id FK, fdc_id, quantity_g, note,
                        created_at, updated_at,
                        PRIMARY KEY (household_id, fdc_id))

meal_plans (id PK, household_id FK, name, start_date,
            created_at, updated_at)

meal_plan_entries (id PK, meal_plan_id FK ON DELETE CASCADE,
                   recipe_id FK, plan_date, slot, portions)

chat_sessions (id PK, household_id FK, title, message_history JSON,
               created_at, updated_at)

chat_messages (id PK, session_id FK ON DELETE CASCADE, role, content,
               tool_calls JSON, created_at)

ingredient_aliases (alias_fdc_id PK, canonical_fdc_id, created_at)

household_profiles (household_id PK, data JSON, updated_at)

pending_actions (id PK, session_id FK ON DELETE CASCADE, household_id FK,
                 kind, summary, params JSON, status, result, created_at,
                 resolved_at)
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

### 4.5 Pantry expansion & deduplication
- `POST /pantry` promotes any USDA row into the curated pantry with a clean
  display name and category.
- `GET /ingredients/usda-search?q=` — fuzzy search the full USDA database.
- **One-shot LLM bootstrap script** (`scripts/expand_pantry.py`):
  interleaves across food groups, asks the LLM to pick good pantry candidates
  and produce clean names. Grew the curated set from **86 → 819 ingredients**
  in one run. Idempotent (uses `ON CONFLICT DO NOTHING`).
- **LLM dedup script** (`scripts/dedup_pantry.py`): batches the pantry by
  category, asks the LLM to group equivalent ids (e.g. "Butter" + "Butter,
  Unsalted") and pick a canonical. Writes to `ingredient_aliases`. Hidden
  from the picker/search, dereferenced at consolidation — so recipes that
  stored different-but-equivalent ids collapse into one shopping-list line.
  First run: 167 aliases → 819 effective pantry shrank to 652.

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

### 4.7 Household profile
- Stored in `household_profiles.data` as JSON. Loose shape (Pydantic model)
  so it evolves without migrations. Fields: `family_size`, `dietary`,
  `allergies`, `dislikes`, `likes`, `cuisines`, `typical_cook_time_min`,
  `batch_cook_preference`, `kitchen_equipment`, `budget_level`, `notes[]`.
- Chat agent has read/write tools (`get_profile`, `update_profile_field`,
  `add_profile_note`) and is instructed to record persistent facts as they
  come up during conversation. Sparse profiles trigger one natural
  discovery question per turn.
- Injected as a "Household profile" block into both the chat system prompt
  and the meal-plan planner brief — every generation respects allergies
  strictly, avoids dislikes, leans into likes/cuisines.

### 4.8 Conversational agent (chat) — with human-in-the-loop writes
- `POST /chat/sessions/{id}/messages` runs a tool-equipped PydanticAI agent.
  Tools live in `api/agent_tools.py`. Read tools (list/get/search/profile)
  run inline; **write tools propose** instead of acting.
- **Propose/accept/reject pipeline:** every `propose_*` tool calls
  `PendingProposer.propose(kind, summary, params)`, which records a row in
  `pending_actions` (status='pending'). The chat endpoint returns the new
  proposals alongside the assistant reply. The UI renders each as a card
  with Accept / Reject buttons; clicking either calls
  `POST /chat/pending/{id}/accept|reject`. Accept dispatches to a per-kind
  executor in `api/pending_actions.py`. Recipe generation is deferred until
  accept — no tokens spent on dishes the user doesn't want.
- **Persistence:** PydanticAI's `ModelMessagesTypeAdapter` serialises the full
  message history (including tool calls and returns) as JSON on
  `chat_sessions.message_history`. Sessions resume across page reloads.
- **Cross-view refresh:** on accept, the UI dispatches `dataChanged("*")`
  so MealPlan, RecipeBuilder, Profile etc. refetch automatically.
- **System prompt** instructs the agent to: always look things up before
  claiming facts, never invent IDs, propose freely (the user is the
  gatekeeper), and not pretend mutations happened ("I added X" →
  "I've put a card above for you to accept").

### 4.9 Shopping list generation
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
- **Household shopping template** (`shopping_list_template` table): baseline
  "we always buy X" items (milk, eggs, …) get merged into every generated
  list before unit conversion, so they sum cleanly with any recipe usage.
  Items carry a `source` tag (`recipe | template | both`). Per-week edits
  on the generated list (skip, alter qty) stay ephemeral on the client —
  only the template editor (`POST|PUT|DELETE /shopping-lists/template`) makes
  permanent changes.

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

### 2026-05 — Frontend primitive layer + end-user cleanup
Extracted a React primitive library (`src/components/ui/`) over the existing CSS
design system, migrated all live views to compose from it, removed inline styles,
and replaced emoji glyphs with `lucide-react` icons. Removed the Products,
Categories and Nutrition tabs from the nav (components kept dormant on disk to
re-add later). Conventions captured in `frontend/CLAUDE.md` so they stay enforced.

### 2026-04 — Shopping list template (household baseline)
New `shopping_list_template` table lets the user pin items they always buy
(e.g. 1 L milk, 6 eggs). Baseline items are merged into every generated
list via a new `include_template` flag on `/shopping-lists/generate` and
`/meal-plans/{id}/shopping-list`, summing against recipe usage so nothing
double-counts. Each list item now carries a `source` tag (`recipe | template
| both`), rendered with a ★ marker and left-border accent. The template
editor (its own sub-view inside the Shopping tab) is the only permanent
path; per-week edits on the generated list — skip item or alter qty —
stay client-side and reset on the next generate.

### 2026-04 — Rich confirmation cards in chat
After the user accepts a `recipe.create` proposal, the chat now shows proof
of the saved recipe instead of just a text line. The accept endpoint returns
a `created: {recipe_id, plan_id, entry_id}` map (per executor) so the UI
knows what to surface. For recipe creates the chat fetches the new recipe
and renders a preview card inside the proposal: thumbnail (or
diagonal-stripe placeholder while the image generates), name, "X servings ·
Y ingredients · Z steps", and a "View →" button. View dispatches a new
global `navigateTo({tab: "recipe", recipe_id})` event the App listens to —
switches to the Recipes tab, auto-selects the recipe via a new
`initialRecipeId` prop on RecipeBuilder, and closes the chat drawer.
Polls the recipe every 5s for up to 60s so the image fills in when ready.

### 2026-04 — Free recipe images (Pollinations.ai)
Added image generation for recipes via Pollinations.ai — a free public
Flux/Stable-Diffusion endpoint, no API key, no cost. New `api/image_gen.py`
builds a food-photography prompt from the recipe name, fetches the JPEG,
saves to `backend/recipe_images/<recipe_id>.jpg`, and writes `image_path`
back on the recipe row. Fires-and-forgets as an asyncio task after every
recipe creation (chat-accepted, weekly-plan generator, manual) so the API
returns immediately and the image lands ~10–20s later. Frontend polls every
5s while viewing an image-less recipe, and has a "↻ Regenerate image"
button on the editor hero. Meal plan recipe picker shows thumbnails for
visual selection. Image column added to `recipes` via lightweight migration.

### 2026-04 — Human-in-the-loop chat writes (propose / accept / reject)
The chat agent no longer mutates the database directly. Every write tool was
renamed `propose_*` and now records to a new `pending_actions` SQLite table
instead of acting. The chat endpoint returns the queued proposals alongside
the assistant reply; the UI renders them as honey-tinted cards with Accept /
Reject buttons (plus an "Accept all" shortcut). New `POST /chat/pending/{id}/
accept|reject` endpoints dispatch by `kind` to executor functions that perform
the actual mutation. Recipe generation is deferred until accept — no tokens
spent on dishes the user doesn't want. Read tools (list/get/search/profile)
still run inline. System prompt updated so the agent stops claiming
mutations happened ("I added X" → "I've put a card above for you to accept").

### 2026-04 — Household profile (context-aware planning)
New `household_profiles` SQLite table (one row, JSON blob) capturing family
size, dietary restrictions, allergies, dislikes/likes, cuisines, cook-time
tolerance, batch-cook preference, kitchen equipment, budget, plus a free-form
`notes` list. `api/profile.py` exposes `GET/PATCH/DELETE /profile`. The chat
agent gets three new tools: `get_profile`, `update_profile_field`,
`add_profile_note` — and the chat system prompt now (a) includes the rendered
profile every turn, (b) tells the agent to record persistent preferences as
they come up without asking permission, (c) switches to discovery-question
mode when the profile is sparse. Meal-plan generator injects the profile into
the planner brief so plans respect dietary/allergy/cuisine constraints. New
frontend "Household" tab with structured editor + notes list — the user can
edit directly, or just let the assistant fill it in through conversation.

### 2026-04 — Per-slot meal plan controls (portions, distinct, disjoint)
Reworked the weekly plan generator input from `{slots, distinct_meals, servings}`
to `{slot_configs: [{slot, portions, distinct_meals}]}`. Each slot now has its
own portions (batch-cook dinners at 2–3x while breakfast stays 1x) and its own
distinct-meals cap. Critically, the planner is instructed — and the server
enforces — that a recipe used in one slot never appears in another (breakfast
and dinner get disjoint recipe sets). Per-slot portions override the planner's
advisory `portions` field at insert time. Frontend modal swaps slot-checkbox
row for a per-slot settings card.

### 2026-04 — Pantry dedup via LLM + alias system
The 819-item pantry (after the bootstrap) contained many near-duplicates:
"Butter" + "Butter, Unsalted", "Milk (whole)" + "Whole Milk", "Flour
(all-purpose)" + "White Flour", etc. New `ingredient_aliases` SQLite table
maps `alias_fdc_id → canonical_fdc_id`; aliases are hidden from the picker
and dereferenced on shopping-list consolidation + recipe name lookup, so
duplicate ids on existing recipes collapse into one shopping-list line
without data loss. `scripts/dedup_pantry.py` batches the pantry by category
to a PydanticAI agent that returns groups of equivalent ids; the canonical
is the lowest id (dbt-seed items). First run found 167 aliases across 92
groups (819 → 652 effective ingredients). Two obviously-wrong groups that
slipped past the LLM (Flank Steak → Pork Chop, Turkey Breast → Chicken
Breast) were removed manually; future runs should get a tighter prompt.

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

---

## 9. Real-product roadmap (post-demo direction)

> Decided 2026-05-25, expanded 2026-05-26. The school demo is a checkpoint,
> not the destination: Hearth becomes a **real, public, monetized product**.
> This section supersedes §6 (Roadmap) as the concrete plan. Implementation
> started 2026-05-26 with the first Supabase migrations.

### 9.1 End-state shape

| Area | Decision |
|---|---|
| **Backend** | FastAPI in a Docker container on an existing **Azure VM**. No Edge Functions rewrite. |
| **Supabase role** | **Postgres + Auth + Storage only.** A free Supabase project is provisioned. |
| **Data topology** | User data + **USDA (~8k rows)** + the `common_ingredients` seed live in **Postgres** (kills the cross-store nutrition join). **OFF is cut from production** (12GB dump, 900MB DuckDB, dlt/dbt pipeline, dormant Products/Categories/Nutrition pages stay in the repo as a data-engineering showcase, not hosted). |
| **Tenant isolation** | Postgres **RLS with the user's Supabase JWT propagated per request.** Tenant-owned: recipes, recipe_ingredients, meal_plans, meal_plan_entries, household_profiles, chat_sessions, chat_messages, pending_actions, store_layout, shopping_list_template, credit_ledger, household_invites. Public-read reference: USDA, curated catalog, `ingredient_aliases`, `ingredient_units`. |
| **Catalog** | **Global, read-only to users.** Recipes can reference any `fdc_id` from the 819 curated or 8k USDA. Promote/dedup/rename are **admin-only**. No per-user pantry table in v1. |
| **Auth** | **Google OAuth + email magic link** (passwordless). |
| **Public URL** | Subdomain of **darkfallcompanion.se** (e.g. `hearth.darkfallcompanion.se`), single origin, Caddy auto-TLS. `/api/*` reverse-proxied to FastAPI; everything else serves the Vite build. |
| **Image storage** | **Supabase Storage** bucket `recipe-images/{household_id}/{recipe_id}.jpg` with per-household RLS. |
| **Monetization** | Free = full manual app. **All AI is gated.** Paid via **usage credits** (Stripe one-time Checkout, not subscriptions). |
| **Mobile** | Responsive web only in v1. PWA + offline shopping list deferred. |
| **Quality bar** | **Critical-path test suite**: RLS isolation, credit-ledger correctness, Stripe webhook idempotency, shopping consolidation. **Supabase CLI migrations** replace `PRAGMA table_info`. |
| **i18n** | **Bilingual SE/EN from day one** via `react-i18next`. UI chrome + AI outputs + emails + legal docs translated; USDA ingredient names stay English in v1. Locale on `household_members.locale`, default from browser. |

### 9.2 Identity & legal entity

- **Enskild firma** for v1 — the operator is the data controller, named in
  PP/ToS. Convert to **Aktiebolag (AB)** once revenue/risk justifies the
  25,000 SEK capital + admin overhead (~50–100k SEK ARR or first employee).
- Public face: `hearth.darkfallcompanion.se` until a dedicated domain is
  bought (one-day DNS swap when revenue covers it).

### 9.3 Multi-user household model

- **Multi-user per household, one active household per user (v1).**
- **`public.households(id, name, created_at, updated_at)`** — tenant root.
  Lives in `public.*` (Supabase's default PostgREST-exposed schema) so any
  future second app in this project can FK to it without a schema rewrite
  (see §9.13).
- **`public.household_members(household_id, user_id, role, locale,
  joined_at)`** — `UNIQUE(user_id)` enforces 1-household-per-user in v1
  (drop the unique later to enable multi-membership without a join-table
  migration). `role` is constrained to `{'owner', 'member'}` via CHECK.
  A partial unique index enforces at most one owner per household. `locale`
  is per-membership (a Swedish user joining an English-speaking household
  may want EN for that household).
- **`public.household_invites(token, household_id, created_by, expires_at,
  used_at, used_by, created_at)`** — cryptographically-random URL-safe
  tokens (32 bytes), default 7-day expiry, consumed in a service-role
  transaction.
- **Invite flow:** owner clicks Invite → server inserts a row with a fresh
  token + 7-day expiry → returns
  `https://hearth.darkfallcompanion.se/join/<token>` → owner shares freely.
  Recipient clicks → auth (or signup) → server consumes the token
  atomically (validate not expired/used → mark used → insert
  `household_members` with role `member`).
- **RBAC (owner + member):**
  - **Owner-only:** kick another member, transfer ownership, delete
    household.
  - **Member:** everything else (create recipes, plans, invites, edit
    profile, generate AI).
  - **Last member leaves auto-deletes the household** and cascades all
    tenant resources.
- **Helpers** (`public.is_member_of(uuid)`, `public.is_household_owner(uuid)`,
  `public.user_household_ids()`) are `SECURITY DEFINER` so they bypass RLS
  on `household_members` when called from RLS policies — without this, a
  policy that queries `household_members` would recurse into its own RLS.

### 9.4 Onboarding & first-session UX

- **New signup (no invite):** Google or magic link → "Create new household
  or join via invite" → name household → **5-question profile wizard
  (skippable per Q + "skip all" escape)**: family size, dietary
  restrictions, allergies, favourite cuisines, typical cook time → drop to
  the meal-plan view.
- **Signup via invite link:** Google/magic link → token consumed → joined →
  **skip the wizard** (household profile already exists, inherited).
- Sample data and tutorial overlays are **not** included; the empty plan
  view is the call to action.

### 9.5 Capped-AI beta + credit ledger

The credit ledger is built **now** (not deferred to Stripe) so the beta and
the paid tier share one mechanism.

- New table (see `supabase/migrations/0003_credit_ledger.sql`):
  `credit_ledger(id, household_id, delta, reason, action_type, ref_id,
  created_at)` — append-only. Balance = `SUM(delta)` per household.
- **Monthly grant**: a lazy check on the first action of a new calendar
  month inserts `+N (reason='monthly_grant')`. Grant size is configurable
  (initial: 30 credits).
- **Action costs (weighted)**: recipe gen ≈ 1, chat turn ≈ 0.5, weekly
  planner ≈ 7 (estimate from days × slots).
- **Variable-cost flow** (planner): insert a `hold` row of −estimate →
  execute fan-out → on success, replace hold with the exact `debit`; on
  failure, delete the hold (refund).
- **Default LLM**: **gpt-4o-mini** for everything in beta.
- **Cap-hit UX**: hard block + "resets on {date}" message + "Notify me
  when paid launches" waitlist signup.
- **Global budget kill-switch**: env var `MONTHLY_BUDGET_USD`. A
  middleware on AI endpoints checks month-to-date spend (derived from
  ledger debits × cost-per-credit) and returns 503 when crossed. Manual
  app keeps working.
- **Stripe later:** inserts `+N (reason='purchase')` rows tied to a
  `stripe_charge_id`. Same ledger, same enforcement, no rewrite.

### 9.6 Infra, deploy, backups

- **Deployment**: GitHub Actions on push to `main` → run critical-path
  tests → build Docker image → push to GHCR → SSH to VM → run Supabase
  migrations → `docker compose pull && docker compose up -d` → `/health`
  check gates the workflow.
- **Repo secrets**: `SSH_PRIVATE_KEY`, `VM_HOST`, `SUPABASE_ACCESS_TOKEN`,
  `SUPABASE_DB_PASSWORD`, `OPENAI_API_KEY`, `MONTHLY_BUDGET_USD`.
- **Backups**: Supabase free tier's daily snapshots (7-day retention) +
  weekly `pg_dump --format=custom` cron on the VM (encrypted dumps, 4–8
  weeks kept locally; later sync to Azure Blob).
- **Observability**: explicitly deferred — pre-launch checklist item, not
  a launch-blocker today. Revisit before going public.

### 9.7 Compliance & data lifecycle

- **Standard pre-launch GDPR**: bilingual PP + ToS pages (template-drafted,
  reviewed by the operator), self-serve account-deletion + data-export
  endpoints, signed Supabase + OpenAI DPAs. **No analytics/cookies in v1
  → no cookie banner.**
- **Account deletion semantics**: drops `auth.users` row + the user's
  `household_members` row + any user-personal preferences. The household's
  recipes/plans/profile stay with remaining members. **Last member exit
  cascades the entire household** (recipes, plans, chat, etc.).
- **Data export**: one-click endpoint returns a JSON bundle of every
  household-scoped resource the user can read (recipes, plans, profile,
  templates, chat history). RLS already constrains the read set.

### 9.8 Operational gates

- **Signup**: open with Google OAuth + magic link. The per-user credit
  grant + global budget kill-switch are the cost brakes.
- **AI access check**: every AI endpoint asserts (1) authenticated,
  (2) member of a household, (3) global kill-switch not tripped,
  (4) sufficient credit balance (or a successful hold for variable-cost
  ops).
- **dbt**: retired from prod. The 86-row `common_ingredients` seed
  becomes a one-time migration. dbt stays in the repo with the dormant
  OFF pipeline.

### 9.9 Internationalization (SE/EN bilingual)

- Library: `react-i18next` with `en.json` + `sv.json`. Locale stored on
  `household_members.locale` (default from browser `Accept-Language`).
- **Translated**: all UI chrome, profile field labels, error messages,
  email templates, PP/ToS, LLM system prompts that produce user-facing text.
- **Not translated in v1**: USDA ingredient names (8k rows). Display as
  USDA's English; revisit if Swedish users complain.
- LLM behaviour: pass the requesting user's locale into the recipe-gen
  and chat agents' system prompts; outputs (recipe names, instructions,
  chat replies) in that language. PydanticAI schemas are
  language-agnostic; content varies.

### 9.10 Build sequence — capped-AI beta

Stripe is **deferred** until usage proves demand. The beta validates the
AI magic at a bounded cost.

1. **Auth + household + onboarding** ← in progress (2026-05-26).
   1. `public.*` core: `households`, `household_members`,
      `household_invites`, `SECURITY DEFINER` helpers
      (`is_member_of`, `is_household_owner`, `user_household_ids`).
      ✅ migration 0001 committed.
   2. `hearth` schema + Hearth tenant tables (recipes, meal_plans,
      household_profiles, chat_*, pending_actions, store_layout,
      shopping_list_template, plus catalog: usda_ingredients,
      pantry_ingredients, ingredient_aliases, ingredient_units).
      FKs to `public.households`. ✅ migration 0002 committed.
   3. `hearth.credit_ledger` + `household_credit_balance` /
      `household_month_spend` views. ✅ migration 0003 committed.
   4. RLS on `public.households` / `household_members` /
      `household_invites` + every `hearth.*` tenant table. Reference
      data: authenticated read. ✅ migration 0004 committed.
   5. Supabase dashboard: enable Google OAuth + email magic link,
      set Site URL + Redirect URLs (`http://localhost:5173`,
      `https://hearth.darkfallcompanion.se`), create `recipe-images`
      private Storage bucket with per-household RLS. (Manual steps.)
   6. FastAPI: install `supabase-py`, add JWT verification middleware
      that propagates the user's claims into each transaction (RLS
      gold standard).
   7. New endpoints: `GET /me` (membership + household), `POST /households`
      (create + insert self as owner-member atomically), `POST
      /households/join/{token}` (consume invite token in a service-role
      transaction; insert member row), `POST /households/{id}/invites`
      (generate new tokenized invite), `DELETE
      /households/{id}/invites/{token}` (revoke), `DELETE
      /households/{id}/members/{user_id}` (owner kick — delete the
      member row), `DELETE /accounts/me` (GDPR — drops `auth.users`;
      cascades follow), `GET /accounts/me/export` (GDPR JSON dump).
   8. Frontend: `@supabase/supabase-js` AuthProvider; sign-in screen;
      create/join household screen; profile wizard (5 questions);
      meal-plan landing.
   9. Frontend: `react-i18next` scaffold with `en.json` + `sv.json`.
2. Migrate USDA + seed into Postgres (start clean — no existing-SQLite
   transform; existing recipes do not migrate).
3. JWT propagation everywhere; verify RLS isolation in a test.
4. Hard AI quota caps via the credit ledger; build global kill-switch.
5. Responsive pass across every view.
6. Critical-path tests: RLS, ledger, shopping consolidation.
7. Bilingual PP/ToS pages; account deletion + export endpoints.
8. CI/CD wiring; deploy to the VM behind Caddy at the subdomain.

*Then later:* credit purchase flow via Stripe; flip the cap into a paywall.

### 9.11 Landmines (known traps, not open decisions)

- **RLS + connection pooling**: must `SET LOCAL request.jwt.claims`
  inside each request's transaction; Supabase's transaction-mode pooler
  keeps no session state. Get this pattern right or RLS silently
  doesn't apply.
- **The beta cap must count tokens-equivalent, not calls.** Chat resends
  growing history each turn; the weekly planner fans out to ~21 gens.
  Per-*call* caps under-bound cost.
- **Supabase free tier pauses after ~7 days of inactivity.** Sporadic
  early-beta traffic can hit a paused DB.
- **Account-linking when same email used in Google + magic link.**
  Supabase Auth handles automatic linking when emails match, but it must
  be enabled in dashboard settings; test the path explicitly.
- **Invite tokens are auth-equivalent**: cryptographically-random,
  single-use, expiry < 14 days, never logged in plaintext.

### 9.12 Explicitly cut from v1

| Cut | Reason |
|---|---|
| **Recipe sharing / community / discovery feed** | Whole second product; validate core loop first. If beta users explicitly ask, build post-Stripe. |
| **PWA + offline shopping list** | Responsive web only; PWA bolts on cheaply later. Accepted risk: in-store signal drop. |
| **Multi-membership** (a user in N households) | One household per user; add member table later if needed. |
| **Per-user pantry / catalog writes** | Catalog is global admin-curated. Personal renames defer to v1.1 if requested. |
| **OFF in production** | 12GB liability for a non-core feature. Kept in repo as data-eng showcase. |
| **dbt in production** | Job evaporates with OFF cut. Seed becomes one-time SQL migration. |
| **Subscription pricing** | Usage credits only — one-time Stripe Checkout, no subscription lifecycle. |
| **Cookie banner / analytics** | No analytics tracking in v1. |
| **USDA name translation** | English names remain in Swedish UI. Revisit on user feedback. |

### 9.13 Multi-app forward compatibility

Hearth lives alone in this Supabase project today, but the schema is laid
out so a future second app's adoption is a non-event. (A habit-tracker
side-project that may eventually merge with Hearth is the canonical
example — design decisions were taken with that in mind.)

**Schema layout:**
- `public.*` — **shared core only.** Today: `households`,
  `household_members`, `household_invites`, plus the `SECURITY DEFINER`
  helpers (`is_member_of`, `is_household_owner`, `user_household_ids`).
  Convention: minimal surface area, no app-specific columns, both
  current and future apps can rely on the shape.
- `hearth.*` — Hearth-specific everything (recipes, meal plans,
  household_profiles meal-prefs blob, chat_*, pending_actions,
  store_layout, shopping_list_template, credit_ledger, USDA + pantry
  catalog).
- `<future_app>.*` — when a second app joins, it gets its own schema
  and uses the existing `public.household_members` for membership.
  No coordination needed beyond agreeing on the role enum.

**Why this layout:**
- Supabase auto-exposes `public.*` via PostgREST. Keeping it minimal
  limits accidental API surface.
- Each app evolves its own schema independently without coordinating
  schema migrations.
- A shared `households` + membership means one user = one identity
  across all apps from day one — no "link your accounts" flow at
  merge time.

**When a second app starts:**
1. Create its schema; add tenant tables FK-ing to `public.households`.
2. Add RLS policies using `public.is_member_of(household_id)`.
3. Reuse the existing tokenized invite flow (or add its own with
   different lifetimes — same `household_invites` table works).
4. No changes to Hearth required.

**App-specific user state**: per-user app-specific fields (e.g. a
gamification XP counter for a habit app) go in
`<app>.<app>_user_state(user_id uuid pk references auth.users)`, *not*
in `public.profiles`. The `public.*` schema deliberately has no
`profiles` table — user identity is `auth.users`; per-membership state
is on `household_members`; everything app-specific is app-scoped.
