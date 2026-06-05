-- Row-Level Security for both schemas.
--
-- Membership checks route through public.is_member_of(uuid) and
-- public.is_household_owner(uuid) -- SECURITY DEFINER helpers that bypass
-- RLS recursion on household_members.
--
-- Mutations on the core auth tables (households, household_members,
-- household_invites) are intentionally restricted in RLS -- inserts happen
-- via service role in FastAPI, where cross-row consistency (create household
-- + insert owner-membership atomically; validate invite + mark used + insert
-- member atomically) lives in one transaction.

-- ============================================================================
-- public.households: members see + update; owner-only delete.
-- INSERT via service role only.
-- ============================================================================
alter table public.households enable row level security;

create policy households_select_member on public.households
    for select to authenticated
    using (public.is_member_of(id));

create policy households_update_member on public.households
    for update to authenticated
    using (public.is_member_of(id))
    with check (public.is_member_of(id));

create policy households_delete_owner on public.households
    for delete to authenticated
    using (public.is_household_owner(id));

-- ============================================================================
-- public.household_members: see fellow members; self-leave OR owner-kick.
-- INSERTs via service role only.
-- ============================================================================
alter table public.household_members enable row level security;

create policy members_select_in_household on public.household_members
    for select to authenticated
    using (public.is_member_of(household_id));

create policy members_delete_self_or_owner on public.household_members
    for delete to authenticated
    using (
        user_id = auth.uid()
        or public.is_household_owner(household_id)
    );

-- ============================================================================
-- public.household_invites: members can list / create; consume via service role.
-- ============================================================================
alter table public.household_invites enable row level security;

create policy invites_select_in_household on public.household_invites
    for select to authenticated
    using (public.is_member_of(household_id));

create policy invites_insert_member on public.household_invites
    for insert to authenticated
    with check (
        created_by = auth.uid()
        and public.is_member_of(household_id)
    );

create policy invites_delete_member on public.household_invites
    for delete to authenticated
    using (public.is_member_of(household_id));

-- ============================================================================
-- Reference data in hearth: authenticated read, no app-user writes.
-- ============================================================================
alter table hearth.usda_ingredients     enable row level security;
alter table hearth.pantry_ingredients   enable row level security;
alter table hearth.ingredient_aliases   enable row level security;
alter table hearth.ingredient_units     enable row level security;

create policy usda_read_authenticated     on hearth.usda_ingredients
    for select to authenticated using (true);
create policy pantry_read_authenticated   on hearth.pantry_ingredients
    for select to authenticated using (true);
create policy aliases_read_authenticated  on hearth.ingredient_aliases
    for select to authenticated using (true);
create policy units_read_authenticated    on hearth.ingredient_units
    for select to authenticated using (true);

-- ============================================================================
-- Hearth tenant resources: full CRUD scoped to household membership.
-- ============================================================================
alter table hearth.recipes                enable row level security;
alter table hearth.recipe_ingredients     enable row level security;
alter table hearth.meal_plans             enable row level security;
alter table hearth.meal_plan_entries      enable row level security;
alter table hearth.household_profiles     enable row level security;
alter table hearth.chat_sessions          enable row level security;
alter table hearth.chat_messages          enable row level security;
alter table hearth.pending_actions        enable row level security;
alter table hearth.store_layout           enable row level security;
alter table hearth.shopping_list_template enable row level security;
alter table hearth.credit_ledger          enable row level security;

-- recipes
create policy recipes_all_in_household on hearth.recipes
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- recipe_ingredients: scope via parent recipe.
create policy recipe_ingredients_all_via_recipe on hearth.recipe_ingredients
    for all to authenticated
    using (exists (
        select 1 from hearth.recipes r
        where r.id = recipe_ingredients.recipe_id
          and public.is_member_of(r.household_id)
    ))
    with check (exists (
        select 1 from hearth.recipes r
        where r.id = recipe_ingredients.recipe_id
          and public.is_member_of(r.household_id)
    ));

-- meal_plans
create policy meal_plans_all_in_household on hearth.meal_plans
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- meal_plan_entries: scope via parent meal plan.
create policy meal_plan_entries_all_via_plan on hearth.meal_plan_entries
    for all to authenticated
    using (exists (
        select 1 from hearth.meal_plans p
        where p.id = meal_plan_entries.meal_plan_id
          and public.is_member_of(p.household_id)
    ))
    with check (exists (
        select 1 from hearth.meal_plans p
        where p.id = meal_plan_entries.meal_plan_id
          and public.is_member_of(p.household_id)
    ));

-- household_profiles
create policy household_profiles_all_in_household on hearth.household_profiles
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- chat_sessions
create policy chat_sessions_all_in_household on hearth.chat_sessions
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- chat_messages: scope via session.
create policy chat_messages_all_via_session on hearth.chat_messages
    for all to authenticated
    using (exists (
        select 1 from hearth.chat_sessions s
        where s.id = chat_messages.session_id
          and public.is_member_of(s.household_id)
    ))
    with check (exists (
        select 1 from hearth.chat_sessions s
        where s.id = chat_messages.session_id
          and public.is_member_of(s.household_id)
    ));

-- pending_actions
create policy pending_actions_all_in_household on hearth.pending_actions
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- store_layout
create policy store_layout_all_in_household on hearth.store_layout
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- shopping_list_template
create policy shopping_list_template_all_in_household on hearth.shopping_list_template
    for all to authenticated
    using      (public.is_member_of(household_id))
    with check (public.is_member_of(household_id));

-- credit_ledger: read-only for members. Writes (grants, debits, holds,
-- refunds, purchases) come from the service role only.
create policy credit_ledger_select_in_household on hearth.credit_ledger
    for select to authenticated
    using (public.is_member_of(household_id));
