with products as (
    select * from {{ ref('stg_products') }}
),

subcategory_mapping as (
    select * from {{ ref('subcategory_mapping') }}
),

-- For each product, find the best (lowest sort_order) matching subcategory
product_subcategories as (
    select
        p.code,
        m.subcategory,
        m.sort_order,
        row_number() over (partition by p.code order by m.sort_order) as rn
    from products p,
         lateral unnest(p.categories) as t(cat_tag)
    inner join subcategory_mapping m on m.tag = t.cat_tag
)

select
    -- Identity
    p.code,
    p.product_name,
    p.brands,
    p.primary_category,

    -- Human-readable category label (strips locale prefix + hyphens, capitalises first word)
    case
        when p.primary_category is not null
        then upper(left(replace(regexp_replace(p.primary_category, '^[a-z]{2}:', ''), '-', ' '), 1))
             || substring(replace(regexp_replace(p.primary_category, '^[a-z]{2}:', ''), '-', ' '), 2)
    end                                                         as category_label,

    -- Granular subcategory derived from OFF taxonomy tags
    ps.subcategory,

    p.categories,
    p.allergens,
    p.countries,
    p.ingredients_text,
    p.image_url,

    -- Quality scores
    p.nutriscore_grade,
    p.nova_group,

    -- Serving info
    p.serving_size,
    p.serving_quantity_g,

    -- Nutrition per 100g
    p.energy_kcal_100g,
    p.proteins_100g,
    p.carbohydrates_100g,
    p.sugars_100g,
    p.fat_100g,
    p.saturated_fat_100g,
    p.fiber_100g,
    p.salt_100g,
    p.sodium_100g,

    -- -------------------------------------------------------------------------
    -- Macro level labels (useful for AI meal-planning filters & explanations)
    -- -------------------------------------------------------------------------
    case
        when p.proteins_100g >= 20 then 'high'
        when p.proteins_100g >= 10 then 'medium'
        when p.proteins_100g is not null then 'low'
    end as protein_level,

    case
        when p.fat_100g <= 3        then 'low'
        when p.fat_100g <= 17.5     then 'medium'
        when p.fat_100g is not null then 'high'
    end as fat_level,

    case
        when p.sugars_100g <= 5     then 'low'
        when p.sugars_100g <= 12.5  then 'medium'
        when p.sugars_100g is not null then 'high'
    end as sugar_level,

    -- UK FSA fibre thresholds
    case
        when p.fiber_100g >= 6      then 'high'
        when p.fiber_100g >= 3      then 'medium'
        when p.fiber_100g is not null then 'low'
    end as fiber_level,

    -- -------------------------------------------------------------------------
    -- Quality / processing flags
    -- -------------------------------------------------------------------------
    (p.nutriscore_grade in ('a', 'b'))                          as is_high_nutriscore,
    (p.nova_group in (1, 2))                                    as is_minimally_processed,
    (p.proteins_100g >= 20)                                     as is_high_protein,
    (p.energy_kcal_100g <= 100)                                 as is_low_calorie,

    -- -------------------------------------------------------------------------
    -- Dietary flags — derived from declared allergens.
    -- Only true when the product has at least one allergen declared (non-empty
    -- list), because an empty list means "unknown", not "free of everything".
    -- -------------------------------------------------------------------------
    (
        len(p.allergens) > 0
        and not list_contains(p.allergens, 'en:gluten')
    )                                                           as is_gluten_free,

    (
        len(p.allergens) > 0
        and not list_contains(p.allergens, 'en:milk')
    )                                                           as is_dairy_free,

    (
        len(p.allergens) > 0
        and not list_contains(p.allergens, 'en:eggs')
    )                                                           as is_egg_free,

    (
        len(p.allergens) > 0
        and not list_contains(p.allergens, 'en:nuts')
        and not list_contains(p.allergens, 'en:peanuts')
    )                                                           as is_nut_free,

    (
        len(p.allergens) > 0
        and not list_contains(p.allergens, 'en:fish')
        and not list_contains(p.allergens, 'en:crustaceans')
        and not list_contains(p.allergens, 'en:molluscs')
    )                                                           as is_seafood_free,

    -- -------------------------------------------------------------------------
    -- Data completeness score (0.0 – 1.0)
    -- Counts how many of the 10 key meal-planning fields are non-null.
    -- The AI layer can use this to deprioritise poorly-documented products.
    -- -------------------------------------------------------------------------
    round(
        (
            (p.energy_kcal_100g    is not null)::integer
          + (p.proteins_100g       is not null)::integer
          + (p.carbohydrates_100g  is not null)::integer
          + (p.fat_100g            is not null)::integer
          + (p.fiber_100g          is not null)::integer
          + (p.nutriscore_grade    is not null)::integer
          + (p.nova_group          is not null)::integer
          + (p.ingredients_text    is not null)::integer
          + (p.serving_quantity_g  is not null)::integer
          + (p.image_url           is not null)::integer
        ) / 10.0,
        1
    )                                                           as data_completeness,

    p.last_modified_at

from products p
left join product_subcategories ps on ps.code = p.code and ps.rn = 1
