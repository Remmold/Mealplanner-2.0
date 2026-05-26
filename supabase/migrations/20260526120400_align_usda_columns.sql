-- Add columns the existing API models expect (saturated fat + salt as grams).
-- These weren't in 0001's initial schema because we modelled USDA as
-- "sodium_mg" only, but the DuckDB source + Ingredient/RecipeNutrition
-- response models use the grams-of-salt convention. Keep both: the new
-- columns hold the source values; sodium_mg stays available for future use.

alter table hearth.usda_ingredients
    add column if not exists saturated_fat_g numeric,
    add column if not exists salt_g numeric;
