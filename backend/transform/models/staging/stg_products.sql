with source as (
    select * from {{ source('off', 'products') }}
),

categories as (
    select
        _dlt_parent_id,
        list(value) as categories
    from {{ source('off', 'products__categories_tags') }}
    group by _dlt_parent_id
),

allergens as (
    select
        _dlt_parent_id,
        list(value) as allergens
    from {{ source('off', 'products__allergens_tags') }}
    group by _dlt_parent_id
),

countries as (
    select
        _dlt_parent_id,
        list(value) as countries
    from {{ source('off', 'products__countries_tags') }}
    group by _dlt_parent_id
),

cleaned as (
    select
        s.code,
        -- Normalise ALL-CAPS names: uppercase first letter, rest lower-case.
        -- Leaves already mixed-case names untouched.
        case
            when upper(trim(s.product_name)) = trim(s.product_name)
                 and length(trim(s.product_name)) > 3
            then upper(left(trim(s.product_name), 1))
                 || lower(substring(trim(s.product_name), 2))
            else trim(s.product_name)
        end                                                     as product_name,
        nullif(trim(s.brands), '')                              as brands,
        s.primary_category,
        coalesce(c.categories, [])                              as categories,
        coalesce(a.allergens, [])                               as allergens,
        coalesce(co.countries, [])                              as countries,
        nullif(trim(s.ingredients_text), '')                    as ingredients_text,
        nullif(trim(s.image_url), '')                           as image_url,

        -- Nutri-Score: keep only valid single letter grades a-e
        case
            when lower(s.nutriscore_grade) in ('a', 'b', 'c', 'd', 'e')
            then lower(s.nutriscore_grade)
        end                                                     as nutriscore_grade,

        -- NOVA group: 1 (unprocessed) → 4 (ultra-processed)
        case
            when s.nova_group::varchar in ('1', '2', '3', '4')
            then s.nova_group::integer
        end                                                     as nova_group,

        nullif(trim(s.serving_size), '')                        as serving_size,
        case
            when s.serving_quantity_g > 0 then s.serving_quantity_g
        end                                                     as serving_quantity_g,

        -- Nutritional values per 100g — clamped to physically possible ranges
        case when s.energy_kcal_100g    between 0 and 900  then s.energy_kcal_100g    end as energy_kcal_100g,
        case when s.proteins_100g       between 0 and 100  then s.proteins_100g       end as proteins_100g,
        case when s.carbohydrates_100g  between 0 and 100  then s.carbohydrates_100g  end as carbohydrates_100g,
        case when s.sugars_100g         between 0 and 100  then s.sugars_100g         end as sugars_100g,
        case when s.fat_100g            between 0 and 100  then s.fat_100g            end as fat_100g,
        case when s.saturated_fat_100g  between 0 and 100  then s.saturated_fat_100g  end as saturated_fat_100g,
        case when s.fiber_100g          between 0 and 100  then s.fiber_100g          end as fiber_100g,
        case when s.salt_100g           between 0 and 100  then s.salt_100g           end as salt_100g,
        case when s.sodium_100g         between 0 and 38.8 then s.sodium_100g         end as sodium_100g,

        to_timestamp(s.last_modified_t)                         as last_modified_at,
        s._dlt_id                                               as source_id

    from source s
    left join categories c  on c._dlt_parent_id  = s._dlt_id
    left join allergens a   on a._dlt_parent_id   = s._dlt_id
    left join countries co  on co._dlt_parent_id  = s._dlt_id

    -- Require a usable name and at least a calorie value
    where
        s.product_name is not null
        and trim(s.product_name) != ''
        and s.energy_kcal_100g is not null
        and s.energy_kcal_100g between 0 and 900
)

select * from cleaned
