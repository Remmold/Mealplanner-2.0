"""Backend API package.

Loads backend/.env once on first `api.*` import so every submodule sees the
environment variables, regardless of import order. (api.db, api.auth, etc.
read os.environ at module-import time for their module-level constants.)
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
