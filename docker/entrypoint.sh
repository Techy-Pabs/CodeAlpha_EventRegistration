#!/bin/sh
# Wait for Postgres, apply migrations, then run the container's command
# (gunicorn by default, or e.g. "python manage.py seed_demo").
set -e

python - <<'PY'
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection
from django.db.utils import OperationalError

for attempt in range(1, 31):
    try:
        connection.ensure_connection()
        print("Postgres is ready.", flush=True)
        break
    except OperationalError:
        print(f"Waiting for Postgres ({attempt}/30)...", flush=True)
        time.sleep(1)
else:
    sys.exit("Postgres was not reachable after 30 seconds.")
PY

python manage.py migrate --noinput

exec "$@"
