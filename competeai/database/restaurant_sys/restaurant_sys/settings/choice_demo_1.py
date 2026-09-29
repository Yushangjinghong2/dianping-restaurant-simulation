from .base import *

SHOW_ALL_COMMENTS = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_choice_demo_1.sqlite3",
    }
}
