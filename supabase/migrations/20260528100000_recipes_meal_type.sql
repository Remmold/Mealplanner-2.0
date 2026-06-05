-- Add nullable meal_type to recipes so the meal-plan picker can prioritise
-- slot-appropriate options (breakfast porridge over lasagna for the morning
-- slot, etc.) while still letting the user pick anything.
--
-- Nullable + open by default — existing recipes stay untagged and rank in
-- the middle of the picker; the user can tag them via the editor.

alter table hearth.recipes
    add column if not exists meal_type text;

alter table hearth.recipes
    drop constraint if exists recipes_meal_type_check;

alter table hearth.recipes
    add constraint recipes_meal_type_check
        check (meal_type is null or meal_type in ('breakfast', 'lunch', 'dinner'));
