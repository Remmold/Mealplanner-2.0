-- ===========================================================================
-- Explore: public recipe pool + per-household swipe log
-- ---------------------------------------------------------------------------
-- The pool is global (readable to all authenticated users). Three sources:
--   * starter_corpus  — seeded once from backend/seeds/starter_recipes.json
--   * llm             — every successful LLM recipe gen is mirrored here
--   * household_share — future: opt-in shares from a personal recipe
--
-- The swipe log is per-household and de-dups the deck across sessions.
-- ===========================================================================


create table if not exists hearth.public_recipes (
    id                          uuid primary key default gen_random_uuid(),
    name                        text not null,
    ingredients                 jsonb not null,          -- [{fdc_id, name, quantity_g}, ...]
    instructions                jsonb not null,
    meal_type                   text                     check (meal_type is null or meal_type in ('breakfast','lunch','dinner')),
    cuisine                     text[] not null default '{}',
    dietary                     text[] not null default '{}',
    time_min                    int,
    source                      text not null            check (source in ('starter_corpus','llm','household_share')),
    originating_household_id    uuid references public.households(id) on delete set null,
    image_path                  text,
    created_at                  timestamptz not null default now()
);

-- Dedup: never store two recipes with the exact same name. Variations on
-- same dish should differ in name (e.g. "Greek Moussaka" vs "Moussaka with
-- Lentils") to coexist. This is the user's chosen dedup policy.
create unique index if not exists ux_public_recipes_name on hearth.public_recipes (lower(name));

create index if not exists idx_public_recipes_source     on hearth.public_recipes (source);
create index if not exists idx_public_recipes_meal_type  on hearth.public_recipes (meal_type);
create index if not exists idx_public_recipes_cuisine    on hearth.public_recipes using gin (cuisine);
create index if not exists idx_public_recipes_dietary    on hearth.public_recipes using gin (dietary);


create table if not exists hearth.recipe_swipes (
    household_id        uuid not null references public.households(id) on delete cascade,
    public_recipe_id    uuid not null references hearth.public_recipes(id) on delete cascade,
    direction           text not null            check (direction in ('like','skip')),
    created_at          timestamptz not null default now(),
    primary key (household_id, public_recipe_id)
);

create index if not exists idx_recipe_swipes_household on hearth.recipe_swipes (household_id, created_at desc);


-- Provenance on personal recipes so we can show "from explore" badges later
-- and prevent re-importing the same pool recipe twice.
alter table hearth.recipes
    add column if not exists public_origin_id uuid references hearth.public_recipes(id) on delete set null;

create index if not exists idx_recipes_public_origin on hearth.recipes (public_origin_id) where public_origin_id is not null;


-- ===========================================================================
-- RLS
-- ===========================================================================

alter table hearth.public_recipes enable row level security;
alter table hearth.recipe_swipes  enable row level security;

-- Public pool: readable by any authenticated user. Inserts/updates only via
-- service_role (the LLM generator, seed script, and future share flow all
-- run as service_role per the codebase pattern).
drop policy if exists public_recipes_read_all on hearth.public_recipes;
create policy public_recipes_read_all on hearth.public_recipes
    for select to authenticated using (true);

-- Swipes are private to the household that made them.
drop policy if exists recipe_swipes_household on hearth.recipe_swipes;
create policy recipe_swipes_household on hearth.recipe_swipes
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));


-- ===========================================================================
-- Grants (mirrors the pattern from 20260526120500_grant_role_privileges_on_hearth)
-- ===========================================================================

grant select                          on hearth.public_recipes to authenticated;
grant select, insert, update, delete  on hearth.public_recipes to service_role;
grant select, insert, update, delete  on hearth.recipe_swipes  to authenticated;
grant select, insert, update, delete  on hearth.recipe_swipes  to service_role;
