-- Per-household "what's already in our kitchen" — the set of fdc_ids the
-- household treats as always-available. Used to:
--   * silently omit staples from the shopping list ('Check pantry' section)
--   * split the recipe view into 'to buy' vs 'from pantry'
--   * compute a comfort score (non-pantry ingredient count)
--
-- The default contents are seeded from a curated system list (filtered by
-- profile.cuisines) the first time a household visits its pantry. We don't
-- pre-populate at household creation so users who never look at the feature
-- still see clean state.

create table if not exists hearth.household_staples (
    household_id  uuid not null references public.households(id) on delete cascade,
    fdc_id        integer not null references hearth.usda_ingredients(fdc_id),
    added_at      timestamptz not null default now(),
    primary key (household_id, fdc_id)
);

create index if not exists idx_household_staples_household
    on hearth.household_staples (household_id);

alter table hearth.household_staples enable row level security;

drop policy if exists household_staples_member on hearth.household_staples;
create policy household_staples_member on hearth.household_staples
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

grant select, insert, update, delete on hearth.household_staples to authenticated;
grant select, insert, update, delete on hearth.household_staples to service_role;
