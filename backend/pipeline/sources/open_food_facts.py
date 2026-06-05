"""
dlt source for the Open Food Facts data dump (JSONL.gz).

Streams the compressed dump file line-by-line, filters for relevant food
categories, and yields flattened product records into dlt.

Dump URL: https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz
Dump docs: https://world.openfoodfacts.org/data

Child tables for list columns (categories_tags, allergens_tags, countries_tags)
are created automatically by dlt.
"""

import gzip
import json
import os
from pathlib import Path
from typing import Iterator

import dlt
import requests
from dlt.common.typing import TDataItem

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DUMP_URL = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"
USER_AGENT = "MealplannerBot/1.0 (https://github.com/yourusername/Mealplanner-2.0)"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB chunks

DEFAULT_CATEGORIES: list[str] = [
    "en:meals",
    "en:breakfasts",
    "en:snacks",
    "en:dairy-products",
    "en:fruits-and-vegetables",
    "en:meats",
    "en:fish-and-seafood",
    "en:cereals-and-their-products",
    "en:breads",
]


# ---------------------------------------------------------------------------
# dlt source
# ---------------------------------------------------------------------------


@dlt.source(name="open_food_facts")
def open_food_facts_source(
    dump_path: str = None,  # dlt wraps params in a dataclass — no mutable defaults
    categories: list[str] = None,
    max_records: int = 0,
) -> dlt.sources.DltResource:
    """
    Yields a `products` resource by streaming the OFF JSONL dump.

    Args:
        dump_path:   Path to the local .jsonl.gz dump file. If the file does
                     not exist, it will be downloaded from DUMP_URL first.
                     Defaults to OFF_DUMP_PATH env var or 'off_dump.jsonl.gz'.
        categories:  OFF category tags to keep. Products not matching any tag
                     are skipped. Defaults to DEFAULT_CATEGORIES.
        max_records: Stop after this many matching records (0 = no limit).
                     Useful for a quick test run.
    """
    if dump_path is None:
        dump_path = os.getenv("OFF_DUMP_PATH", "off_dump.jsonl.gz")
    if categories is None:
        categories = DEFAULT_CATEGORIES

    resolved = Path(dump_path).resolve()
    _ensure_dump(DUMP_URL, resolved)

    yield products_resource(str(resolved), categories, max_records)


# ---------------------------------------------------------------------------
# dlt resource
# ---------------------------------------------------------------------------


@dlt.resource(
    name="products",
    write_disposition="merge",
    primary_key="code",
)
def products_resource(
    dump_path: str,
    categories: list[str],
    max_records: int,
) -> Iterator[TDataItem]:
    category_set = set(categories)
    matched = 0

    with gzip.open(dump_path, "rb") as gz:
        for raw_line in gz:
            line = raw_line.strip()
            if not line:
                continue

            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue

            product_categories = set(raw.get("categories_tags") or [])
            if not product_categories.intersection(category_set):
                continue

            # Assign the first matching target category as the primary one
            primary = next(
                (c for c in categories if c in product_categories),
                next(iter(product_categories), ""),
            )

            record = _flatten(raw, primary)
            if not record["code"]:
                continue

            yield record
            matched += 1

            if max_records and matched >= max_records:
                print(f"  Reached max_records limit ({max_records}), stopping.")
                return

            if matched % 10_000 == 0:
                print(f"  {matched:,} records matched so far...", flush=True)


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------


def _ensure_dump(url: str, dest: Path) -> None:
    """Download the dump if missing or if the server has a newer version.

    Uses HTTP ETags (or Last-Modified as fallback) stored in a sidecar
    `<dump>.meta.json` file so we only re-download when OFF has published
    a new daily dump.
    """
    meta_path = dest.with_suffix(".meta.json")
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Load previously stored validator
    stored: dict = {}
    if meta_path.exists() and dest.exists():
        try:
            stored = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Ask the server whether the file has changed
    head_headers = {"User-Agent": USER_AGENT}
    if stored.get("etag"):
        head_headers["If-None-Match"] = stored["etag"]
    elif stored.get("last_modified"):
        head_headers["If-Modified-Since"] = stored["last_modified"]

    try:
        head = requests.head(url, headers=head_headers, timeout=30, allow_redirects=True)
    except requests.RequestException as exc:
        if dest.exists():
            print(f"  Could not reach server ({exc}), using cached dump.")
            return
        raise

    if head.status_code == 304:
        print(f"Dump is up to date (ETag matched), using cached file: {dest}")
        return

    if dest.exists() and stored:
        print(f"Server has a new dump (status {head.status_code}), re-downloading...")
    else:
        print(f"Dump not found locally, downloading from {url}")

    print("(~5 GB compressed — this will take a while. Subsequent runs check for updates first.)\n")

    _download_dump(url, dest)

    # Persist the new ETag / Last-Modified for next run
    new_meta = {
        "etag": head.headers.get("ETag", ""),
        "last_modified": head.headers.get("Last-Modified", ""),
    }
    meta_path.write_text(json.dumps(new_meta, indent=2))


def _download_dump(url: str, dest: Path) -> None:
    """Stream-download the dump file to dest with a progress indicator."""
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)  # remove any leftover from a previous interrupted download

    headers = {"User-Agent": USER_AGENT}
    with requests.get(url, stream=True, headers=headers, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0

        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        mb = downloaded / 1024 / 1024
                        total_mb = total / 1024 / 1024
                        print(f"  {mb:.0f} / {total_mb:.0f} MB  ({pct:.1f}%)", end="\r", flush=True)

    tmp.replace(dest)  # replace() overwrites on Windows; rename() does not
    print(f"\nDownload complete: {dest}")


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _flatten(raw: dict, primary_category: str) -> TDataItem:
    """Flatten a raw OFF product dict into a single-level record."""
    n = raw.get("nutriments") or {}

    return {
        # Identity
        "code": (raw.get("code") or "").strip(),
        "product_name": (raw.get("product_name") or "").strip(),
        "brands": (raw.get("brands") or "").strip(),
        # Taxonomy
        "primary_category": primary_category,
        "categories_tags": raw.get("categories_tags") or [],
        "allergens_tags": raw.get("allergens_tags") or [],
        "countries_tags": raw.get("countries_tags") or [],
        # Content
        "ingredients_text": (raw.get("ingredients_text") or "").strip(),
        "image_url": (raw.get("image_url") or "").strip(),
        # Quality scores
        "nutriscore_grade": (raw.get("nutriscore_grade") or "").lower().strip(),
        "nova_group": _int_or_none(raw.get("nova_group")),
        # Serving
        "serving_size": (raw.get("serving_size") or "").strip(),
        "serving_quantity_g": _float_or_none(raw.get("serving_quantity")),
        # Macronutrients per 100g
        "energy_kcal_100g": _float_or_none(n.get("energy-kcal_100g")),
        "proteins_100g": _float_or_none(n.get("proteins_100g")),
        "carbohydrates_100g": _float_or_none(n.get("carbohydrates_100g")),
        "sugars_100g": _float_or_none(n.get("sugars_100g")),
        "fat_100g": _float_or_none(n.get("fat_100g")),
        "saturated_fat_100g": _float_or_none(n.get("saturated-fat_100g")),
        "fiber_100g": _float_or_none(n.get("fiber_100g")),
        "salt_100g": _float_or_none(n.get("salt_100g")),
        "sodium_100g": _float_or_none(n.get("sodium_100g")),
        # Metadata
        "last_modified_t": _int_or_none(raw.get("last_modified_t")),
    }


def _float_or_none(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _int_or_none(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None
