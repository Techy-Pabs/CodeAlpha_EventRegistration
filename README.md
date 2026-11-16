# CodeAlpha Event Registration System

[![CI](https://github.com/Techy-Pabs/CodeAlpha_EventRegistration/actions/workflows/ci.yml/badge.svg)](https://github.com/Techy-Pabs/CodeAlpha_EventRegistration/actions/workflows/ci.yml)

A REST API for publishing events and signing up for them. Organisers create
events with a fixed number of seats, and other users register, see their
bookings and cancel them. I built it for the CodeAlpha Backend Development
internship, Task 2.

## Features

- Sign up, log in and log out with JWT access and refresh tokens.
- Usernames and emails are unique regardless of letter case, and you can log
  in as "alice" or "Alice".
- Organisers create, edit and delete their own events. An admin decides who
  is an organiser.
- Anyone can browse published events that haven't started yet. Organisers
  also see their own drafts and past events. Anything you aren't allowed to
  see returns 404.
- Each event shows `seats_left`, counted by the database in the same query
  as the event list.
- Search, date range filters, ordering and pagination on the event list.
- Registering for an event can't overbook it, even when two people take the
  last seat at the same moment.
- Users can cancel before the event starts and register again later.
- Organisers can list the confirmed attendees of their events.
- Swagger UI with request bodies and status codes for every endpoint.
- Login and sign-up are rate limited.
- A health check endpoint, a Docker setup, a demo data command and CI.

## Tech stack

- Python 3.14, Django 5.2, Django REST Framework 3.18
- PostgreSQL 16
- Simple JWT for tokens (with a refresh token blacklist)
- drf-spectacular for the OpenAPI schema and Swagger UI
- gunicorn and WhiteNoise in the Docker image
- pytest and pytest-django for tests, ruff for linting and formatting
- GitHub Actions for CI

## Data model

| Model | What it holds | Key constraints |
| --- | --- | --- |
| `User` | Django's user plus an `is_organiser` flag | Username unique ignoring case. Email unique ignoring case (blank emails allowed). Emails are stored trimmed and lowercased. |
| `Event` | Title, description, location, start and end, capacity, organiser, published flag | `ends_at` after `starts_at`. `capacity` at least 1. An organiser who still has events can't be deleted (`PROTECT`). |
| `Registration` | User, event, status (`confirmed` or `cancelled`), phone, note, timestamps | At most one confirmed registration per user per event, so re-registering after a cancel works. Status must be one of the two values. Note at most 500 characters. |

All of these rules live in the database as well as in the API code, so they
hold even for data written from the admin or the Django shell.

## How overbooking is prevented

Picture an event with one seat left and two people pressing "register" at
the same moment. If both requests count the confirmed registrations before
either one saves, both see a free seat and both get in.

The register endpoint avoids this. It opens a database transaction with
`transaction.atomic()` and loads the event with `select_for_update()`.
That puts a row lock on the event. A second request for the same event has
to wait at that line until the first transaction commits. By the time it
can count the seats, the first registration is already saved, so it sees
the event is full and gets a 409. Requests for different events don't
block each other.

`events/tests/test_concurrency.py` tests this with real threads. It creates
an event with one seat, starts two threads that register two different
users, and releases them at the same moment with a `threading.Barrier`.
The test uses committed transactions on separate database connections
(`django_db(transaction=True)`), so the lock behaves as it does in
production. It expects exactly one 201, one 409 and one confirmed
registration. To check the test can catch the problem, I removed
`select_for_update()` and ran it five times. It failed every time, with
both users registered. With the lock back in place it passed five times
out of five.

## API endpoints

Interactive docs are at `/api/docs/` and the raw schema is at `/api/schema/`.

| Method | Path | Who can call it | Purpose |
| --- | --- | --- | --- |
| GET | `/api/health/` | Anyone | Checks the database connection and returns `{"status": "ok"}` |
| POST | `/api/auth/register/` | Anyone | Create an account (never an organiser) |
| POST | `/api/auth/token/` | Anyone | Log in and get an access and a refresh token |
| POST | `/api/auth/token/refresh/` | Anyone with a refresh token | Get a new access token and a new refresh token |
| POST | `/api/auth/logout/` | Logged in | Blacklist your refresh token |
| GET | `/api/auth/me/` | Logged in | Your own profile |
| GET | `/api/events/` | Anyone | List visible events. Supports `?search=`, `?starts_after=`, `?starts_before=`, `?ordering=starts_at` or `-starts_at`, and `?page=` |
| POST | `/api/events/` | Organisers | Create an event. You become its organiser |
| GET | `/api/events/{id}/` | Anyone | One event, if you are allowed to see it |
| PUT, PATCH | `/api/events/{id}/` | The event's organiser | Edit the event. Capacity can't go below the confirmed count |
| DELETE | `/api/events/{id}/` | The event's organiser | Delete the event. Returns 409 if it has confirmed registrations |
| POST | `/api/events/{id}/register/` | Logged in | Register for the event, with optional `phone` and `note` |
| GET | `/api/events/{id}/attendees/` | The event's organiser | Confirmed attendees with contact details |
| GET | `/api/registrations/` | Logged in | Your own registrations, newest first. Supports `?status=` |
| GET | `/api/registrations/{id}/` | The registration's owner | One of your registrations |
| POST | `/api/registrations/{id}/cancel/` | The registration's owner | Cancel it before the event starts |

## Auth flow

1. **Register.** `POST /api/auth/register/` with a username, email and
   password. The password goes through Django's password validators.
2. **Log in.** `POST /api/auth/token/` with your username and password.
   You get an `access` token (valid for 15 minutes) and a `refresh` token
   (valid for 7 days). The username is matched ignoring letter case.
3. **Authorize.** Send the access token as `Authorization: Bearer <token>`.
   In Swagger UI, click **Authorize** and paste the access token.
4. **Refresh.** When the access token expires, `POST /api/auth/token/refresh/`
   with the refresh token. You get a new pair, and the old refresh token
   stops working.
5. **Log out.** `POST /api/auth/logout/` with your refresh token. It is
   blacklisted and can't be used again.

New accounts are never organisers. To make someone an organiser, log in to
`/admin/` as a superuser, open **Users**, pick the user, tick
**Is organiser** and save.

## Running locally with Docker

You need Docker with Compose.

```bash
cp .env.example .env
# Edit .env: set SECRET_KEY, JWT_SIGNING_KEY, POSTGRES_PASSWORD (and the
# same password inside DATABASE_URL) and DEMO_PASSWORD.

docker compose up --build
```

The web container waits for Postgres, runs the migrations and starts
gunicorn. The API is at <http://localhost:8001/api/docs/>. Postgres is also
available on the host at port 5434.

In a second terminal, add demo data and an admin account:

```bash
docker compose exec web python manage.py seed_demo
docker compose exec web python manage.py createsuperuser
```

`seed_demo` creates `organiser_demo`, three attendees (`attendee_amara`,
`attendee_ben`, `attendee_chioma`), five events (one draft, one nearly full,
one full) and a few registrations, including a cancelled one. All demo
accounts use the `DEMO_PASSWORD` value. Running it again doesn't create
duplicates. It refuses to run when `DEBUG` is False unless you pass
`--force`.

## Running without Docker

You still need a Postgres database. The easiest way is to start only the
database container with `docker compose up -d db`, or you can point
`DATABASE_URL` at your own Postgres.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # then fill in the values
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo    # optional
python manage.py runserver
```

The API is then at <http://localhost:8000/api/docs/>.

## Environment variables

| Variable | Example | What it does |
| --- | --- | --- |
| `SECRET_KEY` | `change-me-to-a-long-random-string` | Django's secret key (sessions, CSRF, password reset links) |
| `JWT_SIGNING_KEY` | `change-me-to-a-different-long-random-string` | Signs JWTs. Keep it different from `SECRET_KEY`. Changing it logs out every API user |
| `DEBUG` | `True` | Django debug mode. Use `False` in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names the site answers to |
| `SECURE_COOKIES` | `False` | When `DEBUG` is False, sends session and CSRF cookies over HTTPS only. Set to `True` once the site uses HTTPS |
| `POSTGRES_DB` | `event_registration` | Database name for the Postgres container |
| `POSTGRES_USER` | `event_user` | Database user for the Postgres container |
| `POSTGRES_PASSWORD` | `change-me` | Database password for the Postgres container |
| `DATABASE_URL` | `postgres://event_user:change-me@localhost:5434/event_registration` | How the app connects to Postgres from the host. Docker Compose replaces it inside the web container so it points at the `db` service |
| `DEMO_PASSWORD` | `change-me-demo-password` | Password for the accounts that `seed_demo` creates |

Generate random keys with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## Tests and linting

```bash
pytest                  # 167 tests, needs the database from .env
ruff check .
ruff format --check .
```

The tests create and drop their own test database, so they don't touch
your data. GitHub Actions runs the same three commands against Postgres 16
on every push and pull request. See the badge at the top of this file.

## Secret check

A pre-commit hook in `.githooks/pre-commit` blocks any commit that stages a
`.env` file, a generated Django "insecure" secret key, or a value copied from
your local `.env`. It also blocks the commit if the check itself fails.

Git does not enable repository hooks automatically, so after cloning run
this once:

```bash
git config core.hooksPath .githooks
```

## Production notes

- **Rate limits need a shared cache.** Throttle counters are kept in Django's
  default cache, which lives in each process's memory. The Docker image runs
  three gunicorn workers, so each worker keeps its own count and a client can
  get roughly three times the limit. In production, set `CACHES` to Redis so
  all workers share one count.
- **Set `NUM_PROXIES` behind a proxy.** Rate limits are tracked per client
  IP. Behind a load balancer or reverse proxy, every request seems to come
  from the proxy unless you set `REST_FRAMEWORK["NUM_PROXIES"]` to the number
  of proxies in front of the app. Then DRF reads the real IP from
  `X-Forwarded-For`. Don't set it higher than the real number, or clients
  can fake their IP with that header.
- **Logout doesn't end the access token.** Logging out blacklists the refresh
  token, but an access token that was already issued keeps working until it
  expires, which is at most 15 minutes. Keep the access token lifetime short.
- Set `DEBUG=False`, a real `ALLOWED_HOSTS`, and `SECURE_COOKIES=True` once
  HTTPS is in place.

## Screenshots

### Swagger UI

_Screenshot to be added._

### Event list

_Screenshot to be added._

### Registering for an event

_Screenshot to be added._

### Attendee list (organiser view)

_Screenshot to be added._

### Django admin: approving an organiser

_Screenshot to be added._
