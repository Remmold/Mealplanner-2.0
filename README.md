# Mealplanner 2.0

A meal planning application backed by real nutritional data from [Open Food Facts](https://world.openfoodfacts.org/).

---

## Project structure

```
Mealplanner-2.0/
├── backend/
│   ├── pipeline/               # Data ingestion (OFF → DuckDB)
│   │   ├── sources/
│   │   │   └── open_food_facts.py
│   │   └── run.py
│   ├── .dlt/config.toml        # dlt runtime config
│   ├── pyproject.toml          # Python project + dependencies
│   └── .env.example            # Environment variable template
└── README.md
```

---

## Backend — data pipeline

The pipeline streams the Open Food Facts daily data dump, filters by meal-planning categories, and loads the results into a local DuckDB database.

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)

### Setup

```bash
cd backend

# Install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
```

Edit `.env` if you want to change the dump path, target categories, or destination database.

### Run

```bash
uv run python -m pipeline.run
```

**First run:** downloads the OFF dump (~5 GB compressed) then ingests matching products. Expect 30–90 minutes depending on internet speed and hardware.

**Subsequent runs:** sends a `HEAD` request to check if OFF has published a new dump. If unchanged, the cached file is reused and only the load step runs.

### Quick test (5 000 records)

```bash
OFF_MAX_RECORDS=5000 uv run python -m pipeline.run
```

### Output

Tables are written to `food_data.duckdb` under the `off` schema:

| Table | Description |
|---|---|
| `off.products` | One row per product — name, brand, nutriscore, nova group, macros per 100g |
| `off.products__categories_tags` | Product ↔ category tag |
| `off.products__allergens_tags` | Product ↔ allergen tag |
| `off.products__countries_tags` | Product ↔ country tag |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `OFF_DUMP_PATH` | `off_dump.jsonl.gz` | Local path for the downloaded dump |
| `OFF_CATEGORIES` | (built-in list) | Comma-separated OFF category tags to ingest |
| `OFF_MAX_RECORDS` | `0` (unlimited) | Cap matched records — useful for testing |
| `DUCKDB_PATH` | `food_data.duckdb` | Output DuckDB file |
| `DESTINATION` | `duckdb` | `duckdb` or `postgres` |
| `POSTGRES_CONNECTION_STRING` | — | Required when `DESTINATION=postgres` |

For a full explanation of every file and the pipeline internals, see [backend/PIPELINE.md](backend/PIPELINE.md).
