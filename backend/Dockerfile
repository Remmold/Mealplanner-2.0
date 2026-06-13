# Build context is the repo ROOT (see docker-compose: context: .), so paths
# below are repo-relative. The runtime API is Postgres-only; none of the large
# offline-pipeline data (food_data.duckdb, off_dump*, usda_data) is needed or
# copied — see the root .dockerignore.
FROM python:3.12-slim

# uv is build-time only; the container runs the resulting venv directly.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
# No UV_COMPILE_BYTECODE: on this 1GB VM it added ~2min of compile + thousands of
# .pyc files that slow the image export. Python compiles lazily at first import;
# for a long-running server the one-time startup cost is negligible.
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install third-party deps only (--no-install-project), so this layer caches
# across source edits and doesn't need api/ present yet. The app is run from
# source via PYTHONPATH, never pip-installed.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-cache --no-install-project

COPY backend/api ./api
COPY backend/pipeline ./pipeline

# Generated images are bind-mounted here at runtime; pre-create so the app's
# mkdir(exist_ok=True) / FileResponse paths resolve even on an empty mount.
RUN mkdir -p ingredient_images recipe_images

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
