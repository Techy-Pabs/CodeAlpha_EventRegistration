"""Production settings read from the environment, and how they behave."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from django.urls import reverse

BASE_DIR = Path(__file__).resolve().parents[2]

NEW_VARS = [
    "CSRF_TRUSTED_ORIGINS",
    "SECURE_SSL_REDIRECT",
    "NUM_PROXIES",
    "DATABASE_CONN_MAX_AGE",
]


def load_settings(**overrides):
    """Import config.settings in a fresh process with the given env vars.

    Settings are read once at import time, so each case needs its own process.
    """
    env = {k: v for k, v in os.environ.items() if k not in NEW_VARS}
    env.update(overrides)
    code = (
        "import json; from config import settings as s; "
        "db = s.DATABASES['default']; "
        "print(json.dumps({"
        "'csrf': s.CSRF_TRUSTED_ORIGINS, 'redirect': s.SECURE_SSL_REDIRECT, "
        "'exempt': s.SECURE_REDIRECT_EXEMPT, 'proxy': s.SECURE_PROXY_SSL_HEADER, "
        "'hsts': getattr(s, 'SECURE_HSTS_SECONDS', 0), "
        "'hsts_sub': getattr(s, 'SECURE_HSTS_INCLUDE_SUBDOMAINS', False), "
        "'preload': getattr(s, 'SECURE_HSTS_PRELOAD', False), "
        "'num_proxies': s.REST_FRAMEWORK['NUM_PROXIES'], "
        "'max_age': db['CONN_MAX_AGE'], 'health_checks': db['CONN_HEALTH_CHECKS'], "
        "'options': db.get('OPTIONS', {})}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BASE_DIR, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_local_defaults():
    s = load_settings()
    assert s["csrf"] == []
    assert s["redirect"] is False
    assert s["hsts"] == 0
    assert s["num_proxies"] is None
    assert s["max_age"] == 60
    assert s["health_checks"] is True
    assert s["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]


def test_empty_values_behave_like_unset():
    s = load_settings(CSRF_TRUSTED_ORIGINS="", NUM_PROXIES="", SECURE_SSL_REDIRECT="")
    assert s["csrf"] == []
    assert s["num_proxies"] is None
    assert s["redirect"] is False


def test_csrf_trusted_origins_is_a_list():
    s = load_settings(CSRF_TRUSTED_ORIGINS="https://a.onrender.com, https://b.example.com,")
    assert s["csrf"] == ["https://a.onrender.com", "https://b.example.com"]


@pytest.mark.parametrize(("value", "expected"), [("0", 0), ("1", 1), ("2", 2)])
def test_num_proxies(value, expected):
    assert load_settings(NUM_PROXIES=value)["num_proxies"] == expected


def test_ssl_redirect_turns_on_one_day_hsts_without_preload():
    s = load_settings(SECURE_SSL_REDIRECT="True")
    assert s["redirect"] is True
    assert s["hsts"] == 86400
    assert s["hsts_sub"] is False
    assert s["preload"] is False
    assert s["exempt"] == [r"^api/health/$"]


def test_neon_connection_string_keeps_ssl_options():
    url = (
        "postgresql://user:pw@ep-example-123.eu-central-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    s = load_settings(DATABASE_URL=url, DATABASE_CONN_MAX_AGE="0")
    assert s["options"] == {"sslmode": "require", "channel_binding": "require"}
    assert s["max_age"] == 0


# --- HTTPS redirect behaviour (SecurityMiddleware reads settings per client) ---


@pytest.fixture
def https_on(settings):
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_HSTS_SECONDS = 86400


@pytest.mark.django_db
def test_plain_http_is_redirected_to_https(https_on, api_client):
    response = api_client.get(reverse("events:event-list"))
    assert response.status_code == 301
    assert response["Location"].startswith("https://")


@pytest.mark.django_db
def test_health_check_is_not_redirected(https_on, api_client):
    response = api_client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_request_forwarded_as_https_is_served_with_hsts(https_on, api_client):
    response = api_client.get(reverse("events:event-list"), HTTP_X_FORWARDED_PROTO="https")
    assert response.status_code == 200
    assert response["Strict-Transport-Security"] == "max-age=86400"


# --- gunicorn.conf.py ---


def gunicorn_conf(monkeypatch, **env):
    for name in ("PORT", "WEB_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return runpy.run_path(str(BASE_DIR / "gunicorn.conf.py"))


def test_gunicorn_local_defaults(monkeypatch):
    conf = gunicorn_conf(monkeypatch)
    assert conf["bind"] == "0.0.0.0:8000"
    assert conf["workers"] == 2


def test_gunicorn_uses_render_port_and_web_concurrency(monkeypatch):
    conf = gunicorn_conf(monkeypatch, PORT="10000", WEB_CONCURRENCY="3")
    assert conf["bind"] == "0.0.0.0:10000"
    assert conf["workers"] == 3


@pytest.mark.parametrize("value", ["abc", "0", "-1"])
def test_gunicorn_rejects_bad_worker_count(monkeypatch, value):
    with pytest.raises(SystemExit, match="WEB_CONCURRENCY"):
        gunicorn_conf(monkeypatch, WEB_CONCURRENCY=value)
