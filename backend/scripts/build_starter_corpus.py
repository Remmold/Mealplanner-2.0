"""Batch-generate the starter recipe corpus.

Runs the existing chef-style LLM recipe generator over a curated prompt list
spanning Mediterranean, Nordic, Asian, Vegetarian-anywhere, Quick weeknight,
and Batch-cook. Each recipe comes back with proper USDA fdc_id mappings, so
the corpus is ready to insert into hearth.recipes without further work.

Output: backend/seeds/starter_recipes.json — a flat list of tagged recipes
the seed service uses to populate new households based on their profile.

Usage (from the backend/ dir, with venv activated):
    python -m scripts.build_starter_corpus

Re-running is safe: it overwrites the JSON in place. Cost is roughly
$0.10–$0.20 against the model in OPENAI_RECIPE_MODEL (~60 recipes).
Concurrency is capped by CORPUS_GEN_CONCURRENCY (default 3) so we don't
saturate the OpenAI tier or the USDA-search pool. Expect ~10 minutes total.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Imported AFTER load_dotenv so OPENAI_API_KEY is in env when the agent boots.
from api.db import close_pool, init_pool  # noqa: E402
from api.recipe_gen import generate_recipe  # noqa: E402


# ---------------------------------------------------------------------------
# Curated prompt list. Each entry's tags are used by the seed service to pick
# recipes that match a household's profile (cuisine + dietary + cook-time).
#
# Keep prompt text evocative — the chef-agent reads it as the brief and the
# quality of the brief drives the quality of the output. Aim for one specific
# dish per prompt, ideally naming the cuisine and a flavour hook.
# ---------------------------------------------------------------------------

PROMPTS: list[dict] = [
    # ---- Mediterranean (10) ----
    {"category": "mediterranean", "cuisine": ["greek"],        "dietary": [],            "time_min": 90, "slot": "dinner",
     "prompt": "Classic Greek moussaka with layered eggplant, spiced lamb ragu, and a rich béchamel. Bake until the top is deep golden. 4 servings."},
    {"category": "mediterranean", "cuisine": ["italian"],      "dietary": ["vegetarian"], "time_min": 20, "slot": "dinner",
     "prompt": "Italian spaghetti aglio e olio with golden-fried garlic, dried chili, parsley, and a touch of pasta water for emulsion. 20-minute weeknight."},
    {"category": "mediterranean", "cuisine": ["lebanese"],     "dietary": [],            "time_min": 45, "slot": "dinner",
     "prompt": "Lebanese chicken shawarma bowls: spice-marinated chicken thigh, lemony hummus, fresh tabbouleh, pickled turnip, and warm pita."},
    {"category": "mediterranean", "cuisine": ["italian"],      "dietary": ["vegetarian"], "time_min": 75, "slot": "dinner",
     "prompt": "Tuscan ribollita — slow-simmered cannellini bean and lacinato kale soup with day-old sourdough bread to thicken. Drizzle of good olive oil."},
    {"category": "mediterranean", "cuisine": ["greek"],        "dietary": [],            "time_min": 45, "slot": "dinner",
     "prompt": "Greek lemon-oregano chicken souvlaki on skewers, served with cooling tzatziki, warm pita, and a sharp Horiatiki salad with feta."},
    {"category": "mediterranean", "cuisine": ["spanish"],      "dietary": ["vegetarian"], "time_min": 50, "slot": "lunch",
     "prompt": "Spanish tortilla española with thinly sliced potato, slow-caramelised onion, and roasted red pepper. Serve room-temperature wedges with crusty bread."},
    {"category": "mediterranean", "cuisine": ["italian"],      "dietary": ["vegetarian"], "time_min": 55, "slot": "dinner",
     "prompt": "Sicilian pasta alla Norma with melt-soft fried eggplant, garlic-tomato sauce, fresh basil, and shaved ricotta salata."},
    {"category": "mediterranean", "cuisine": ["turkish"],      "dietary": ["vegetarian"], "time_min": 25, "slot": "breakfast",
     "prompt": "Turkish menemen: soft scrambled eggs folded through a slow-cooked tomato-and-green-pepper base, finished with crumbled feta and warm bread."},
    {"category": "mediterranean", "cuisine": ["french"],       "dietary": ["vegetarian"], "time_min": 90, "slot": "dinner",
     "prompt": "Provençal ratatouille — slow-roasted summer vegetables (eggplant, zucchini, bell pepper, tomato) layered with garlic and herbes de Provence. Vegan-friendly."},
    {"category": "mediterranean", "cuisine": ["greek"],        "dietary": ["vegetarian"], "time_min": 35, "slot": "dinner",
     "prompt": "Greek baked feta with cherry tomatoes, olives, oregano, and olive oil — tossed through orzo. The feta melts into a sauce."},

    # ---- Nordic (10) ----
    {"category": "nordic", "cuisine": ["swedish"],   "dietary": [],            "time_min": 55, "slot": "dinner",
     "prompt": "Classic Swedish meatballs (köttbullar) in a silky cream gravy, with buttery mashed potatoes, pickled cucumber and lingonberry sauce."},
    {"category": "nordic", "cuisine": ["norwegian"], "dietary": [],            "time_min": 30, "slot": "dinner",
     "prompt": "Norwegian pan-seared salmon with browned butter, dill, lemon, and steamed new potatoes. Skin crisp; flesh just-cooked."},
    {"category": "nordic", "cuisine": ["swedish"],   "dietary": [],            "time_min": 20, "slot": "lunch",
     "prompt": "Swedish toast skagen — sweet pink shrimp tossed in dill, lemon mayo, and chives, piled on butter-fried rye toast. Crown with roe."},
    {"category": "nordic", "cuisine": ["danish"],    "dietary": [],            "time_min": 50, "slot": "dinner",
     "prompt": "Danish frikadeller — pan-fried pork-and-veal patties with creamy gravy, boiled potatoes, and braised red cabbage with apple."},
    {"category": "nordic", "cuisine": ["swedish"],   "dietary": ["vegetarian"], "time_min": 35, "slot": "dinner",
     "prompt": "Swedish creamed wild-mushroom soup with parsley, a swirl of dill cream, and crusty rye bread for dipping. Vegetarian."},
    {"category": "nordic", "cuisine": ["norwegian"], "dietary": [],            "time_min": 55, "slot": "dinner",
     "prompt": "Norwegian fiskesuppe — creamy fish soup with cod, salmon, leek, carrot, and dill. Bright with lemon, finished with sour cream."},
    {"category": "nordic", "cuisine": ["swedish"],   "dietary": [],            "time_min": 30, "slot": "lunch",
     "prompt": "Swedish gravlax with mustard-dill sauce (hovmästarsås), thin rye, pickled cucumber, and capers — for an open sandwich plate."},
    {"category": "nordic", "cuisine": ["danish"],    "dietary": [],            "time_min": 20, "slot": "lunch",
     "prompt": "Danish smørrebrød with cold-smoked salmon, dill horseradish cream, pickled radish, and crispy rye. Open-faced and architectural."},
    {"category": "nordic", "cuisine": ["swedish"],   "dietary": [],            "time_min": 80, "slot": "dinner",
     "prompt": "Swedish kåldolmar — cabbage rolls stuffed with beef and rice, simmered with a cream gravy, served with lingonberry and boiled potatoes."},
    {"category": "nordic", "cuisine": ["norwegian"], "dietary": [],            "time_min": 150, "slot": "dinner",
     "prompt": "Norwegian fårikål — bone-in lamb and cabbage slow-braised with whole peppercorns. Few ingredients; deep, comforting flavour."},

    # ---- Asian (10) ----
    {"category": "asian", "cuisine": ["thai"],       "dietary": [],            "time_min": 35, "slot": "dinner",
     "prompt": "Thai green chicken curry with bamboo shoots, Thai basil, kaffir lime leaves, and creamy coconut milk. Serve over jasmine rice."},
    {"category": "asian", "cuisine": ["japanese"],   "dietary": [],            "time_min": 45, "slot": "dinner",
     "prompt": "Japanese chicken karaage — soy-and-ginger marinated thigh, dredged in potato starch, double-fried for shatter-crisp edges. With shiso slaw and Kewpie."},
    {"category": "asian", "cuisine": ["indian"],     "dietary": [],            "time_min": 50, "slot": "dinner",
     "prompt": "Indian chicken tikka masala in a rich tomato-cream sauce with garam masala, fenugreek, and ginger. Basmati rice and warm naan."},
    {"category": "asian", "cuisine": ["vietnamese"], "dietary": [],            "time_min": 40, "slot": "dinner",
     "prompt": "Vietnamese bún chả — caramelised grilled pork patties over rice noodles with mountain of herbs, pickled vegetables, and nuoc cham dipping sauce."},
    {"category": "asian", "cuisine": ["chinese"],    "dietary": [],            "time_min": 30, "slot": "dinner",
     "prompt": "Sichuan kung pao chicken with dried red chili, Sichuan peppercorn for that numbing tingle, peanuts, scallion, and a glossy black-vinegar sauce."},
    {"category": "asian", "cuisine": ["korean"],     "dietary": [],            "time_min": 45, "slot": "dinner",
     "prompt": "Korean bibimbap with sesame-marinated beef bulgogi, an array of seasoned vegetables, a runny fried egg, and a generous spoon of gochujang."},
    {"category": "asian", "cuisine": ["thai"],       "dietary": [],            "time_min": 25, "slot": "dinner",
     "prompt": "Thai pad krapow gai — minced chicken stir-fried with garlic, bird's-eye chili, and Thai holy basil. Crown with a crisp-edged fried egg."},
    {"category": "asian", "cuisine": ["indian"],     "dietary": ["vegetarian"], "time_min": 40, "slot": "dinner",
     "prompt": "Indian palak paneer — cubes of fresh paneer in a smooth, spiced spinach gravy with ginger, garlic, and a swirl of cream."},
    {"category": "asian", "cuisine": ["japanese"],   "dietary": [],            "time_min": 30, "slot": "dinner",
     "prompt": "Japanese chicken teriyaki rice bowls with a glossy soy-mirin glaze, steamed rice, sesame broccoli, and pickled ginger."},
    {"category": "asian", "cuisine": ["indonesian"], "dietary": [],            "time_min": 30, "slot": "dinner",
     "prompt": "Indonesian nasi goreng with shrimp, kecap manis, fried shallots, prawn crackers, and a fried egg on top."},

    # ---- Vegetarian (10) ----
    {"category": "vegetarian", "cuisine": ["italian"],       "dietary": ["vegetarian"], "time_min": 50, "slot": "dinner",
     "prompt": "Creamy mushroom risotto with white wine, parmesan, a knob of butter for mantecatura, and a few drops of truffle oil. 4 servings."},
    {"category": "vegetarian", "cuisine": ["middle_eastern"],"dietary": ["vegetarian"], "time_min": 45, "slot": "dinner",
     "prompt": "Whole-roasted cauliflower steaks with tahini-lemon sauce, ruby pomegranate seeds, toasted almonds, and parsley."},
    {"category": "vegetarian", "cuisine": ["mexican"],       "dietary": ["vegetarian"], "time_min": 50, "slot": "dinner",
     "prompt": "Three-bean vegetarian chili with roasted poblano, smoked paprika, dark chocolate for depth, and a lime crema. Cornbread on the side."},
    {"category": "vegetarian", "cuisine": ["italian"],       "dietary": ["vegetarian"], "time_min": 75, "slot": "dinner",
     "prompt": "Eggplant parmigiana with crisp-edged eggplant, smoked mozzarella, basil-laced tomato sauce, baked until bubbling."},
    {"category": "vegetarian", "cuisine": ["italian"],       "dietary": ["vegetarian"], "time_min": 60, "slot": "dinner",
     "prompt": "Spinach-and-ricotta gnocchi with brown butter, crispy sage, and lots of parmesan. Pillow-soft, properly seasoned."},
    {"category": "vegetarian", "cuisine": ["indian"],        "dietary": ["vegetarian", "vegan"], "time_min": 45, "slot": "dinner",
     "prompt": "Red lentil and butternut squash dahl with coconut milk, ginger, mustard seeds, and a fresh coriander finish. Vegan."},
    {"category": "vegetarian", "cuisine": ["indian"],        "dietary": ["vegetarian"], "time_min": 60, "slot": "dinner",
     "prompt": "Vegetable biryani with saffron-soaked rice, layered spiced vegetables, fried onions, mint, and a cooling cucumber raita."},
    {"category": "vegetarian", "cuisine": ["italian"],       "dietary": ["vegetarian"], "time_min": 40, "slot": "dinner",
     "prompt": "Roasted butternut squash and sage pasta with brown butter, toasted hazelnuts, a grating of parmesan, and chili flakes."},
    {"category": "vegetarian", "cuisine": ["mexican"],       "dietary": ["vegetarian"], "time_min": 35, "slot": "dinner",
     "prompt": "Sweet potato and black bean tacos with chipotle crema, pickled red onion, and fresh coriander. Charred corn tortillas."},
    {"category": "vegetarian", "cuisine": ["greek"],         "dietary": ["vegetarian"], "time_min": 70, "slot": "dinner",
     "prompt": "Greek spanakopita — spinach, feta, dill, and spring onion baked between crackling layers of filo with melted butter."},

    # ---- Quick weeknight (10) ----
    {"category": "quick_weeknight", "cuisine": ["korean"],     "dietary": [],            "time_min": 20, "slot": "dinner",
     "prompt": "20-minute Korean ground beef bowls over rice with a soy-sesame glaze, quick-pickled cucumber, scallion, and toasted sesame."},
    {"category": "quick_weeknight", "cuisine": ["greek"],      "dietary": [],            "time_min": 35, "slot": "dinner",
     "prompt": "One-pan lemon-oregano chicken thighs with potatoes and red onion — everything roasts on one sheet, 35 minutes total."},
    {"category": "quick_weeknight", "cuisine": ["italian"],    "dietary": [],            "time_min": 15, "slot": "dinner",
     "prompt": "15-minute creamy garlic shrimp pasta with parsley, chili flakes, lemon zest, and parmesan. Genuinely fast, properly seasoned."},
    {"category": "quick_weeknight", "cuisine": ["japanese"],   "dietary": [],            "time_min": 25, "slot": "dinner",
     "prompt": "25-minute miso-glazed salmon over steamed rice with sesame broccoli. Glaze caramelises under the broiler."},
    {"category": "quick_weeknight", "cuisine": ["thai"],       "dietary": [],            "time_min": 25, "slot": "dinner",
     "prompt": "25-minute Thai-style chicken larb in cabbage cups — minced chicken with lime, fish sauce, toasted rice powder, mint and chili."},
    {"category": "quick_weeknight", "cuisine": ["indian"],     "dietary": ["vegetarian"], "time_min": 25, "slot": "dinner",
     "prompt": "25-minute chickpea curry with spinach, coconut milk, and warm spices. Pantry-friendly, vegan, served with basmati rice."},
    {"category": "quick_weeknight", "cuisine": ["italian"],    "dietary": ["vegetarian"], "time_min": 20, "slot": "lunch",
     "prompt": "20-minute caprese pasta salad with cherry tomato, fresh mozzarella, torn basil, balsamic glaze, and good olive oil. Eat warm or cold."},
    {"category": "quick_weeknight", "cuisine": ["mexican"],    "dietary": [],            "time_min": 25, "slot": "dinner",
     "prompt": "25-minute steak fajitas with charred bell pepper and onion, warm flour tortillas, lime, and a quick guacamole."},
    {"category": "quick_weeknight", "cuisine": ["greek"],      "dietary": ["vegetarian"], "time_min": 20, "slot": "lunch",
     "prompt": "20-minute halloumi and quinoa bowls with herbed yogurt, cucumber, cherry tomato, mint, and a lemon-olive-oil dressing."},
    {"category": "quick_weeknight", "cuisine": ["italian"],    "dietary": [],            "time_min": 30, "slot": "dinner",
     "prompt": "30-minute turkey and zucchini meatballs simmered in a quick marinara with basil, over spaghetti."},

    # ---- Batch-cook / matlåda (10) ----
    {"category": "batch_cook", "cuisine": ["french"],   "dietary": [],            "time_min": 180, "slot": "dinner",
     "prompt": "Slow-braised beef bourguignon with bacon lardons, pearl onions, mushrooms, and red wine. Cook Sunday, eats brilliantly over the next 4 days."},
    {"category": "batch_cook", "cuisine": ["indian"],   "dietary": ["vegetarian", "vegan"], "time_min": 60, "slot": "dinner",
     "prompt": "Big-batch chickpea, sweet potato, and coconut curry with spinach. Scales to 8 portions, freezes well, vegan."},
    {"category": "batch_cook", "cuisine": ["american"], "dietary": [],            "time_min": 240, "slot": "dinner",
     "prompt": "Slow-cooker pulled pork with a smoky BBQ sauce — sandwich filling that gets better through the week. Serve on brioche buns with slaw."},
    {"category": "batch_cook", "cuisine": ["spanish"],  "dietary": [],            "time_min": 60, "slot": "dinner",
     "prompt": "Hearty white bean and chorizo stew with smoked paprika, kale, and a sherry-vinegar finish. Crusty bread alongside. Meal-prep staple."},
    {"category": "batch_cook", "cuisine": ["mexican"],  "dietary": [],            "time_min": 75, "slot": "dinner",
     "prompt": "Slow-cooker shredded chicken tinga with chipotle, tomato, and oregano. A week of taco fillings, salad toppings, and rice-bowl protein."},
    {"category": "batch_cook", "cuisine": ["italian"],  "dietary": ["vegetarian"], "time_min": 75, "slot": "dinner",
     "prompt": "Vegetarian lentil bolognese with a soffritto base, plenty of mushrooms for umami, and red wine. Sauces a week of pasta or polenta."},
    {"category": "batch_cook", "cuisine": ["moroccan"], "dietary": [],            "time_min": 90, "slot": "dinner",
     "prompt": "Moroccan chicken tagine with dried apricot, preserved lemon, toasted almond, and warm spices. Served over fluffy couscous."},
    {"category": "batch_cook", "cuisine": ["american"], "dietary": [],            "time_min": 75, "slot": "dinner",
     "prompt": "Texas-style three-bean chili with chuck steak, ancho, and chipotle. Better on day two. Cornbread for sopping."},
    {"category": "batch_cook", "cuisine": ["greek"],    "dietary": [],            "time_min": 110, "slot": "dinner",
     "prompt": "Greek pastitsio — baked tubular pasta layered with cinnamon-and-clove-spiced lamb ragu and a thick béchamel. Cuts into proper portions."},
    {"category": "batch_cook", "cuisine": ["british"],  "dietary": [],            "time_min": 105, "slot": "dinner",
     "prompt": "Sunday roast chicken with crispy potatoes, glazed carrots, and a pan-gravy. Leftover chicken becomes sandwiches and soup the rest of the week."},
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "seeds" / "starter_recipes.json"
# Default concurrency tuned for OpenAI gpt-4o-mini's 200k TPM: three parallel
# recipe gens (each consuming ~30-60k tokens once tool-call history accumulates)
# blew the limit on the first run. Two is the safe ceiling.
CONCURRENCY = int(os.getenv("CORPUS_GEN_CONCURRENCY", "2"))


async def _gen_one(idx: int, total: int, entry: dict, sem: asyncio.Semaphore) -> dict | None:
    """Generate one recipe. Retries OpenAI 429s (TPM) with exponential backoff."""
    async with sem:
        t0 = time.monotonic()
        attempt = 0
        backoffs = (8, 20, 45, 90)  # seconds — enough to clear a 200k-TPM window
        while True:
            try:
                r = await generate_recipe(entry["prompt"])
                break
            except Exception as e:
                msg = str(e)
                rate_limited = "429" in msg or "rate_limit" in msg.lower()
                if rate_limited and attempt < len(backoffs):
                    delay = backoffs[attempt]
                    print(f"[{idx:2d}/{total}] 429 — retry in {delay}s ({entry['category']})")
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                print(f"[{idx:2d}/{total}] FAIL ({entry['category']}): {e}")
                return None
        duration = time.monotonic() - t0
        print(f"[{idx:2d}/{total}] ({duration:5.1f}s) [{entry['category']:>15}] {r.name}")
        return {
            "category":    entry["category"],
            "cuisine":     entry["cuisine"],
            "dietary":     entry["dietary"],
            "time_min":    entry["time_min"],
            "slot":        entry["slot"],
            "source_prompt": entry["prompt"],
            "name":        r.name,
            "ingredients": [
                {"fdc_id": i.fdc_id, "name": i.name, "quantity_g": i.quantity_g}
                for i in r.ingredients
            ],
            "instructions": r.instructions,
        }


async def main() -> None:
    OUTPUT_PATH.parent.mkdir(exist_ok=True)

    # Resume support: load any recipes already in the JSON. Prompts whose
    # source_prompt is already present are skipped; we only generate the gaps.
    existing: list[dict] = []
    existing_prompts: set[str] = set()
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            existing_prompts = {r["source_prompt"] for r in existing if "source_prompt" in r}
        except Exception:
            existing = []

    todo = [p for p in PROMPTS if p["prompt"] not in existing_prompts]
    if not todo:
        print(f"All {len(PROMPTS)} prompts already covered in {OUTPUT_PATH.name}. Nothing to do.")
        return

    await init_pool()
    try:
        sem = asyncio.Semaphore(CONCURRENCY)
        total = len(todo)
        print(
            f"Generating {total} recipes (concurrency={CONCURRENCY}, "
            f"resuming with {len(existing)} already in {OUTPUT_PATH.name})"
        )
        print("-" * 80)

        overall = time.monotonic()
        tasks = [_gen_one(i + 1, total, p, sem) for i, p in enumerate(todo)]
        results = await asyncio.gather(*tasks)
        new_recipes = [r for r in results if r is not None]
        elapsed = time.monotonic() - overall

        corpus = existing + new_recipes
        OUTPUT_PATH.write_text(json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")
        print("-" * 80)
        print(
            f"Added {len(new_recipes)}/{total} new recipes in {elapsed:.0f}s "
            f"({len(corpus)} total in corpus) -> {OUTPUT_PATH}"
        )
        if len(new_recipes) < total:
            print(f"  {total - len(new_recipes)} prompts failed; re-run later to retry them.")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
