"""Add per-piece / per-slice display units to hearth.ingredient_units.

The shopping list + recipe modal use this table to render '4 hamburger buns'
instead of '120g bread', or '2 cloves garlic' instead of '10g garlic'. Grams
remain the canonical storage unit — display is converted at read time."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# fdc_id, display_unit, grams_per_unit, round_step
ROWS: list[tuple[int, str, float, float]] = [
    # ── eggs (already has 171287 = pcs / 50g; redundant but idempotent)
    (171287, "pcs",   50.0, 1),
    (172184, "pcs",   18.0, 1),    # yolk
    (172183, "pcs",   33.0, 1),    # white

    # ── alliums
    (170000, "pcs",  100.0, 1),    # yellow onion (overrides earlier 150g)
    (170008, "pcs",  100.0, 1),    # red onion (mapped to sweet)
    (170499, "pcs",   30.0, 1),    # shallot
    (170006, "pcs",   15.0, 1),    # scallion
    (169230, "clove",  5.0, 1),    # garlic clove (already 5g, idempotent)
    (169246, "pcs",  100.0, 1),    # leek

    # ── produce by piece
    (170457, "pcs",  100.0, 1),    # tomato (was 120, tightening)
    (169225, "pcs",  250.0, 1),    # cucumber
    (170108, "pcs",  150.0, 1),    # red bell pepper
    (170427, "pcs",  150.0, 1),    # green bell pepper
    (169383, "pcs",  150.0, 1),    # yellow bell pepper
    (170106, "pcs",   15.0, 1),    # chili pepper
    (168576, "pcs",   15.0, 1),    # jalapeno
    (169228, "pcs",  300.0, 1),    # eggplant
    (169291, "pcs",  200.0, 1),    # zucchini
    (170393, "pcs",   80.0, 1),    # carrot
    (169145, "pcs",  100.0, 1),    # beetroot
    (170417, "pcs",  100.0, 1),    # parsnip
    (170032, "pcs",  150.0, 1),    # potato (medium)
    (168482, "pcs",  130.0, 1),    # sweet potato
    (169231, "piece", 30.0, 1),    # ginger piece
    (170400, "pcs",  600.0, 1),    # celeriac (whole)
    (169986, "pcs",  600.0, 1),    # cauliflower head
    (170379, "pcs",  350.0, 1),    # broccoli head
    (169975, "pcs",  900.0, 1),    # cabbage head

    # ── mushrooms
    (169251, "pcs",   25.0, 1),    # button mushroom
    (169255, "pcs",   90.0, 1),    # portobello
    (168422, "pcs",   30.0, 1),    # chanterelle
    (169242, "pcs",   20.0, 1),    # shiitake

    # ── fruit
    (171689, "pcs",  180.0, 1),    # apple
    (169118, "pcs",  180.0, 1),    # pear
    (173944, "pcs",  120.0, 1),    # banana
    (167746, "pcs",   60.0, 1),    # lemon
    (168155, "pcs",   60.0, 1),    # lime
    (169097, "pcs",  130.0, 1),    # orange
    (169910, "pcs",  200.0, 1),    # mango
    (168153, "pcs",   80.0, 1),    # kiwi
    (169949, "pcs",   70.0, 1),    # plum
    (171697, "pcs",   35.0, 1),    # apricot
    (171707, "pcs",  200.0, 1),    # avocado
    (171705, "pcs",  200.0, 1),    # avocado (all)
    (173021, "pcs",   60.0, 1),    # fig

    # ── proteins by portion
    (168251, "pcs",  150.0, 1),    # pork chop
    (168249, "pcs",  200.0, 1),    # pork tenderloin
    (171477, "pcs",  150.0, 1),    # chicken breast fillet
    (172383, "pcs",  120.0, 1),    # chicken thigh fillet
    (173614, "pcs",  100.0, 1),    # chicken drumstick
    (173632, "pcs",   50.0, 1),    # chicken wing
    (175167, "pcs",  150.0, 1),    # salmon portion
    (173686, "pcs",  150.0, 1),    # salmon wild portion
    (171955, "pcs",  150.0, 1),    # cod portion
    (173706, "pcs",  150.0, 1),    # tuna fresh portion

    # ── sausage & cured
    (172934, "pcs",   60.0, 1),    # pork sausage / falukorv slice
    (172968, "pcs",   50.0, 1),    # frankfurter
    (173864, "slice", 20.0, 1),    # ham slice
    (168277, "strip", 10.0, 1),    # bacon strip

    # ── bread + buns
    (172686, "pcs",   50.0, 1),    # bread / hamburger bun = 50g (was 30g slice)
    (174924, "slice", 30.0, 1),    # white bread / breadcrumbs slice
    (175030, "slice", 30.0, 1),    # generic bread slice
    (169716, "pcs",   60.0, 1),    # tortilla

    # ── cheese slices (most cheeses are sold sliced for sandwiches)
    (170848, "slice", 20.0, 1),    # parmesan / lagrad ost slice
    (173414, "slice", 20.0, 1),    # cheddar (FDP)
    (170847, "slice", 20.0, 1),    # mozzarella part-skim
    (173420, "pcs",  200.0, 1),    # feta (small block)
    (173417, "slice", 20.0, 1),    # cheddar generic
    (172177, "pcs",  200.0, 1),    # brie (wedge)
    (172175, "pcs",  100.0, 1),    # blue cheese (wedge)
    (173418, "pcs",  200.0, 1),    # cream cheese (tub)
    (170851, "pcs",  225.0, 1),    # cottage cheese tub
    (171249, "pcs",  100.0, 1),    # goat cheese small log

    # ── nuts & seeds (typically scoop / dl not piece, but some)
    (170567, "dl",    60.0, 1),    # almonds
    (170187, "dl",    50.0, 1),    # walnuts
    (170581, "dl",    60.0, 1),    # hazelnuts
    (170182, "dl",    50.0, 1),    # pecans
    (170162, "dl",    55.0, 1),    # cashews
    (170184, "dl",    50.0, 1),    # pistachios
    (170591, "dl",    50.0, 1),    # pine nuts
    (170554, "msk",   12.0, 0.5),  # chia seed (typically by tbsp)
]


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        inserted = updated = 0
        for fdc_id, unit, grams, step in ROWS:
            result = await conn.execute(
                """
                INSERT INTO hearth.ingredient_units (fdc_id, display_unit, grams_per_unit, round_step)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (fdc_id) DO UPDATE SET
                    display_unit  = excluded.display_unit,
                    grams_per_unit = excluded.grams_per_unit,
                    round_step    = excluded.round_step
                """,
                fdc_id, unit, grams, step,
            )
            if "INSERT 0 1" in result:
                inserted += 1
            else:
                updated += 1
        total = await conn.fetchval("SELECT count(*) FROM hearth.ingredient_units")
        print(f"upserted {len(ROWS)} rows ({inserted} new, {updated} updated). Total rows: {total}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
