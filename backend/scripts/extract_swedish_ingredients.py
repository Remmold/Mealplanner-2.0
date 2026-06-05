"""Stage 1 of the alias-table build: scan all 10,924 amcoff recipes, normalize
each ingredient phrase down to its core noun, and rank by frequency.

Normalization rules (applied in order):
  - lowercase + collapse whitespace
  - drop parentheticals: "indian tonic (gärna zero)" -> "indian tonic"
  - drop trailing prep notes after comma: "olivolja, kallpressad" -> "olivolja"
  - strip leading qty/count words the source sometimes leaves in the ingr field:
        "skivor X" -> "X", "klyftor X" -> "X", "stor X" -> "X", etc.
  - strip leading preparation adjectives: "färsk X", "kokt X", "finhackad X",
    "riven X", "skivad X", "hackad X" -> "X"
  - split conjunctions ("X och Y") into two separate ingredients
  - keep diacritics intact (ö/ä/å are load-bearing in Swedish)

Output: backend/seeds/swedish_ingredient_freq.json — sorted list of
{name, count, sample_raw} so we can eyeball before hand-mapping fdc_ids."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from huggingface_hub import hf_hub_download

BACKEND = Path(__file__).resolve().parent.parent
OUT_DIR = BACKEND / "seeds"
OUT_DIR.mkdir(exist_ok=True)


# Words we strip from the FRONT of an ingredient phrase when they appear there.
# These are preparation/state adjectives and quantity-leaking nouns.
LEADING_STRIPS = (
    # state / freshness
    "färsk", "färska", "fryst", "frysta", "torkad", "torkade", "kokt", "kokta",
    "stekt", "stekta", "rostad", "rostade", "kallpressad", "ekologisk", "ekologiska",
    "mogen", "mogna", "uppskuren", "uppskurna", "rumsvarm", "rumsvarmt",
    "rumstempererad", "rumstempererat", "varm", "varmt", "kall", "kallt",
    "laktosfri", "laktosfritt", "laktosfria",
    # cut style
    "hackad", "hackade", "finhackad", "finhackade", "grovhackad", "grovhackade",
    "skivad", "skivade", "tärnad", "tärnade", "riven", "rivna", "rivet",
    "pressad", "pressade", "pressat",
    "krossad", "krossade", "delad", "delade", "halverad", "halverade", "strimlad",
    "strimlade", "pillad", "pillade", "skalad", "skalade", "urkärnad", "urkärnade",
    "finskuren", "finskurna", "finskuret", "finskuret", "skuren", "skurna",
    "malen", "malda", "malt", "nymald", "nymalen", "nymalda",
    "blandad", "blandade", "blandat", "grovmalen", "grovmald",
    # concentration / processing
    "konc", "koncentrerad", "koncentrerat", "passerad", "passerade", "inlagd",
    "inlagda", "inlagt",
    # size words
    "stor", "stora", "liten", "lilla", "små", "mellanstor", "mellanstora",
    # qty-leaking count nouns
    "skivor", "skiva", "klyfta", "klyftor", "kruka", "krukor", "burk", "burkar",
    "påse", "påsar", "förp", "förpackning", "knippe", "knippen", "näve", "nävar",
    "pkt", "paket", "stycken", "styck", "bit", "bitar",
    "ev", "evt", "extra",
    # ICA portion shorthand that leaked into the `ingr` field for some recipes
    "port", "portion", "portioner",
    "ask", "askar",
)

# Words that — if they remain as the SOLE token after stripping — are not
# foods at all and should be dropped (these survived as bare ingr strings like
# "färsk" alone or "frysta" alone).
SOLO_NON_FOOD = set(LEADING_STRIPS) | {
    "till servering", "till", "servering", "garnering", "garnish", "smaksättning",
    "att rulla i", "annat",
}

# Multi-word strips we want to recognize as a unit at the front.
LEADING_PHRASES = (
    "rivet ", "rivna ", "skivat ", "skivad ", "tärnat ", "tärnad ",
)

PAREN_RE = re.compile(r"\s*\([^)]*\)")
PUNCT_TRAIL_RE = re.compile(r"[\s,.;]+$")
MULTISPACE_RE = re.compile(r"\s+")


def _strip_leading(name: str) -> str:
    """Strip one or more leading preparation/count adjectives. Idempotent."""
    changed = True
    while changed:
        changed = False
        for w in LEADING_STRIPS:
            if name.startswith(w + " "):
                name = name[len(w) + 1:]
                changed = True
                break
        for phr in LEADING_PHRASES:
            if name.startswith(phr):
                name = name[len(phr):]
                changed = True
                break
    return name


def normalize(raw: str) -> list[str]:
    """Take a raw `ingr` string, return zero, one, or more normalized core names."""
    if not raw:
        return []
    s = raw.strip().lower()
    # drop parenthetical asides
    s = PAREN_RE.sub("", s)
    # drop trailing prep after comma: "olivolja, kallpressad"
    if "," in s:
        s = s.split(",", 1)[0].strip()
    # collapse whitespace, strip trailing punctuation
    s = PUNCT_TRAIL_RE.sub("", s)
    s = MULTISPACE_RE.sub(" ", s).strip()
    if not s:
        return []

    # split "X och Y" / "X eller Y" (or)
    parts: list[str] = []
    for piece in re.split(r"\s+(?:och|eller|samt)\s+", s):
        piece = piece.strip()
        if not piece:
            continue
        piece = _strip_leading(piece)
        piece = PUNCT_TRAIL_RE.sub("", piece).strip()
        if piece and len(piece) >= 2 and piece not in SOLO_NON_FOOD:
            parts.append(piece)
    return parts


def _stream_decode(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    out: list[dict] = []
    idx, length = 0, len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        obj, end = decoder.raw_decode(text, idx)
        out.append(obj)
        idx = end
    return out


def main() -> None:
    print("Loading amcoff/ica.json...")
    path = hf_hub_download(repo_id="amcoff/recept", filename="ica.json", repo_type="dataset")
    recipes = _stream_decode(Path(path).read_text(encoding="utf-8"))
    print(f"  {len(recipes)} recipes")

    counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)

    total_lines = 0
    for r in recipes:
        for group in r.get("ingredients") or []:
            for item in group.get("list") or []:
                raw = (item.get("ingr") or "").strip()
                if not raw:
                    continue
                total_lines += 1
                for norm in normalize(raw):
                    counter[norm] += 1
                    if len(samples[norm]) < 3:
                        samples[norm].append(raw)

    print(f"  {total_lines:,} raw ingredient lines")
    print(f"  {len(counter):,} unique normalized names")

    ranked = counter.most_common()
    out = [
        {"name": n, "count": c, "samples": samples[n]}
        for n, c in ranked
    ]
    out_path = OUT_DIR / "swedish_ingredient_freq.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")

    print("\n--- top 60 normalized ingredients (eyeball check) ---")
    for n, c in ranked[:60]:
        ex = samples[n][0] if samples[n] else ""
        print(f"  {c:5d}  {n:30s}  ex: {ex[:50]}")

    cum = 0
    for thresh in (50, 100, 200, 300, 500, 1000):
        cum_count = sum(c for _, c in ranked[:thresh])
        cov = cum_count / total_lines * 100 if total_lines else 0
        print(f"  top {thresh:4d} covers {cum_count:7,d} / {total_lines:,} lines = {cov:5.1f}%")


if __name__ == "__main__":
    main()
