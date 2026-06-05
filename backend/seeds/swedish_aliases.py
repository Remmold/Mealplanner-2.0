"""Swedish ingredient -> USDA fdc_id alias table.

Two layers:
  EN_TO_FDC: canonical English label -> verified USDA fdc_id (one entry per food)
  SV_TO_EN: Swedish surface form (incl. plurals & common preparations) -> EN key

Compose with build_sv_to_fdc() to get the flat {swedish: fdc_id} table the
ingest pipeline consumes.

All fdc_id picks below were selected by hand from USDA's catalogue, preferring:
  - Foundation Foods or SR Legacy over Branded
  - "raw" / "fresh" / "uncooked" forms over prepared variants
  - shortest, simplest description that matches the food
  - no all-caps brand prefix (DENNY'S, KRAFT, etc.)

Run _validate_swedish_aliases.py after editing to confirm every fdc_id still
resolves to its expected description in hearth.usda_ingredients."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Layer 1: canonical English food -> USDA fdc_id
# ---------------------------------------------------------------------------
EN_TO_FDC: dict[str, int] = {
    # ── pantry essentials ──────────────────────────────────────────────────
    "salt":               173468,  # Salt, table
    "black pepper":       170931,  # Spices, pepper, black
    "white pepper":       170933,  # Spices, pepper, white
    "olive oil":          171413,  # Oil, olive, salad or cooking
    "canola oil":         172336,  # Oil, canola
    "vegetable oil":      172336,  # Oil, canola (Swedish default oil = rapsolja)
    "sesame oil":         171016,  # Oil, sesame, salad or cooking
    "coconut oil":        171412,  # Oil, coconut
    "butter":             173410,  # Butter, salted
    "margarine":          172347,  # Margarine, regular, 80% fat, composite, tub, with salt
    "water":              174158,  # Water, bottled, generic
    "sugar granulated":   169655,  # Sugars, granulated
    "sugar powdered":     169656,  # Sugars, powdered
    "sugar brown":        168833,  # Sugars, brown
    "honey":              169640,  # Honey
    "maple syrup":        169661,  # Syrups, maple
    "vanilla extract":    173471,  # Vanilla extract
    "vanilla sugar":      169655,  # closest = granulated sugar (USDA has no vanilla sugar)
    "wheat flour":        168894,  # Wheat flour, white, all-purpose, enriched, bleached
    "cornstarch":         169698,  # Cornstarch
    "potato flour":       168446,  # Potato flour
    "baking powder":      172804,  # Leavening agents, baking powder, double-acting, straight phosphate
    "baking soda":        175040,  # Leavening agents, baking soda
    "yeast dry":          175043,  # Leavening agents, yeast, baker's, active dry
    "breadcrumbs":        174924,  # Bread, white, commercially prepared (incl. soft bread crumbs)
    "panko":              174924,  # closest: white bread crumbs
    "bread":              172686,  # Bread, wheat
    "ice":                174158,  # frozen water = use water

    # ── spices & dried herbs ───────────────────────────────────────────────
    "cumin":              170923,  # Spices, cumin seed
    "ground cumin":       170923,
    "oregano dried":      171328,  # Spices, oregano, dried
    "thyme dried":        170938,  # Spices, thyme, dried
    "basil dried":        171317,  # Spices, basil, dried
    "rosemary dried":     171333,  # Spices, rosemary, dried
    "paprika":            171329,  # Spices, paprika
    "cinnamon":           171320,  # Spices, cinnamon, ground
    "cardamom":           170919,  # Spices, cardamom
    "nutmeg":             171326,  # Spices, nutmeg, ground
    "ginger dried":       170926,  # Spices, ginger, ground
    "turmeric":           172231,  # Spices, turmeric, ground
    "chili powder":       171319,  # Spices, chili powder
    "cayenne":            170932,  # Spices, pepper, red or cayenne
    "bay leaf":           170917,  # Spices, bay leaf
    "saffron":            170934,  # Spices, saffron
    "curry powder":       170924,  # Spices, curry powder
    "allspice":           171315,  # Spices, allspice, ground
    "anise":              171316,  # Spices, anise seed
    "fennel seed":        171323,  # Spices, fennel seed
    "caraway":            170918,  # Spices, caraway seed
    "cloves":             171321,  # Spices, cloves, ground
    "garlic powder":      171325,  # Spices, garlic powder
    "onion powder":       171327,  # Spices, onion powder
    "tarragon":           170937,  # Spices, tarragon, dried
    "marjoram":           170928,  # Spices, marjoram, dried
    "star anise":         171316,  # closest = anise seed
    "sage":               170935,  # Spices, sage, ground

    # ── fresh herbs ────────────────────────────────────────────────────────
    "parsley fresh":      170416,  # Parsley, fresh
    "cilantro fresh":     169997,  # Coriander (cilantro) leaves, raw
    "basil fresh":        172232,  # Basil, fresh
    "thyme fresh":        173470,  # Thyme, fresh
    "rosemary fresh":     173473,  # Rosemary, fresh
    "dill fresh":         172233,  # Dill weed, fresh
    "chives":             169994,  # Chives, raw
    "mint":               173474,  # Peppermint, fresh
    "tarragon fresh":     170937,  # closest = dried (no fresh tarragon in USDA)

    # ── vegetables ─────────────────────────────────────────────────────────
    "onion yellow":       170000,  # Onions, raw
    "onion red":          170008,  # Onions, sweet, raw (closest USDA to red — no plain red onion)
    "shallot":            170499,  # Shallots, raw
    "scallion":           170006,  # Onions, young green, tops only
    "garlic":             169230,  # Garlic, raw
    "leek":               169246,  # Leeks, (bulb and lower leaf-portion), raw
    "potato":             170032,  # Potatoes, raw, skin
    "sweet potato":       168482,  # Sweet potato, raw, unprepared
    "carrot":             170393,  # Carrots, raw
    "celery":             169988,  # Celery, raw
    "celeriac":           170400,  # Celeriac, raw
    "parsnip":            170417,  # Parsnips, raw
    "beetroot":           169145,  # Beets, raw
    "tomato":             170457,  # Tomatoes, red, ripe, raw, year round average
    "cherry tomato":      170457,  # USDA has no separate cherry — use raw tomato
    "canned tomato":      170501,  # Tomatoes, crushed, canned
    "tomato paste":       170459,  # Tomato products, canned, paste
    "tomato sauce":       170054,  # Tomato products, canned, sauce
    "tomato puree":       170055,  # Tomato products, canned, puree
    "passata":            170055,  # = puree, same fdc
    "sun-dried tomato":   168567,  # Tomatoes, sun-dried
    "cucumber":           169225,  # Cucumber, peeled, raw
    "bell pepper red":    170108,  # Peppers, sweet, red, raw
    "bell pepper green":  170427,  # Peppers, sweet, green, raw
    "bell pepper yellow": 169383,  # Peppers, sweet, yellow, raw
    "chili pepper":       170106,  # Peppers, hot chili, red, raw
    "jalapeno":           168576,  # Peppers, jalapeno, raw
    "mushroom button":    169251,  # Mushrooms, white, raw
    "mushroom portobello":169255,  # Mushrooms, portabella, raw
    "mushroom chanterelle":168422, # Mushrooms, Chanterelle, raw
    "mushroom shiitake":  169242,  # Mushrooms, shiitake, raw
    "spinach":            168462,  # Spinach, raw
    "kale":               168421,  # Kale, raw
    "lettuce":            169249,  # Lettuce, green leaf, raw
    "arugula":            169387,  # Arugula, raw
    "romaine":            169247,  # Lettuce, cos or romaine, raw
    "iceberg":            169248,  # Lettuce, iceberg (incl crisphead types), raw
    "lamb's lettuce":     169247,  # closest = romaine
    "broccoli":           170379,  # Broccoli, raw
    "cauliflower":        169986,  # Cauliflower, raw
    "cabbage":            169975,  # Cabbage, raw
    "red cabbage":        169977,  # Cabbage, red, raw
    "brussels sprouts":   170383,  # Brussels sprouts, raw
    "zucchini":           169291,  # Squash, summer, zucchini, includes skin, raw
    "eggplant":           169228,  # Eggplant, raw
    "avocado":            171705,  # Avocados, raw, all commercial varieties
    "fennel":             169994,  # closest = chives (no fennel-bulb in USDA? — fallback)
    "asparagus green":    168389,  # Asparagus, raw
    "peas frozen":        170016,  # Peas, green, frozen, unprepared
    "peas fresh":         170419,  # Peas, green, raw
    "snap peas":          170010,  # Peas, edible-podded, raw
    "corn":               169998,  # Corn, sweet, yellow, raw
    "corn canned":        169998,  # closest = corn raw (USDA canned variant is branded-heavy)
    "olives black":       169094,  # Olives, ripe, canned (small-extra large)
    "olives green":       169096,  # Olives, pickled, canned or bottled, green
    "capers":             172238,  # Capers, canned
    "radish":             169276,  # Radishes, raw
    "horseradish":        173472,  # Horseradish, prepared
    "pumpkin":            168448,  # Pumpkin, raw

    # ── fruits & berries ───────────────────────────────────────────────────
    "apple":              171689,  # Apples, raw, without skin
    "pear":               169118,  # Pears, raw
    "banana":             173944,  # Bananas, raw
    "orange":             169097,  # Oranges, raw, all commercial varieties
    "lemon":              167746,  # Lemons, raw, without peel
    "lemon juice":        167747,  # Lemon juice, raw
    "lemon zest":         167746,  # use lemon (no separate zest in USDA we hit)
    "lime":               168155,  # Limes, raw
    "lime juice":         168156,  # Lime juice, raw
    "strawberry":         167762,  # Strawberries, raw
    "blueberry":          171711,  # Blueberries, raw
    "raspberry":          167755,  # Raspberries, raw
    "blackberry":         173946,  # Blackberries, raw
    "currant black":      173963,  # Currants, european black, raw
    "currant red":        173964,  # Currants, red and white, raw
    "lingonberry":        171722,  # closest = Cranberries, raw (USDA has no lingonberry)
    "cranberry":          171722,  # Cranberries, raw
    "cherry":             171719,  # Cherries, sweet, raw
    "peach":              169928,  # Peaches, yellow, raw
    "apricot":             171697,  # Apricots, raw
    "apricot dried":      173941,  # Apricots, dried, sulfured, uncooked
    "plum":               169949,  # Plums, raw
    "prune":              168162,  # Plums, dried (prunes), uncooked
    "grape":              174683,  # Grapes, red or green, raw, European type
    "pineapple":          169124,  # Pineapple, raw, all varieties
    "mango":              169910,  # Mangos, raw
    "kiwi":               168153,  # Kiwifruit, green, raw
    "raisin":             168165,  # Raisins, dark, seedless (cleanest plain raisin)
    "date":               168191,  # Dates, medjool
    "mixed berries":      167762,  # placeholder = strawberries
    "fig":                173021,  # Figs, raw
    "artichoke":          169205,  # Artichokes, (globe or french), raw
    "green beans":        169961,  # Beans, snap, green, raw

    # ── dairy & eggs ───────────────────────────────────────────────────────
    "egg":                171287,  # Egg, whole, raw, fresh
    "egg yolk":           172184,  # Egg, yolk, raw, fresh
    "egg white":          172183,  # Egg, white, raw, fresh
    "milk":               171265,  # Milk, whole, 3.25% milkfat, with added vitamin D
    "milk lowfat":        171266,  # Milk, lowfat, fluid, 1% milkfat (closest 2%/1%)
    "buttermilk":         170874,  # Milk, buttermilk, fluid, cultured, lowfat
    "cream heavy":        170859,  # Cream, fluid, heavy whipping
    "cream light":        170858,  # Cream, fluid, light whipping
    "cream half and half":171255,  # Cream, fluid, half and half
    "cream sour":         171257,  # Cream, sour, cultured
    "creme fraiche":      171257,  # closest USDA = sour cream cultured
    "smetana":            171257,  # Russian sour cream = same fdc
    "yogurt plain":       170886,  # Yogurt, plain, low fat
    "yogurt greek":       170903,  # Yogurt, Greek, plain, lowfat
    "yogurt fruit":       169898,  # Yogurt, fruit variety, nonfat
    "yogurt turkish":     170886,  # closest = plain low fat
    "cheese generic":     170848,  # Cheese, parmesan, hard (default "ost")
    "cheese cheddar":     173414,  # Cheese, cheddar (FDP)
    "cheese mozzarella":  170847,  # Cheese, mozzarella, part skim milk
    "cheese feta":        173420,  # Cheese, feta
    "cheese parmesan":    170848,  # Cheese, parmesan, hard
    "cheese brie":        172177,  # Cheese, brie
    "cheese blue":        172175,  # Cheese, blue
    "cheese cream":       173418,  # Cheese, cream
    "cheese goat":        171249,  # Cheese, goat, semisoft type
    "cheese cottage":     170851,  # Cheese, cottage, lowfat, 2% milkfat
    "cheese halloumi":    170848,  # closest = parmesan hard (no halloumi)
    "cheese vasterbotten":170848,  # Swedish hard cheese ≈ parmesan
    "quark":              170851,  # closest = cottage cheese lowfat

    # ── meat & poultry ─────────────────────────────────────────────────────
    "chicken breast":     171477,  # Chicken, broilers or fryers, breast, meat only, raw
    "chicken thigh":      172383,  # Chicken, broilers or fryers, thigh, meat only, raw
    "chicken whole":      171464,  # Chicken, broilers or fryers, meat and skin, raw
    "chicken ground":     172850,  # Chicken, ground, raw
    "chicken drumstick":  173614,  # Chicken, broilers or fryers, dark meat, drumstick, meat only, raw
    "chicken wing":       173632,  # Chicken, broilers or fryers, wing, meat only, raw
    "turkey breast":      171098,  # Turkey, whole, breast, meat only, raw
    "turkey ground":      171505,  # Turkey, Ground, raw
    "duck":               172410,  # Duck, domesticated, meat only, raw
    "pork chop":          168251,  # Pork, fresh, loin, top loin (chops), boneless, lean only, raw
    "pork tenderloin":    168249,  # Pork, fresh, loin, tenderloin, lean only, raw
    "pork shoulder":      167845,  # Pork, fresh, shoulder, whole, lean only, raw
    "pork belly":         167812,  # Pork, fresh, belly, raw
    "pork steak":         168260,  # Pork, fresh, shoulder (Boston butt), blade steaks, lean only, raw
    "pork cured loin":    168277,  # closest = bacon (no plain cured-loin in USDA)
    "beef tenderloin":    169547,  # Beef, tenderloin, lean and fat, trimmed to 1/8" fat, prime, raw
    "beef rib short":     168614,  # Beef, rib, shortribs, lean only, choice, raw
    "beef chuck stew":    170810,  # Beef, chuck for stew, lean and fat, choice, raw
    "beef brisket":       168607,  # Beef, brisket, whole, lean only, all grades, raw
    "lamb chop":          172517,  # Lamb, NZ imported, loin chop, lean and fat, raw
    "lamb shoulder":      174330,  # Lamb, shoulder, arm, lean only, trimmed to 1/4" fat, choice, raw
    "lamb leg":           172486,  # Lamb, leg, shank half, lean only, trimmed to 1/4" fat, choice, raw
    "venison":            173855,  # Game meat, deer, raw
    "salmon wild":        173686,  # Fish, salmon, Atlantic, wild, raw
    "salmon smoked":      173687,  # Fish, salmon, chinook, smoked
    "salmon lox":         171985,  # Fish, salmon, chinook, smoked, (lox), regular
    "white fish":         171964,  # Fish, haddock, raw (closest to "vit fisk")
    "tuna canned water":  173709,  # Fish, tuna, light, canned in water, drained
    "crab":               174204,  # Crustaceans, crab, blue, raw
    "scallop":            174220,  # Mollusks, scallop, mixed species, raw
    "oyster":             174219,  # Mollusks, oyster, Pacific, raw
    "tofu firm":          172475,  # Tofu, raw, firm, prepared with calcium sulfate
    "tempeh":             174272,  # Tempeh
    "seitan":             168147,  # Vital wheat gluten
    "ground beef":        173110,  # Beef, ground, 93% lean meat / 7% fat, raw
    "beef steak":         168609,  # Beef, flank, steak, raw (representative)
    "beef sirloin":       174763,  # Beef, top sirloin, steak, lean only, raw
    "pork loin":          168230,  # Pork, fresh, loin, whole, separable lean only, raw
    "ground pork":        169190,  # Pork, ground, 96% lean / 4% fat, raw
    "bacon":              168277,  # Pork, cured, bacon, unprepared
    "ham":                173864,  # Ham, sliced, regular (approximately 11% fat)
    "sausage pork":       172934,  # Pork sausage, link/patty, unprepared
    "frankfurter":        172968,  # Frankfurter, meat
    "meatball generic":   171638,  # Meatballs, frozen, Italian style (closest pre-made)
    "lamb":               174370,  # Lamb, ground, raw
    "moose":              175301,  # closest = Game meat, elk, raw
    "reindeer":           175301,  # closest = elk
    "liver pate":         172967,  # Pate, truffle flavor (closest)

    # ── fish & shellfish ───────────────────────────────────────────────────
    "salmon":             175167,  # Fish, salmon, Atlantic, farmed, raw
    "cod":                171955,  # Fish, cod, Atlantic, raw
    "tuna fresh":         173706,  # Fish, tuna, fresh, bluefin, raw
    "tuna canned":        173708,  # Fish, tuna, light, canned in oil, drained
    "shrimp":             175179,  # Crustaceans, shrimp, raw
    "herring":            173668,  # Fish, herring, Atlantic, raw
    "mackerel":           175119,  # Fish, mackerel, Atlantic, raw
    "trout":              175153,  # Fish, trout, mixed species, raw
    "pollock":            173725,  # Fish, pollock, Alaska, raw
    "pike walleye":       175128,  # Fish, pike, walleye, raw
    "anchovy":            174182,  # Fish, anchovy, european, raw
    "sardine":            175139,  # Fish, sardine, Atlantic, canned in oil, drained
    "caviar":             174188,  # Fish, caviar, black and red, granular
    "crayfish":           174206,  # Crustaceans, crayfish, mixed species, wild, raw
    "mussel":             174216,  # Mollusks, mussel, blue, raw

    # ── grains, pasta, legumes ────────────────────────────────────────────
    "rice white":         168877,  # Rice, white, long-grain, regular, raw, enriched
    "rice brown":         169704,  # Rice, brown, long-grain, raw
    "pasta dry":          169736,  # Pasta, dry, enriched
    "spaghetti dry":      169736,  # = pasta dry
    "noodles":            169736,  # = pasta dry
    "couscous":           169699,  # Couscous, dry
    "bulgur":             170688,  # Bulgur, dry
    "quinoa":             168874,  # Quinoa, uncooked
    "oats":               173904,  # Cereals, oats, regular and quick, not fortified, dry
    "polenta":            169697,  # Cornmeal, whole-grain, yellow
    "tortilla":           175037,  # Tortillas, ready-to-bake or -fry, flour, refrigerated
    "lentils dry":        172420,  # Lentils, raw
    "chickpeas raw":      173756,  # Chickpeas, mature seeds, raw
    "chickpeas cooked":   173799,  # Chickpeas, mature seeds, cooked, boiled, with salt
    "black beans":        173734,  # Beans, black, mature seeds, raw
    "kidney beans":       173744,  # Beans, kidney, red, mature seeds, raw
    "white beans":        175202,  # Beans, white, mature seeds, raw
    "soybeans":           174270,  # Soybeans, mature seeds, raw
    "tofu":               172476,  # Tofu, raw, regular, prepared with calcium sulfate

    # ── nuts & seeds ──────────────────────────────────────────────────────
    "almond":             170567,  # Nuts, almonds
    "walnut":             170187,  # Nuts, walnuts, english
    "hazelnut":           170581,  # Nuts, hazelnuts or filberts
    "pecan":              170182,  # Nuts, pecans
    "cashew":             170162,  # Nuts, cashew nuts, raw
    "pistachio":          170184,  # Nuts, pistachio nuts, raw
    "macadamia":          170178,  # Nuts, macadamia nuts, raw
    "pine nut":           170591,  # Nuts, pine nuts, dried
    "peanut":             172430,  # Peanuts, all types, raw
    "chia seed":          170554,  # Seeds, chia seeds, dried
    "sunflower seed":     170562,  # Seeds, sunflower seed kernels, dried
    "sesame seed":        170150,  # Seeds, sesame seeds, whole, dried
    "pumpkin seed":       170556,  # Seeds, pumpkin and squash seed kernels, dried
    "flaxseed":           169414,  # Seeds, flaxseed
    "almond flour":       168588,  # Nuts, almond butter, plain, without salt (closest)
    "peanut butter":      172470,  # Peanut butter, smooth style, without salt
    "tahini":             170191,  # Seeds, sesame butter, paste (tahini)
    "coconut shredded":   170169,  # Nuts, coconut meat, dried (desiccated, not sweetened)
    "coconut milk":       170173,  # Nuts, coconut milk, canned
    "coconut cream":      170580,  # Nuts, coconut cream, raw

    # ── sauces, vinegars, condiments ──────────────────────────────────────
    "vinegar white":      172237,  # Vinegar, distilled
    "vinegar red wine":   172240,  # Vinegar, red wine
    "vinegar white wine": 172237,  # closest = distilled (USDA missing white-wine variant)
    "vinegar cider":      173469,  # Vinegar, cider
    "vinegar balsamic":   172241,  # Vinegar, balsamic
    "vinegar rice":       172237,  # closest = distilled
    "soy sauce":          174277,  # Soy sauce made from hydrolyzed vegetable protein
    "fish sauce":         174531,  # Sauce, fish, ready-to-serve
    "worcestershire":     171610,  # Sauce, worcestershire
    "sriracha":           171186,  # Sauce, hot chile, sriracha
    "sambal oelek":       171186,  # closest = sriracha (no separate sambal)
    "sweet chili sauce":  171186,  # closest = sriracha
    "ketchup":            168556,  # Catsup
    "mustard dijon":      172234,  # Mustard, prepared, yellow (closest; no separate dijon)
    "mustard yellow":     172234,  # Mustard, prepared, yellow
    "mayonnaise":         171443,  # Mayonnaise, reduced fat, with olive oil (cleanest non-branded)
    "hummus":             174289,  # Hummus, commercial
    "tabasco":            174528,  # Sauce, ready-to-serve, pepper, TABASCO

    # ── alcohol & misc beverages ──────────────────────────────────────────
    "white wine":         174837,  # Alcoholic beverage, wine, table, white
    "red wine":           173190,  # Alcoholic beverage, wine, table, red
    "beer":               168746,  # Alcoholic beverage, beer, regular, all
    "rum":                174817,  # Alcoholic beverage, distilled, rum, 80 proof
    "vodka":              174818,  # Alcoholic beverage, distilled, vodka, 80 proof
    "orange juice":       169098,  # Orange juice, raw
    "apple juice":        173933,  # Apple juice, canned, unsweetened, w/o ascorbic
    "sparkling water":    174158,  # = water generic

    # ── stocks & broths ────────────────────────────────────────────────────
    "chicken stock":      172884,  # Soup, stock, chicken, home-prepared
    "beef stock":         172883,  # Soup, stock, beef, home-prepared
    "vegetable stock":    171163,  # Soup, vegetable beef, canned (no plain veg stock in USDA)
    "fish stock":         172884,  # closest = chicken stock (no fish stock in USDA)

    # ── chocolate & sweets ────────────────────────────────────────────────
    "dark chocolate":     167976,  # Candies, semisweet chocolate (cleanest plain dark)
    "milk chocolate":     167587,  # Candies, milk chocolate
    "white chocolate":    167571,  # Candies, white chocolate
    "chocolate chips":    167976,  # Candies, semisweet chocolate (chips)
    "cocoa powder":       169593,  # Cocoa, dry powder, unsweetened
    "jam":                169641,  # Jams and preserves
    "marmalade":          168819,  # Marmalade, orange
    "applesauce":         167773,  # Applesauce, canned, sweetened, with salt
    "vanilla ice cream":  167575,  # Ice creams, vanilla
    "ice cream":          167575,  # = vanilla ice cream as generic

    # ── meat substitutes / other ──────────────────────────────────────────
    "vegetable broth cube":171163, # closest fallback = veg beef soup
}


# ---------------------------------------------------------------------------
# Layer 2: Swedish surface form -> canonical English key
#
# Covers the top ~250 entries in seeds/swedish_ingredient_freq.json, including
# common plurals, preparation prefixes that survived normalization, and
# regional variants.
# ---------------------------------------------------------------------------
SV_TO_EN: dict[str, str] = {
    # pantry essentials
    "salt": "salt",
    "flingsalt": "salt",
    "havssalt": "salt",
    "peppar": "black pepper",
    "svartpeppar": "black pepper",
    "nymalen svartpeppar": "black pepper",
    "grovmalen svartpeppar": "black pepper",
    "vitpeppar": "white pepper",
    "olja": "canola oil",
    "matolja": "canola oil",
    "neutral olja": "canola oil",
    "rapsolja": "canola oil",
    "olivolja": "olive oil",
    "sesamolja": "sesame oil",
    "kokosolja": "coconut oil",
    "smör": "butter",
    "rumsvarmt smör": "butter",
    "rumstempererat smör": "butter",
    "smör till stekning": "butter",
    "margarin": "margarine",
    "vatten": "water",
    "kallt vatten": "water",
    "kokande vatten": "water",
    "is": "ice",
    "socker": "sugar granulated",
    "strösocker": "sugar granulated",
    "råsocker": "sugar brown",
    "farinsocker": "sugar brown",
    "muscovadosocker": "sugar brown",
    "florsocker": "sugar powdered",
    "puddersocker": "sugar powdered",
    "vaniljsocker": "vanilla sugar",
    "vaniljpulver": "vanilla extract",
    "vaniljstång": "vanilla extract",
    "vaniljextrakt": "vanilla extract",
    "honung": "honey",
    "flytande honung": "honey",
    "lönnsirap": "maple syrup",
    "ljus sirap": "maple syrup",
    "sirap": "maple syrup",
    # flours & starches
    "vetemjöl": "wheat flour",
    "mjöl": "wheat flour",
    "majsstärkelse": "cornstarch",
    "potatismjöl": "potato flour",
    "bakpulver": "baking powder",
    "bikarbonat": "baking soda",
    "natriumbikarbonat": "baking soda",
    "jäst": "yeast dry",
    "färsk jäst": "yeast dry",
    "torrjäst": "yeast dry",
    "ströbröd": "breadcrumbs",
    "panko": "panko",
    "bröd": "bread",
    "tortillabröd": "tortilla",
    "pitabröd": "bread",
    "hamburgerbröd": "bread",
    "sourdoughbröd": "bread",

    # spices
    "spiskummin": "cumin",
    "malen spiskummin": "cumin",
    "oregano": "oregano dried",
    "timjan": "thyme fresh",
    "torkad timjan": "thyme dried",
    "basilika": "basil fresh",
    "torkad basilika": "basil dried",
    "rosmarin": "rosemary fresh",
    "torkad rosmarin": "rosemary dried",
    "paprikapulver": "paprika",
    "rökt paprikapulver": "paprika",
    "kanel": "cinnamon",
    "malen kanel": "cinnamon",
    "kanelstång": "cinnamon",
    "kardemumma": "cardamom",
    "stötta kardemumma": "cardamom",
    "muskot": "nutmeg",
    "ingefära": "ginger dried",
    "färsk ingefära": "ginger dried",
    "torkad ingefära": "ginger dried",
    "gurkmeja": "turmeric",
    "chiliflakes": "chili powder",
    "chilipulver": "chili powder",
    "kajennpeppar": "cayenne",
    "cayennepeppar": "cayenne",
    "lagerblad": "bay leaf",
    "saffran": "saffron",
    "curry": "curry powder",
    "kryddpeppar": "allspice",
    "fänkålsfrön": "fennel seed",
    "kummin": "caraway",
    "nejlikor": "cloves",
    "anis": "anise",
    "stjärnanis": "star anise",
    "vitlökspulver": "garlic powder",
    "lökpulver": "onion powder",
    "dragon": "tarragon",
    "mejram": "marjoram",

    # fresh herbs
    "persilja": "parsley fresh",
    "bladpersilja": "parsley fresh",
    "koriander": "cilantro fresh",
    "färsk koriander": "cilantro fresh",
    "malen koriander": "cilantro fresh",  # debatable; coriander seed vs leaves
    "dill": "dill fresh",
    "färsk dill": "dill fresh",
    "gräslök": "chives",
    "mynta": "mint",
    "färsk mynta": "mint",

    # vegetables — onion family
    "gul lök": "onion yellow",
    "gula lökar": "onion yellow",
    "lök": "onion yellow",
    "stor lök": "onion yellow",
    "stor gul lök": "onion yellow",
    "rödlök": "onion red",
    "rödlökar": "onion red",
    "silverlök": "onion yellow",
    "schalottenlök": "shallot",
    "schalottenlökar": "shallot",
    "salladslök": "scallion",
    "salladslökar": "scallion",
    "vitlök": "garlic",
    "vitlöksklyfta": "garlic",
    "vitlöksklyftor": "garlic",
    "pressad vitlöksklyfta": "garlic",
    "purjolök": "leek",
    "purjolökar": "leek",

    # vegetables — root / tubers
    "potatis": "potato",
    "potatisar": "potato",
    "fast potatis": "potato",
    "färskpotatis": "potato",
    "mjölig potatis": "potato",
    "sötpotatis": "sweet potato",
    "morötter": "carrot",
    "morot": "carrot",
    "rotselleri": "celeriac",
    "selleri": "celery",
    "palsternackor": "parsnip",
    "palsternacka": "parsnip",
    "rödbetor": "beetroot",
    "rödbeta": "beetroot",

    # vegetables — tomatoes
    "tomater": "tomato",
    "tomat": "tomato",
    "körsbärstomater": "cherry tomato",
    "plommontomater": "tomato",
    "passerade tomater": "canned tomato",
    "krossade tomater": "canned tomato",
    "krossad tomat": "canned tomato",
    "tomatpuré": "tomato paste",
    "tomatpassata": "tomato puree",
    "soltorkade tomater": "sun-dried tomato",

    # vegetables — other
    "gurka": "cucumber",
    "stor gurka": "cucumber",
    "röd paprika": "bell pepper red",
    "röda paprikor": "bell pepper red",
    "gul paprika": "bell pepper yellow",
    "grön paprika": "bell pepper green",
    "paprika": "bell pepper red",  # default red unless qualified
    "röd chili": "chili pepper",
    "röd chilifrukt": "chili pepper",
    "chilifrukt": "chili pepper",
    "jalapeño": "jalapeno",
    "champinjoner": "mushroom button",
    "champinjon": "mushroom button",
    "kantareller": "mushroom chanterelle",
    "shiitake": "mushroom shiitake",
    "portobellosvamp": "mushroom portobello",
    "spenat": "spinach",
    "babyspenat": "spinach",
    "bladspenat": "spinach",
    "grönkål": "kale",
    "sallad": "lettuce",
    "isbergssallad": "iceberg",
    "krispsallad": "iceberg",
    "romansallad": "romaine",
    "hjärtsallad": "romaine",
    "rucola": "arugula",
    "mâchesallad": "lamb's lettuce",
    "broccoli": "broccoli",
    "blomkål": "cauliflower",
    "vitkål": "cabbage",
    "rödkål": "red cabbage",
    "brysselkål": "brussels sprouts",
    "zucchini": "zucchini",
    "aubergine": "eggplant",
    "auberginer": "eggplant",
    "avokado": "avocado",
    "avokador": "avocado",
    "mogen avokado": "avocado",
    "fänkål": "fennel",
    "grön sparris": "asparagus green",
    "sparris": "asparagus green",
    "haricots verts": "green beans",
    "gröna bönor": "green beans",
    "haricot verts": "green beans",
    "brytbönor": "green beans",
    "gröna ärtor": "peas fresh",
    "ärtor": "peas fresh",
    "frysta ärtor": "peas frozen",
    "sockerärtor": "snap peas",
    "majskorn": "corn",
    "majs": "corn",
    "rädisor": "radish",
    "pepparrot": "horseradish",
    "pumpa": "pumpkin",
    "svarta oliver": "olives black",
    "gröna oliver": "olives green",
    "kapris": "capers",

    # fruits & berries
    "äpple": "apple",
    "äpplen": "apple",
    "päron": "pear",
    "banan": "banana",
    "bananer": "banana",
    "apelsin": "orange",
    "apelsiner": "orange",
    "citron": "lemon",
    "citroner": "lemon",
    "färskpressad citronjuice": "lemon juice",
    "citronjuice": "lemon juice",
    "citronsaft": "lemon juice",
    "pressad citronjuice": "lemon juice",
    "finrivet citronskal": "lemon zest",
    "citronskal": "lemon zest",
    "lime": "lime",
    "färskpressad limejuice": "lime juice",
    "limejuice": "lime juice",
    "limesaft": "lime juice",
    "jordgubbar": "strawberry",
    "jordgubbe": "strawberry",
    "blåbär": "blueberry",
    "hallon": "raspberry",
    "björnbär": "blackberry",
    "svarta vinbär": "currant black",
    "röda vinbär": "currant red",
    "lingon": "lingonberry",
    "tranbär": "cranberry",
    "körsbär": "cherry",
    "persikor": "peach",
    "persika": "peach",
    "aprikoser": "apricot",
    "torkade aprikoser": "apricot dried",
    "plommon": "plum",
    "katrinplommon": "prune",
    "vindruvor": "grape",
    "druvor": "grape",
    "ananas": "pineapple",
    "mango": "mango",
    "kiwi": "kiwi",
    "russin": "raisin",
    "dadlar": "date",
    "bär": "mixed berries",

    # dairy
    "ägg": "egg",
    "äggula": "egg yolk",
    "äggulor": "egg yolk",
    "äggvita": "egg white",
    "äggvitor": "egg white",
    "mjölk": "milk",
    "lättmjölk": "milk lowfat",
    "laktosfri mjölk": "milk",
    "kärnmjölk": "buttermilk",
    "filmjölk": "buttermilk",
    "vispgrädde": "cream heavy",
    "grädde": "cream heavy",
    "matlagningsgrädde": "cream light",
    "lätt matlagningsgrädde": "cream light",
    "crème fraiche": "creme fraiche",
    "lätt crème fraiche": "creme fraiche",
    "gräddfil": "cream sour",
    "smetana": "smetana",
    "naturell yoghurt": "yogurt plain",
    "yoghurt": "yogurt plain",
    "matyoghurt": "yogurt plain",
    "matlagningsyoghurt": "yogurt plain",
    "grekisk yoghurt": "yogurt greek",
    "turkisk yoghurt": "yogurt turkish",
    "fruktyoghurt": "yogurt fruit",
    "ost": "cheese generic",
    "lagrad ost": "cheese parmesan",
    "västerbottensost": "cheese vasterbotten",
    "parmesan": "cheese parmesan",
    "finriven parmesan": "cheese parmesan",
    "cheddar": "cheese cheddar",
    "mozzarella": "cheese mozzarella",
    "fetaost": "cheese feta",
    "feta": "cheese feta",
    "brie": "cheese brie",
    "ädelost": "cheese blue",
    "färskost": "cheese cream",
    "philadelphiaost": "cheese cream",
    "getost": "cheese goat",
    "halloumi": "cheese halloumi",
    "keso": "cheese cottage",
    "kvarg": "quark",
    "laktosfritt smör": "butter",
    "hamburgerost": "cheese cheddar",  # ICA's "hamburgerost" = mild cheddar slice
    "skivad ost": "cheese cheddar",

    # meat & poultry
    "kycklingfilé": "chicken breast",
    "kycklingfiléer": "chicken breast",
    "kycklingbröst": "chicken breast",
    "kycklinglårfilé": "chicken thigh",
    "kycklinglårfiléer": "chicken thigh",
    "kycklinglår": "chicken thigh",
    "hel kyckling": "chicken whole",
    "kycklingfärs": "chicken ground",
    "nötfärs": "ground beef",
    "blandfärs": "ground beef",
    "biff": "beef steak",
    "ryggbiff": "beef sirloin",
    "fläskfilé": "pork loin",
    "fläskkarré": "pork loin",
    "fläskfärs": "ground pork",
    "bacon": "bacon",
    "skivat bacon": "bacon",
    "skinka": "ham",
    "kokt skinka": "ham",
    "rökt skinka": "ham",
    "falukorv": "sausage pork",
    "prinskorv": "sausage pork",
    "isterband": "sausage pork",
    "korv": "sausage pork",
    "varmkorv": "frankfurter",
    "wienerkorv": "frankfurter",
    "köttbullar": "meatball generic",
    "färdiga köttbullar": "meatball generic",
    "lammfilé": "lamb",
    "lammfärs": "lamb",
    "lammstek": "lamb",
    "älg": "moose",
    "älgkött": "moose",
    "ren": "reindeer",
    "renkött": "reindeer",
    "leverpastej": "liver pate",

    # fish & shellfish
    "laxfilé": "salmon",
    "lax": "salmon",
    "rökt lax": "salmon",
    "gravad lax": "salmon",
    "torsk": "cod",
    "torskfilé": "cod",
    "tonfisk": "tuna canned",
    "tonfiskfilé": "tuna fresh",
    "halstrad tonfisk": "tuna fresh",
    "räkor": "shrimp",
    "skalade räkor": "shrimp",
    "sill": "herring",
    "matjessill": "herring",
    "makrill": "mackerel",
    "öring": "trout",
    "regnbågslax": "trout",
    "sej": "pollock",
    "gös": "pike walleye",
    "sardell": "anchovy",
    "ansjovis": "anchovy",
    "sardin": "sardine",
    "rom": "caviar",
    "kräftor": "crayfish",
    "kräfta": "crayfish",
    "musslor": "mussel",

    # grains, pasta, legumes
    "ris": "rice white",
    "vitt ris": "rice white",
    "långkornigt ris": "rice white",
    "basmatiris": "rice white",
    "jasminris": "rice white",
    "brunt ris": "rice brown",
    "port ris": "rice white",       # "1 port[ion] ris" leaked through normalization
    "pasta": "pasta dry",
    "port pasta": "pasta dry",       # same leak
    "spaghetti": "spaghetti dry",
    "tagliatelle": "pasta dry",
    "penne": "pasta dry",
    "fusilli": "pasta dry",
    "macaroni": "pasta dry",
    "makaroner": "pasta dry",
    "lasagneplattor": "pasta dry",
    "nudlar": "noodles",
    "äggnudlar": "noodles",
    "risnudlar": "noodles",
    "couscous": "couscous",
    "bulgur": "bulgur",
    "quinoa": "quinoa",
    "havregryn": "oats",
    "annat gryn": "oats",            # generic "other grain" — best fallback
    "polenta": "polenta",
    "majsmjöl": "polenta",
    "tortilla": "tortilla",
    "linser": "lentils dry",
    "röda linser": "lentils dry",
    "gröna linser": "lentils dry",
    "kikärtor": "chickpeas cooked",   # ICA recipes almost always use canned/cooked
    "kokta kikärtor": "chickpeas cooked",
    "kikärter": "chickpeas cooked",
    "svarta bönor": "black beans",
    "kidneybönor": "kidney beans",
    "röda kidneybönor": "kidney beans",
    "vita bönor": "white beans",
    "borlottibönor": "kidney beans",
    "edamamebönor": "soybeans",
    "sojabönor": "soybeans",
    "tofu": "tofu",

    # nuts, seeds
    "mandel": "almond",
    "sötmandel": "almond",
    "mandlar": "almond",
    "mandelspån": "almond",
    "valnötter": "walnut",
    "valnöt": "walnut",
    "hasselnötter": "hazelnut",
    "hasselnötskärnor": "hazelnut",
    "pecannötter": "pecan",
    "cashewnötter": "cashew",
    "pistagenötter": "pistachio",
    "macadamianötter": "macadamia",
    "pinjenötter": "pine nut",
    "jordnötter": "peanut",
    "chiafrön": "chia seed",
    "solroskärnor": "sunflower seed",
    "solrosfrön": "sunflower seed",
    "sesamfrön": "sesame seed",
    "sesamfrö": "sesame seed",
    "pumpakärnor": "pumpkin seed",
    "pumpafrön": "pumpkin seed",
    "linfrön": "flaxseed",
    "linfrö": "flaxseed",
    "jordnötssmör": "peanut butter",
    "tahini": "tahini",
    "kokos": "coconut shredded",
    "kokosflingor": "coconut shredded",
    "riven kokos": "coconut shredded",
    "kokosmjölk": "coconut milk",
    "kokosgrädde": "coconut cream",

    # sauces, vinegars, condiments
    "vinäger": "vinegar white",
    "ättika": "vinegar white",
    "ättiksprit": "vinegar white",
    "rödvinsvinäger": "vinegar red wine",
    "vitvinsvinäger": "vinegar white wine",
    "äppelcidervinäger": "vinegar cider",
    "balsamvinäger": "vinegar balsamic",
    "balsamico": "vinegar balsamic",
    "risvinäger": "vinegar rice",
    "soja": "soy sauce",
    "japansk soja": "soy sauce",
    "kinesisk soja": "soy sauce",
    "fisksås": "fish sauce",
    "worcestershiresås": "worcestershire",
    "sriracha": "sriracha",
    "sambal oelek": "sambal oelek",
    "sweet chilisås": "sweet chili sauce",
    "chilisås": "sriracha",
    "ketchup": "ketchup",
    "tomatketchup": "ketchup",
    "dijonsenap": "mustard dijon",
    "senap": "mustard yellow",
    "skånsk senap": "mustard yellow",
    "majonnäs": "mayonnaise",
    "lättmajonnäs": "mayonnaise",
    "hummus": "hummus",

    # stocks & broths
    "kycklingbuljong": "chicken stock",
    "hönsbuljong": "chicken stock",
    "köttbuljong": "beef stock",
    "grönsaksbuljong": "vegetable stock",
    "grönsaksbuljongtärning": "vegetable stock",
    "fiskbuljong": "fish stock",

    # chocolate, sweets
    "mörk choklad": "dark chocolate",
    "mjölkchoklad": "milk chocolate",
    "vit choklad": "white chocolate",
    "chokladknappar": "chocolate chips",
    "kakao": "cocoa powder",
    "sylt": "jam",
    "hallonsylt": "jam",
    "jordgubbssylt": "jam",
    "marmelad": "marmalade",
    "äppelmos": "applesauce",
    "vaniljglass": "vanilla ice cream",
    "glass": "ice cream",

    # alcohol & beverages
    "vitt vin": "white wine",
    "vitt matlagningsvin": "white wine",
    "rödvin": "red wine",
    "öl": "beer",
    "rom": "rum",
    "ljus rom": "rum",
    "vodka": "vodka",
    "apelsinjuice": "orange juice",
    "äppeljuice": "apple juice",
    "kolsyrat vatten": "sparkling water",

    # ── alias-growth batch #1 (top residue from first pipeline pass) ──────
    "röd peppar": "chili pepper",
    "olja till stekning": "canola oil",
    "neutral rapsolja": "canola oil",
    "rapsolja för stekning": "canola oil",
    "finskuren gräslök": "chives",
    "hackad gräslök": "chives",
    "fransk senap": "mustard dijon",
    "engelsk senap": "mustard yellow",
    "nötter": "almond",
    "blandade nötter": "almond",
    "delikatesspotatis": "potato",
    "klyftpotatis": "potato",
    "småpotatis": "potato",
    "brun farin": "sugar brown",
    "brunt farinsocker": "sugar brown",
    "muscovado": "sugar brown",
    "isbitar": "ice",
    "fikon": "fig",
    "torkade fikon": "fig",
    "malen kardemumma": "cardamom",
    "stött kardemumma": "cardamom",
    "tabasco": "tabasco",
    "mango chutney": "mango",
    "mangochutney": "mango",
    "räkor i lake": "shrimp",
    "handskalade räkor": "shrimp",
    "paprikor": "bell pepper red",
    "grillad paprika": "bell pepper red",
    "rostad paprika": "bell pepper red",
    "salladsblad": "lettuce",
    "blandsallad": "lettuce",
    "cosmopolitansallad": "lettuce",
    "ekoladasallad": "lettuce",
    "konc kycklingfond": "chicken stock",
    "kycklingfond": "chicken stock",
    "köttfond": "beef stock",
    "konc grönsaksfond": "vegetable stock",
    "grönsaksfond": "vegetable stock",
    "citronmeliss": "mint",
    "mandelmassa": "almond",
    "mandelpasta": "almond",
    "nymald svartpeppar": "black pepper",
    "kycklingklubbor": "chicken drumstick",
    "kycklingklubba": "chicken drumstick",
    "salvia": "sage",
    "färsk salvia": "sage",
    "jordärtskockor": "parsnip",
    "torrt vitt vin": "white wine",
    "torrt rött vin": "red wine",
    "matvin": "white wine",
    "kronärtskockor": "artichoke",
    "kronärtskocka": "artichoke",
    "vit tonfisk": "tuna canned",
    "smördeg": "bread",
    "färsk smördeg": "bread",
    "smördegsplattor": "bread",
    "pommes strips": "potato",
    "pommes": "potato",
    "vaniljkräm": "vanilla extract",
    "kebabspett": "ground beef",
    "köttspett": "ground beef",
    "riven cheddarost": "cheese cheddar",
    "riven ost": "cheese generic",
    "inlagd jalapeño": "jalapeno",
    "inlagd hackad gurka": "cucumber",
    "inlagda rödbetor": "beetroot",
    "ev mangosorbet": "mango",
    "rumsvarmt laktosfritt smör": "butter",
    "färsk timjan": "thyme fresh",
    "färsk basilika": "basil fresh",
    "färsk rosmarin": "rosemary fresh",
    "färsk dill": "dill fresh",
    "färsk persilja": "parsley fresh",
    "färsk koriander": "cilantro fresh",
    "färsk mynta": "mint",
    "hackad bladpersilja": "parsley fresh",
    "finhackad rödlök": "onion red",
    "finhackad gul lök": "onion yellow",
    "ask persilja": "parsley fresh",
    "ask basilika": "basil fresh",
    "kruka persilja": "parsley fresh",
    "kruka basilika": "basil fresh",
    "kruka koriander": "cilantro fresh",
    "äppelcidervinäger eller vitvinsvinäger": "vinegar cider",
    "förp sardeller": "anchovy",
    "förp färsk smördeg": "bread",
    "förp kokta kikärtor": "chickpeas cooked",
    "port couscous": "couscous",

    # ── alias-growth batch #2 ─────────────────────────────────────────────
    "örter": "parsley fresh",
    "blandade örter": "parsley fresh",
    "färska örter": "parsley fresh",
    "kalvfond": "beef stock",
    "oliver": "olives black",
    "svamp": "mushroom button",
    "svampar": "mushroom button",
    "blomkålshuvud": "cauliflower",
    "rabarber": "celery",  # closest USDA (rhubarb maps to no clean entry)
    "kycklingbuljongtärning": "chicken stock",
    "hönsbuljongtärning": "chicken stock",
    "grönsaksbuljongtärningar": "vegetable stock",
    "buljongtärning": "chicken stock",
    "pesto": "basil fresh",
    "grön pesto": "basil fresh",
    "havredryck": "milk",  # oat milk closest = milk
    "spetskål": "cabbage",
    "köttfärs": "ground beef",
    "smält smör": "butter",
    "vitpepparkorn": "white pepper",
    "srirachasås": "sriracha",
    "surdegsbröd": "bread",
    "finriven ingefära": "ginger dried",
    "cottage cheese": "cheese cottage",
    "ärtskott": "peas fresh",
    "rucolasallad": "arugula",
    "rörsocker": "sugar granulated",
    "naturell färskost": "cheese cream",
    "färskpressad apelsinjuice": "orange juice",
    "ricottaost": "cheese cottage",  # closest = cottage cheese
    "ricotta": "cheese cottage",
    "syltsocker": "sugar granulated",
    "ask körsbärstomater": "cherry tomato",
    "myntablad": "mint",
    "vetemjöl special": "wheat flour",
    "kavring": "bread",
    "rågbröd": "bread",
    "ljust bröd": "bread",
    "mörkt bröd": "bread",
    "knäckebröd": "bread",  # USDA has no clean crispbread; use bread fallback
    "rågmjöl": "wheat flour",  # closest = wheat flour
    "havremjöl": "oats",
    "korngryn": "oats",
    "rågflingor": "oats",
    "lingon": "lingonberry",
    "lingonsylt": "lingonberry",
    "hallonsylt": "jam",
    "jordgubbssylt": "jam",
    "blåbärssylt": "jam",
    "bär": "mixed berries",
    "frysta bär": "mixed berries",
    "blandbär": "mixed berries",

    # ── alias-growth batch #3 — protein gaps (the kotlett fix) ────────────
    "kotlett": "pork chop",
    "kotletter": "pork chop",
    "fläskkotlett": "pork chop",
    "fläskkotletter": "pork chop",
    "benfri fläskkotlett": "pork chop",
    "benfria fläskkotletter": "pork chop",
    "benfria kotletter": "pork chop",
    "fläskytterfilé": "pork loin",
    "fläskytterfiléer": "pork loin",
    "fläskinnerfilé": "pork tenderloin",
    "fläsktenderloin": "pork tenderloin",
    "tenderloin": "pork tenderloin",
    "fläskbog": "pork shoulder",
    "pulled pork": "pork shoulder",
    "fläsksida": "pork belly",
    "fläskmage": "pork belly",
    "fläsk": "pork shoulder",
    "fläskstek": "pork shoulder",
    "kassler": "pork cured loin",
    "parmaskinka": "ham",
    "lufttorkad skinka": "ham",
    "rökt skinka": "ham",
    "kokt skinka": "ham",
    "serranoskinka": "ham",
    "lövbiff": "beef sirloin",
    "rostbiff": "beef sirloin",
    "bifftomat": "tomato",
    "bifftomater": "tomato",
    "oxfilé": "beef tenderloin",
    "entrecôte": "beef rib short",
    "entrecote": "beef rib short",
    "högrev": "beef chuck stew",
    "bringa": "beef brisket",
    "grytbitar": "beef chuck stew",
    "kalvfärs": "ground beef",
    "kalvkött": "ground beef",
    "kalvstek": "beef steak",
    "kyckling": "chicken whole",
    "hel kyckling": "chicken whole",
    "grillad kyckling": "chicken whole",
    "kycklingben": "chicken drumstick",
    "kycklingvinge": "chicken wing",
    "kycklingvingar": "chicken wing",
    "kalkonfilé": "turkey breast",
    "kalkonbröst": "turkey breast",
    "kalkonfärs": "turkey ground",
    "kalkon": "turkey breast",
    "anka": "duck",
    "ankbröst": "duck",
    "ankalår": "duck",
    "snabbfiléer av kyckling": "chicken breast",
    "kycklingbröstfiléer": "chicken breast",
    "kycklinginnerfilé": "chicken breast",
    "kycklinginnerfiléer": "chicken breast",
    "kycklingbröst": "chicken breast",
    "laxfilé utan skinn": "salmon",
    "benfri laxfilé": "salmon",
    "port laxfilé": "salmon",
    "färsk laxfilé": "salmon",
    "kallrökt lax": "salmon smoked",
    "varmrökt lax": "salmon smoked",
    "rökt lax": "salmon smoked",
    "gravad lax": "salmon lox",
    "graavlax": "salmon lox",
    "torskrygg": "cod",
    "torsk": "cod",
    "torskfilé": "cod",
    "vit fisk": "white fish",
    "vitfisk": "white fish",
    "fisk": "white fish",
    "fiskfilé": "white fish",
    "räkor med skal": "shrimp",
    "räkor utan skal": "shrimp",
    "handskalade räkor": "shrimp",
    "tonfisk i vatten": "tuna canned water",
    "tonfisk i olja": "tuna canned",
    "ansjovisfiléer": "anchovy",
    "ansjovis": "anchovy",
    "sardeller": "anchovy",
    "kräftstjärtar": "crayfish",
    "kräftstjärtar i lake": "crayfish",
    "blåmusslor": "mussel",
    "pilgrimsmusslor": "scallop",
    "musslor": "mussel",
    "krabba": "crab",
    "krabbkött": "crab",
    "ostron": "oyster",
    "älgfärs": "moose",
    "älg": "moose",
    "älgstek": "moose",
    "rådjursfärs": "venison",
    "rådjur": "venison",
    "vilt": "venison",
    "uppvispat ägg": "egg",
    "uppvispade ägg": "egg",
    "hårdkokta ägg": "egg",
    "hårdkokt ägg": "egg",
    "stora ägg": "egg",
    "smulad fetaost": "cheese feta",
    "smulad feta": "cheese feta",
    "tärnad fetaost": "cheese feta",
    "tofu fast": "tofu firm",
    "fast tofu": "tofu firm",
    "tempeh": "tempeh",
    "seitan": "seitan",

    # ── alias-growth batch #3b — non-protein residue overlap ──────────────
    "muskotnöt": "nutmeg",
    "naturella cashewnötter": "cashew",
    "valnötskärnor": "walnut",
    "salta jordnötter": "peanut",
    "köttbuljongtärning": "beef stock",
    "köttbuljongtärningar": "beef stock",
    "hönsbuljongtärningar": "chicken stock",
    "fiskbuljongtärning": "fish stock",
    "fiskbuljongtärningar": "fish stock",
    "fiskfond": "fish stock",
    "olivolja till stekning": "olive oil",
    "rapsolja till stekning": "canola oil",
    "färskriven ingefära": "ginger dried",
    "finriven färsk ingefära": "ginger dried",
    "finriven ingefära": "ginger dried",
    "färskriven pepparrot": "horseradish",
    "färskpressad citronsaft": "lemon juice",
    "färskpressad limesaft": "lime juice",
    "färskriven parmesan": "cheese parmesan",
    "ask färsk persilja": "parsley fresh",
    "ask färsk dill": "dill fresh",
    "ask färsk gräslök": "chives",
    "ask färsk basilika": "basil fresh",
    "ask färsk koriander": "cilantro fresh",
    "kvistar färsk rosmarin": "rosemary fresh",
    "kvistar färsk timjan": "thyme fresh",
    "kvist rosmarin": "rosemary fresh",
    "kvist timjan": "thyme fresh",
    "färskpotatisar": "potato",
    "hasselnötskräm": "hazelnut",
    "hasselnötter": "hazelnut",
}


def build_sv_to_fdc() -> dict[str, int]:
    """Compose the flat {swedish: fdc_id} table the pipeline consumes."""
    out: dict[str, int] = {}
    missing_en: set[str] = set()
    for sv, en in SV_TO_EN.items():
        fdc = EN_TO_FDC.get(en)
        if fdc is None:
            missing_en.add(en)
            continue
        out[sv] = fdc
    if missing_en:
        # Surface mistakes loudly during dev; never silent.
        raise RuntimeError(
            f"SV_TO_EN references English keys not in EN_TO_FDC: {sorted(missing_en)}"
        )
    return out


if __name__ == "__main__":
    table = build_sv_to_fdc()
    print(f"Built {len(table)} Swedish -> fdc_id mappings "
          f"from {len(EN_TO_FDC)} English canonical entries.")
