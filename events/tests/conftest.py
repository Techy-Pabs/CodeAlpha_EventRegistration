from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from events.models import Event, Registration

User = get_user_model()


def make_user(username, **extra):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="pw-12345!", **extra
    )


def make_event(organiser, *, starts_in=timedelta(days=7), **overrides):
    start = timezone.now() + starts_in
    data = {
        "title": "Django Meetup",
        "description": "Talks and pizza",
        "location": "Lagos",
        "starts_at": start,
        "ends_at": start + timedelta(hours=2),
        "capacity": 10,
        "organiser": organiser,
        "is_published": True,
    }
    data.update(overrides)
    return Event.objects.create(**data)


def confirm(user, event, **extra):
    return Registration.objects.create(user=user, event=event, **extra)


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


@pytest.fixture
def organiser(db):
    return make_user("org", is_organiser=True)


@pytest.fixture
def other_organiser(db):
    return make_user("org2", is_organiser=True)


@pytest.fixture
def attendee(db):
    return make_user("att")


@pytest.fixture
def event(organiser):
    return make_event(organiser)
