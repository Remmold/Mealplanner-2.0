-- Lunch-bag leftovers: link a leftover entry to the cook that produced it.
--
-- The lunchbox/batch planner now lays a cook on one day and "lunch bags" of the
-- same dish on the following days in the same slot, extending forward until the
-- batch (recipe servings) runs out. Each bag points at its cook so the calendar
-- can show which meals are actually COOKED and how many lunch bags each yields.
--
--   * A normal single meal:  source_entry_id IS NULL, no children.
--   * A cook that makes bags: source_entry_id IS NULL, N children point at it.
--   * A lunch bag (leftover): source_entry_id = the cook's entry id.
--
-- on delete cascade: re-rolling / deleting a cook clears its leftover bags too
-- (the leftovers of a dish you no longer cook don't make sense on their own).

alter table hearth.meal_plan_entries
    add column if not exists source_entry_id uuid
        references hearth.meal_plan_entries(id) on delete cascade;

create index if not exists idx_meal_plan_entries_source
    on hearth.meal_plan_entries (source_entry_id);
