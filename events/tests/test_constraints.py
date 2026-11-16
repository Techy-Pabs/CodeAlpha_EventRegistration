from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from events.models import Event, Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def organiser():
    return get_user_model().objects.create_user(username="org", password="pw-12345!", is_organiser=True)


@pytest.fixture
def attendee():
    return get_user_model().objects.create_user(username="att", password="pw-12345!")


def make_event(organiser, **overrides):
    start = timezone.now() + timedelta(days=7)
    data = {
        "title": "Django Meetup",
        "location": "Lagos",
        "starts_at": start,
        "ends_at": start + timedelta(hours=2),
        "capacity": 50,
        "organiser": organiser,
    }
    data.update(overrides)
    return Event.objects.create(**data)


@pytest.fixture
def event(organiser):
    return make_event(organiser)


# --- Event constraints ---------------------------------------------------

def test_valid_event_is_saved(event):
    assert Event.objects.filter(pk=event.pk).exists()


def test_event_end_before_start_is_rejected(organiser):
    start = timezone.now()
    with pytest.raises(IntegrityError, match="event_ends_after_starts"), transaction.atomic():
        make_event(organiser, starts_at=start, ends_at=start - timedelta(hours=1))


def test_event_end_equal_to_start_is_rejected(organiser):
    start = timezone.now()
    with pytest.raises(IntegrityError, match="event_ends_after_starts"), transaction.atomic():
        make_event(organiser, starts_at=start, ends_at=start)


def test_event_capacity_zero_is_rejected(organiser):
    with pytest.raises(IntegrityError, match="event_capacity_at_least_1"), transaction.atomic():
        make_event(organiser, capacity=0)


# --- Registration constraints --------------------------------------------

def test_duplicate_confirmed_registration_is_rejected(event, attendee):
    Registration.objects.create(user=attendee, event=event)
    with pytest.raises(IntegrityError, match="unique_confirmed_registration_per_user_event"), transaction.atomic():
        Registration.objects.create(user=attendee, event=event)
    assert Registration.objects.filter(user=attendee, event=event).count() == 1


def test_reregistering_after_cancelling_is_allowed(event, attendee):
    first = Registration.objects.create(user=attendee, event=event)
    first.status = Registration.Status.CANCELLED
    first.cancelled_at = timezone.now()
    first.save()

    Registration.objects.create(user=attendee, event=event)  # must not raise

    assert Registration.objects.filter(user=attendee, event=event).count() == 2
    assert Registration.objects.filter(
        user=attendee, event=event, status=Registration.Status.CONFIRMED
    ).count() == 1


def test_registration_note_over_500_chars_is_rejected(event, attendee):
    with pytest.raises(IntegrityError, match="registration_note_max_500"), transaction.atomic():
        Registration.objects.create(user=attendee, event=event, note="x" * 501)


def test_registration_defaults_and_optional_fields(event, attendee):
    reg = Registration.objects.create(user=attendee, event=event)
    assert reg.status == Registration.Status.CONFIRMED
    assert reg.phone == "" and reg.note == "" and reg.cancelled_at is None
    assert str(reg) == "att -> Django Meetup [confirmed]"
