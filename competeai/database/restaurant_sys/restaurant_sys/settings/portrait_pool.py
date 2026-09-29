"""Run-specific settings for isolated portrait-pool simulations."""

import os
from pathlib import Path

from .base import *  # noqa: F401,F403

SHOW_ALL_COMMENTS = True

database_path = os.environ.get("COMPETEAI_DB_PATH")
if not database_path:
    raise RuntimeError("COMPETEAI_DB_PATH must point to this run's SQLite database")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(database_path),
    }
}
