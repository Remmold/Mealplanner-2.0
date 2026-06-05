-- Hearth schema + all Hearth-specific tables.
--
-- All FKs to the household root use public.households(id), set up in the
-- previous migration. Hearth's tenant resources cascade on household
-- delete (last-member-leaves auto-deletes the household via the API).
--
-- Translated from the SQLite schema in backend/api/recipe_db.py. Types:
--   TEXT (uuid strings)   -> uuid (gen_random_uuid())
--   TEXT (json blobs)     -> jsonb
--   TIMESTAMP             -> timestamptz
--   REAL                  -> numeric

set check_function_bodies = off;
create extension if not exists "pg_trgm";  -- fuzzy USDA search

create schema if not exists hearth;
comment on schema hearth is
    'Hearth meal-planner. Tenant resources FK to public.households.';

grant usage on schema hearth to authenticated;

-- ============================================================================
-- Reference data (global, public-read to authenticated; admin-only writes).
-- ============================================================================

-- USDA SR Legacy nutrition database (~8k rows).
create table if not exists hearth.usda_ingredients (
    fdc_id         integer primary key,
    description    text not null,
    food_group     text,
    energy_kcal    numeric,
    protein_g      numeric,
    fat_g          numeric,
    carbs_g        numeric,
    fiber_g        numeric,
    sugar_g        numeric,
    sodium_mg      numeric,
    raw            jsonb
);
create index if not exists idx_usda_ingredients_food_group
    on hearth.usda_ingredients (food_group);
create index if not exists idx_usda_ingredients_description_trgm
    on hearth.usda_ingredients using gin (description gin_trgm_ops);

-- Curated pantry catalog (the 819 LLM-bootstrapped items).
create table if not exists hearth.pantry_ingredients (
    fdc_id        integer primary key references hearth.usda_ingredients(fdc_id),
    simple_name   text not null,
    category      text not null,
    subcategory   text,
    created_at    timestamptz default now()
);

-- Display-name dedup: alias_fdc_id is hidden in favour of canonical_fdc_id.
create table if not exists hearth.ingredient_aliases (
    alias_fdc_id      integer primary key references hearth.usda_ingredients(fdc_id),
    canonical_fdc_id  integer not null references hearth.usda_ingredients(fdc_id),
    created_at        timestamptz default now()
);
create index if not exists idx_ingredient_aliases_canonical
    on hearth.ingredient_aliases (canonical_fdc_id);

-- Per-ingredient unit overrides (eggs -> pcs, milk -> dl, garlic -> clove).
create table if not exists hearth.ingredient_units (
    fdc_id          integer primary key references hearth.usda_ingredients(fdc_id),
    display_unit    text not null,
    grams_per_unit  numeric not null,
    round_step      numeric not null default 1
);

-- ============================================================================
-- Recipes + ingredients
-- ============================================================================
create table if not exists hearth.recipes (
    id            uuid primary key default gen_random_uuid(),
    household_id  uuid not null references public.households(id) on delete cascade,
    name          text not null,
    instructions  jsonb not null default '[]'::jsonb,
    servings      integer not null default 4,
    image_path    text,
    created_at    timestamptz default now(),
    updated_at    timestamptz default now()
);
create index if not exists idx_recipes_household on hearth.recipes (household_id);

create table if not exists hearth.recipe_ingredients (
    id          uuid primary key default gen_random_uuid(),
    recipe_id   uuid not null references hearth.recipes(id) on delete cascade,
    fdc_id      integer not null references hearth.usda_ingredients(fdc_id),
    quantity_g  numeric not null,
    unique (recipe_id, fdc_id)
);
create index if not exists idx_recipe_ingredients_recipe
    on hearth.recipe_ingredients (recipe_id);

-- ============================================================================
-- Meal plans
-- ============================================================================
create table if not exists hearth.meal_plans (
    id            uuid primary key default gen_random_uuid(),
    household_id  uuid not null references public.households(id) on delete cascade,
    name          text not null,
    start_date    date not null,
    created_at    timestamptz default now(),
    updated_at    timestamptz default now()
);
create index if not exists idx_meal_plans_household on hearth.meal_plans (household_id);

create table if not exists hearth.meal_plan_entries (
    id            uuid primary key default gen_random_uuid(),
    meal_plan_id  uuid not null references hearth.meal_plans(id) on delete cascade,
    recipe_id     uuid not null references hearth.recipes(id) on delete cascade,
    plan_date     date not null,
    slot          text,
    portions      numeric not null default 1
);
create index if not exists idx_meal_plan_entries_plan
    on hearth.meal_plan_entries (meal_plan_id);

-- ============================================================================
-- Household meal-planning preferences (per household; JSON blob)
-- ============================================================================
create table if not exists hearth.household_profiles (
    household_id  uuid primary key references public.households(id) on delete cascade,
    data          jsonb not null default '{}'::jsonb,
    updated_at    timestamptz default now()
);

-- ============================================================================
-- Store layout (per-household grocery-aisle ordering)
-- ============================================================================
create table if not exists hearth.store_layout (
    household_id  uuid not null references public.households(id) on delete cascade,
    category      text not null,
    sort_index    integer not null,
    primary key (household_id, category)
);

-- ============================================================================
-- Shopping list template (per household; always-buy items)
-- ============================================================================
create table if not exists hearth.shopping_list_template (
    household_id  uuid not null references public.households(id) on delete cascade,
    fdc_id        integer not null references hearth.usda_ingredients(fdc_id),
    quantity_g    numeric not null,
    note          text,
    created_at    timestamptz default now(),
    updated_at    timestamptz default now(),
    primary key (household_id, fdc_id)
);

-- ============================================================================
-- Chat (sessions + messages + pending actions for human-in-the-loop writes)
-- ============================================================================
create table if not exists hearth.chat_sessions (
    id               uuid primary key default gen_random_uuid(),
    household_id     uuid not null references public.households(id) on delete cascade,
    title            text not null default 'New chat',
    message_history  jsonb not null default '[]'::jsonb,
    created_at       timestamptz default now(),
    updated_at       timestamptz default now()
);
create index if not exists idx_chat_sessions_household on hearth.chat_sessions (household_id);

create table if not exists hearth.chat_messages (
    id           uuid primary key default gen_random_uuid(),
    session_id   uuid not null references hearth.chat_sessions(id) on delete cascade,
    role         text not null,
    content      text not null,
    tool_calls   jsonb,
    created_at   timestamptz default now()
);
create index if not exists idx_chat_messages_session on hearth.chat_messages (session_id);

create table if not exists hearth.pending_actions (
    id            uuid primary key default gen_random_uuid(),
    session_id    uuid not null references hearth.chat_sessions(id) on delete cascade,
    household_id  uuid not null references public.households(id) on delete cascade,
    kind          text not null,
    summary       text not null,
    params        jsonb not null,
    status        text not null default 'pending'
                  check (status in ('pending', 'accepted', 'rejected')),
    result        jsonb,
    created_at    timestamptz default now(),
    resolved_at   timestamptz
);
create index if not exists idx_pending_actions_session on hearth.pending_actions (session_id);
create index if not exists idx_pending_actions_status  on hearth.pending_actions (status);
