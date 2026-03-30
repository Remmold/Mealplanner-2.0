with products as (
    select * from {{ ref('stg_products') }}
)

select
    -- Identity
    code,
    product_name,
    brands,
    primary_category,

    -- Human-readable category label (strips locale prefix + hyphens, capitalises first word)
    case
        when primary_category is not null
        then upper(left(replace(regexp_replace(primary_category, '^[a-z]{2}:', ''), '-', ' '), 1))
             || substring(replace(regexp_replace(primary_category, '^[a-z]{2}:', ''), '-', ' '), 2)
    end                                                         as category_label,

    categories,
    allergens,
    countries,
    ingredients_text,
    image_url,

    -- Quality scores
    nutriscore_grade,
    nova_group,

    -- Serving info
    serving_size,
    serving_quantity_g,

    -- Nutrition per 100g
    energy_kcal_100g,
    proteins_100g,
    carbohydrates_100g,
    sugars_100g,
    fat_100g,
    saturated_fat_100g,
    fiber_100g,
    salt_100g,
    sodium_100g,

    -- -------------------------------------------------------------------------
    -- Macro level labels (useful for AI meal-planning filters & explanations)
    -- -------------------------------------------------------------------------
    case
        when proteins_100g >= 20 then 'high'
        when proteins_100g >= 10 then 'medium'
        when proteins_100g is not null then 'low'
    end as protein_level,

    case
        when fat_100g <= 3        then 'low'
        when fat_100g <= 17.5     then 'medium'
        when fat_100g is not null then 'high'
    end as fat_level,

    case
        when sugars_100g <= 5     then 'low'
        when sugars_100g <= 12.5  then 'medium'
        when sugars_100g is not null then 'high'
    end as sugar_level,

    -- UK FSA fibre thresholds
    case
        when fiber_100g >= 6      then 'high'
        when fiber_100g >= 3      then 'medium'
        when fiber_100g is not null then 'low'
    end as fiber_level,

    -- -------------------------------------------------------------------------
    -- Quality / processing flags
    -- -------------------------------------------------------------------------
    (nutriscore_grade in ('a', 'b'))                            as is_high_nutriscore,
    (nova_group in (1, 2))                                      as is_minimally_processed,
    (proteins_100g >= 20)                                       as is_high_protein,
    (energy_kcal_100g <= 100)                                   as is_low_calorie,

    -- -------------------------------------------------------------------------
    -- Dietary flags — derived from declared allergens.
    -- Only true when the product has at least one allergen declared (non-empty
    -- list), because an empty list means "unknown", not "free of everything".
    -- -------------------------------------------------------------------------
    (
        len(allergens) > 0
        and not list_contains(allergens, 'en:gluten')
    )                                                           as is_gluten_free,

    (
        len(allergens) > 0
        and not list_contains(allergens, 'en:milk')
    )                                                           as is_dairy_free,

    (
        len(allergens) > 0
        and not list_contains(allergens, 'en:eggs')
    )                                                           as is_egg_free,

    (
        len(allergens) > 0
        and not list_contains(allergens, 'en:nuts')
        and not list_contains(allergens, 'en:peanuts')
    )                                                           as is_nut_free,

    (
        len(allergens) > 0
        and not list_contains(allergens, 'en:fish')
        and not list_contains(allergens, 'en:crustaceans')
        and not list_contains(allergens, 'en:molluscs')
    )                                                           as is_seafood_free,

    -- -------------------------------------------------------------------------
    -- Data completeness score (0.0 – 1.0)
    -- Counts how many of the 10 key meal-planning fields are non-null.
    -- The AI layer can use this to deprioritise poorly-documented products.
    -- -------------------------------------------------------------------------
    round(
        (
            (energy_kcal_100g    is not null)::integer
          + (proteins_100g       is not null)::integer
          + (carbohydrates_100g  is not null)::integer
          + (fat_100g            is not null)::integer
          + (fiber_100g          is not null)::integer
          + (nutriscore_grade    is not null)::integer
          + (nova_group          is not null)::integer
          + (ingredients_text    is not null)::integer
          + (serving_quantity_g  is not null)::integer
          + (image_url           is not null)::integer
        ) / 10.0,
        1
    )                                                           as data_completeness,

    last_modified_at

from products
