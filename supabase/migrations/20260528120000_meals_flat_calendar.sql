-- Meals as a flat household calendar (no plans wrapper).
--
-- The meal_plan_entries table becomes the canonical "meals on the calendar"
-- table. To break the dependency on meal_plans:
--   1. Add household_id directly so we can SELECT by date range without
--      joining through meal_plans.
--   2. Backfill from the parent plan, then enforce NOT NULL.
--   3. Make meal_plan_id nullable so new entries don't need to belong to a
--      plan at all (the chat agent and ad-hoc UI now write entries directly).
--   4. Replace the plan-based RLS policy with a household-direct one.
--   5. Add a (household_id, plan_date) index for fast week-window queries.
--
-- Legacy: existing meal_plans + wizard-generated plans keep working. Their
-- entries simply also carry household_id now and are visible on the flat
-- calendar query. We can drop meal_plans entirely in a later migration.

-- 1. Add household_id (nullable for now so we can backfill).
alter table hearth.meal_plan_entries
    add column if not exists household_id uuid
        references public.households(id) on delete cascade;

-- 2. Backfill from the parent plan.
update hearth.meal_plan_entries e
   set household_id = p.household_id
  from hearth.meal_plans p
 where p.id = e.meal_plan_id
   and e.household_id is null;

-- 3. Enforce NOT NULL going forward.
alter table hearth.meal_plan_entries
    alter column household_id set not null;

-- 4. Make meal_plan_id nullable.
alter table hearth.meal_plan_entries
    alter column meal_plan_id drop not null;

-- 5. Replace RLS: household_id direct instead of join-through-plan. The
--   policy name stays so anything else that references it keeps working.
drop policy if exists meal_plan_entries_household on hearth.meal_plan_entries;
create policy meal_plan_entries_household on hearth.meal_plan_entries
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- 6. Fast week-window index.
create index if not exists idx_meal_plan_entries_household_date
    on hearth.meal_plan_entries (household_id, plan_date);
