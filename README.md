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
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | Comma-separated full origins (with `https://`) allowed to submit forms such as the admin login. Needed on HTTPS |
| `SECURE_SSL_REDIRECT` | `False` | Redirects HTTP to HTTPS and sends a one-day HSTS header. `/api/health/` is never redirected |
| `DATABASE_CONN_MAX_AGE` | `60` | Seconds to keep reusing a database connection. `0` reconnects on every request |
| `NUM_PROXIES` | *(empty)* | Number of proxies in front of the app, so rate limits see each client's real IP. Leave empty locally |
| `WEB_CONCURRENCY` | `2` | Number of gunicorn worker processes (Docker image only) |
| `PORT` | *(unset)* | Port gunicorn listens on (Docker image only). Render sets it; defaults to `8000` |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | *(unset)* | If all three are set, the container creates this admin account on start (if it doesn't exist yet) |
| `SEED_DEMO_ON_START` | *(unset)* | `True` runs `seed_demo --force` every time the container starts |

Generate random keys with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## Tests and linting

```bash
pytest                  # 207 tests, needs the database from .env
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

## Deployment

The API runs on [Render](https://render.com) as a free Docker web service,
with the database on [Neon](https://neon.tech) (free PostgreSQL). Docker
Compose is only for local development; on Render the container connects to
Neon over the internet.

### What the container does when it starts

`docker/entrypoint.sh` runs these steps in order. If any of them fails, it
prints a line starting with `ERROR:` and exits without starting the app. On
Render the deploy is then marked as failed and the previous version keeps
serving, so the app never runs half set up.

1. Waits for the database (up to 30 seconds).
2. Applies migrations.
3. Creates the admin account from the `DJANGO_SUPERUSER_*` variables, if all
   three are set and that username doesn't exist yet. An existing account is
   left as it is, so a password you change in the admin isn't reset on the
   next start. The password is never printed.
4. Runs `seed_demo --force` if `SEED_DEMO_ON_START` is `True`.
5. Starts gunicorn on `0.0.0.0:$PORT` with `WEB_CONCURRENCY` workers (2 by
   default, which fits the free plan's 512 MB of RAM).

Steps 3 and 4 exist because Render's free plan has no shell, so you can't
run `createsuperuser` or `seed_demo` by hand.

### 1. Create the database on Neon

1. Create a Neon project. Choose PostgreSQL 16 to match the local setup, and
   a region close to the Render region you'll pick.
2. On the project dashboard, open **Connect**. Turn off **Connection
   pooling** so you get the direct connection string (its host name doesn't
   contain `-pooler`). The app keeps its own connections open for a minute
   at a time, so it doesn't need Neon's pooler, and migrations run on every
   start.
3. Copy the connection string. It looks like this:

   ```
   postgresql://USER:PASSWORD@ep-example-123456.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```

   Paste it into Render unchanged. `sslmode=require` and
   `channel_binding=require` are passed to the database driver, so the
   connection is encrypted. Treat the whole string as a secret, because it
   contains the database password.

The tables are created by the migrations on the first start.

### 2. Create the web service on Render

1. In Render, choose **New**, then **Web Service**, and connect this GitHub
   repository. Pick the `main` branch.
2. Set **Language** to **Docker**. Render builds the `Dockerfile` in the
   project root. Leave the Docker command empty, so the image's own
   entrypoint and gunicorn command run.
3. Choose the **Free** instance type, in a region close to your Neon region.
4. Under **Advanced**, set **Health Check Path** to `/api/health/`. It
   returns 200 only when the database answers, and it's exempt from the
   HTTPS redirect.
5. Add the environment variables below, then create the service.

Render gives the service an address such as `your-app.onrender.com`. Use
it in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. If you don't know it yet,
create the service first, then set those two variables and let it redeploy.

Every push to `main` then triggers a new build and deploy.

### Environment variables on Render

| Variable | Value | What it's for |
| --- | --- | --- |
| `SECRET_KEY` | A new random value, not your local one | Django's signing key for sessions, CSRF and password reset links |
| `JWT_SIGNING_KEY` | A different new random value | Signs the API's access and refresh tokens |
| `DEBUG` | `False` | Turns off debug pages and turns on the production hardening |
| `ALLOWED_HOSTS` | `your-app.onrender.com` | The host name the site answers to |
| `CSRF_TRUSTED_ORIGINS` | `https://your-app.onrender.com` | Lets the admin login form work over HTTPS |
| `SECURE_SSL_REDIRECT` | `True` | Redirects HTTP to HTTPS and sends a one-day HSTS header |
| `SECURE_COOKIES` | `True` | Sends session and CSRF cookies over HTTPS only |
| `DATABASE_URL` | The Neon connection string, unchanged | How the app reaches the database |
| `NUM_PROXIES` | `1` to start with (see below) | Lets rate limiting see each visitor's IP instead of Render's proxy |
| `DJANGO_SUPERUSER_USERNAME` | e.g. `admin` | Username of the admin account created on start |
| `DJANGO_SUPERUSER_EMAIL` | Your email | Email of that admin account |
| `DJANGO_SUPERUSER_PASSWORD` | A new strong password | Its password. It must pass Django's password checks, or startup stops with the reason |
| `SEED_DEMO_ON_START` | `True` for a demo, otherwise leave it out | Loads the demo users, events and registrations on every start |
| `DEMO_PASSWORD` | A new random value | Password of the demo accounts. Required when `SEED_DEMO_ON_START` is `True` |
| `WEB_CONCURRENCY` | Optional, default `2` | Number of gunicorn workers. Keep it at 2 on the free plan |
| `DATABASE_CONN_MAX_AGE` | Optional, default `60` | Seconds to reuse a database connection |

Not needed on Render: `PORT` (Render sets it) and `POSTGRES_DB`,
`POSTGRES_USER` and `POSTGRES_PASSWORD` (they only configure the local
database container).

Generate random values with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Notes:

- **The admin variables are all or nothing.** If only one or two of the
  `DJANGO_SUPERUSER_*` variables are set, startup stops with an error naming
  the missing one. After the first successful deploy you can delete all
  three. The account stays in the database.
- **Demo data is reloaded on every start** while `SEED_DEMO_ON_START` is
  `True`, and on the free plan that's every time the service wakes up.
  `seed_demo` doesn't duplicate anything. It does reset the demo accounts'
  passwords to `DEMO_PASSWORD`, move the demo events back into the future
  and re-book demo registrations that were cancelled. Data created by other
  users is not touched.

### Checking NUM_PROXIES on Render

On Render a request passes through Cloudflare and Render's own proxy before
it reaches the app, and each proxy adds an address to the end of the
`X-Forwarded-For` header. A visitor can put anything at the start of that
header, so DRF counts `NUM_PROXIES` entries from the end. `1` takes the
last entry, which a proxy always writes, so a visitor can't fake it. If that
entry turns out to be a Cloudflare address, many visitors would share one
rate limit, and `2` is the right value. To check:

1. On Render, temporarily add this environment variable, which makes
   gunicorn's access log show the header:

   ```
   GUNICORN_CMD_ARGS=--access-logformat '%(h)s xff="%({x-forwarded-for}i)s" "%(r)s" %(s)s'
   ```

2. Open the site from your own device. Find the request in Render's
   **Logs**, and find your own public IP (search "what is my IP").
3. If your IP is the **last** entry in `xff="..."`, keep `NUM_PROXIES=1`.
   If it's the second to last, and the last is a Cloudflare address, set
   `NUM_PROXIES=2`.
4. Delete `GUNICORN_CMD_ARGS` again, so the logs stop recording IP
   addresses.

Never set it higher than the number of addresses that the proxies add. A
visitor could then choose their own IP and avoid the rate limit.

### Free plan behaviour

- **It sleeps.** A free Render web service goes to sleep after about 15
  minutes without requests. The next request wakes it up, which takes up to
  about a minute (the container also runs the migrations and startup tasks
  again), so the first request after a quiet period is slow. It's fast
  again once awake.
- **Neon pauses too.** Neon's free plan suspends the database when it's
  idle and resumes it on the next query, which adds a short delay.
  Connections that Neon closed are detected and replaced (Django's
  `CONN_HEALTH_CHECKS`), so they don't cause errors.
- **One instance, little memory.** 512 MB of RAM, which is why the default
  is two gunicorn workers. Rate limit counters live in each worker's memory
  and reset when the service restarts.
- **No shell, no scheduled jobs.** Use the startup variables above instead
  of `manage.py` commands.

## Production notes

- **Rate limits need a shared cache.** Throttle counters are kept in Django's
  default cache, which lives in each process's memory. The Docker image runs
  two gunicorn workers by default (`WEB_CONCURRENCY`), so each worker keeps
  its own count and a client can get roughly twice the limit. For strict
  limits, set `CACHES` to Redis so all workers share one count.
- **Set `NUM_PROXIES` behind a proxy.** Rate limits are tracked per client
  IP. Behind a load balancer or reverse proxy, every request seems to come
  from the proxy unless you set the `NUM_PROXIES` environment variable to the
  number of proxies in front of the app. Then DRF reads the real IP from
  `X-Forwarded-For`. Don't set it higher than the real number, or clients
  can fake their IP with that header. See
  [Checking NUM_PROXIES on Render](#checking-num_proxies-on-render).
- **Logout doesn't end the access token.** Logging out blacklists the refresh
  token, but an access token that was already issued keeps working until it
  expires, which is at most 15 minutes. Keep the access token lifetime short.
- Set `DEBUG=False`, a real `ALLOWED_HOSTS`, and `SECURE_COOKIES=True` once
  HTTPS is in place.

## Screenshots

These were taken from the Docker setup after running `seed_demo`.

### Swagger UI

![Swagger UI listing the auth, events, health and registrations endpoints](docs/screenshots/01-swagger-overview.png)

All the endpoints in Swagger UI, grouped into auth, events, health and registrations.

### Event list

![GET /api/events/ returning seed events with seats_left](docs/screenshots/02-event-list.png)

The public event list, where each event shows how many seats are left.

### Registering for an event

![POST /api/events/2/register/ returning 201 Created](docs/screenshots/03-register-success.png)

An attendee registers with a phone number and a note and gets a confirmed registration back.

### Registering for a full event

![POST /api/events/5/register/ returning 409 Event is full](docs/screenshots/04-event-full.png)

The same attendee tries to book an event with no seats left and gets a 409.

### My registrations

![GET /api/registrations/ listing the attendee's own registrations](docs/screenshots/05-my-registrations.png)

The attendee's own registrations, newest first, with the event title and start time.

### Django admin

![Django admin change page for an event with its registrations inline](docs/screenshots/06-admin-event.png)

An event in the Django admin, with its registrations listed underneath, including a cancelled one.

### Attendee list (organiser view)

![GET /api/events/4/attendees/ showing confirmed attendees](docs/screenshots/07-attendees.png)

The organiser sees the confirmed attendees of the nearly full event, with their contact details.
