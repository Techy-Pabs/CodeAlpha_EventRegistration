FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Unprivileged user that runs the app. It owns nothing in /app, so a
# compromised process can't rewrite the code.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

# Dependencies first, in their own layer: rebuilt only when
# requirements.txt changes, not on every code edit.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collect static files into the image. Settings need these variables to
# load, but nothing connects to a database here, so placeholders are enough.
RUN SECRET_KEY=collectstatic-only JWT_SIGNING_KEY=collectstatic-only \
    DATABASE_URL=sqlite:////tmp/unused.db \
    python manage.py collectstatic --noinput

USER app

EXPOSE 8000

# --no-control-socket: gunicorn 27's runtime control socket would live in the
# user's home directory, which this user doesn't have (and we don't use it).

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--no-control-socket"]
