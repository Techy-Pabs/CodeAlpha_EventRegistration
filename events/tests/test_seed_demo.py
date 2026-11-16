from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from events.models import Event, Registration

User = get_user_model()

pytestmark = pytest.mark.django_db

DEMO_PASSWORD = "Demo-Pass-For-Tests-1"


@pytest.fixture
def demo_env(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)


def seed(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def snapshot():
    """Everything the command creates, in a comparable form."""
    return {
        "users": sorted(User.objects.values_list("username", "is_organiser")),
        "events": sorted(Event.objects.values_list("title", "capacity", "is_published")),
        "registrations": sorted(
            Registration.objects.values_list("user__username", "event__title", "status")
        ),
    }


def seats_left(title):
    event = Event.objects.get(title=title)
    taken = event.registrations.filter(status=Registration.Status.CONFIRMED).count()
    return event.capacity - taken


def test_creates_expected_data(demo_env):
    output = seed()
    assert "Demo data ready" in output
    assert DEMO_PASSWORD not in output  # never echo the password

    organiser = User.objects.get(username="organiser_demo")
    assert organiser.is_organiser
    attendees = User.objects.filter(username__startswith="attendee_")
    assert attendees.count() == 3
    assert not attendees.filter(is_organiser=True).exists()

    assert Event.objects.count() == 5
    assert set(Event.objects.values_list("organiser", flat=True)) == {organiser.pk}
    assert Event.objects.filter(is_published=False).count() == 1
    assert not Event.objects.filter(starts_at__lte=timezone.now()).exists()  # all upcoming

    assert seats_left("Docker Hands-on Lab") == 0  # full
    assert seats_left("Small Group Code Review") == 1  # nearly full

    assert Registration.objects.filter(status="cancelled").count() == 1
    cancelled = Registration.objects.get(status="cancelled")
    assert cancelled.cancelled_at is not None


def test_running_twice_creates_nothing_new(demo_env):
    seed()
    first = snapshot()
    seed()
    assert snapshot() == first
    assert User.objects.count() == 4
    assert Event.objects.count() == 5
    assert Registration.objects.count() == 6


def test_demo_users_can_log_in_with_demo_password(demo_env):
    seed()
    for username in ["organiser_demo", "attendee_amara", "attendee_ben", "attendee_chioma"]:
        assert authenticate(username=username, password=DEMO_PASSWORD) is not None


def test_rerun_picks_up_new_password(demo_env, monkeypatch):
    seed()
    monkeypatch.setenv("DEMO_PASSWORD", "A-Different-Pass-2")
    seed()
    assert authenticate(username="attendee_ben", password="A-Different-Pass-2") is not None
    assert authenticate(username="attendee_ben", password=DEMO_PASSWORD) is None


def test_rerun_restores_cancelled_seed_registration(demo_env):
    """If a demo user cancels via the API, the next run books them again."""
    seed()
    reg = Registration.objects.get(
        user__username="attendee_ben", event__title="Small Group Code Review"
    )
    reg.status = Registration.Status.CANCELLED
    reg.cancelled_at = timezone.now()
    reg.save()
    seed()
    assert seats_left("Small Group Code Review") == 1


def test_rerun_never_overbooks_or_lowers_capacity(demo_env):
    """Someone took the last seat through the API; seeding must not break the event."""
    seed()
    event = Event.objects.get(title="Small Group Code Review")
    extra = User.objects.create_user("walk_in", "walk_in@example.com", "pw-12345!")
    Registration.objects.create(user=extra, event=event)
    seed()
    event.refresh_from_db()
    assert event.capacity == 3
    assert seats_left("Small Group Code Review") == 0


def test_refuses_when_debug_is_false(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)
    with pytest.raises(CommandError, match="--force"):
        seed()
    assert not User.objects.exists()


def test_force_runs_when_debug_is_false(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)
    seed("--force")
    assert Event.objects.count() == 5


@pytest.mark.parametrize("value", [None, ""])
def test_requires_demo_password(settings, monkeypatch, value):
    settings.DEBUG = True
    if value is None:
        monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("DEMO_PASSWORD", value)
    with pytest.raises(CommandError, match="DEMO_PASSWORD"):
        seed()
    assert not User.objects.exists()
