-- Credit ledger: append-only, household-scoped. Same machinery for beta
-- free grants and (later) Stripe purchases.
--
-- Lives in the hearth schema (Hearth-specific economics). FK to the shared
-- public.households so the credits travel with the household if/when
-- HabitHabitat eventually wants visibility.
--
-- Balance = SUM(delta) per household. Reasons:
--   monthly_grant    +N, inserted lazily on first action of a new month
--   debit            -N, finalized cost of an AI action
--   hold             -N, pre-flight reservation for variable-cost ops
--   refund           +N, on hold release / action failure
--   purchase         +N, Stripe credit-pack (post-beta)
--   admin_adjustment +/-, manual fix-ups

create table if not exists hearth.credit_ledger (
    id                uuid primary key default gen_random_uuid(),
    household_id      uuid not null references public.households(id) on delete cascade,
    delta             numeric not null,
    reason            text not null check (reason in (
        'monthly_grant', 'debit', 'hold', 'refund', 'purchase', 'admin_adjustment'
    )),
    action_type       text check (action_type in (
        'recipe_gen', 'chat_turn', 'weekly_plan'
    )),
    ref_id            uuid,
    stripe_charge_id  text,
    created_at        timestamptz default now()
);

create index if not exists idx_credit_ledger_household_created
    on hearth.credit_ledger (household_id, created_at desc);

-- date_trunc on a timestamptz is non-immutable (result depends on session
-- timezone), so it can't go directly in an index expression. Anchoring to
-- UTC via AT TIME ZONE makes the whole expression immutable.
create index if not exists idx_credit_ledger_household_month
    on hearth.credit_ledger (
        household_id,
        date_trunc('month', created_at at time zone 'UTC')
    );

-- Current balance per household. RLS on the underlying table also gates this view.
create or replace view hearth.household_credit_balance as
select
    household_id,
    coalesce(sum(delta), 0) as balance
from hearth.credit_ledger
group by household_id;

-- Month-to-date debit total per household (positive number) — used by the
-- global kill-switch middleware to compute total spend and 503 when over.
create or replace view hearth.household_month_spend as
select
    household_id,
    coalesce(-sum(delta) filter (where reason in ('debit', 'hold')), 0) as month_debit
from hearth.credit_ledger
where created_at >= date_trunc('month', now())
group by household_id;
