"""Create demo users, events and registrations for trying the API.

Safe to run more than once: rows are looked up by username or event title
and updated in place, so a second run changes nothing (apart from moving
event dates so they stay in the future).
"""

import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from events.models import Event, Registration

User = get_user_model()

ORGANISER = "organiser_demo"
ATTENDEES = ["attendee_amara", "attendee_ben", "attendee_chioma"]

# title: (days from now, capacity, published, description, location)
EVENTS = {
    "Intro to Django REST Framework": (
        7,
        30,
        True,
        "Build and document a small API in an afternoon.",
        "Lagos, Yaba Tech Hub",
    ),
    "Backend Career Panel": (
        14,
        50,
        True,
        "Engineers talk about their first backend roles.",
        "Online",
    ),
    "Postgres Performance Workshop": (
        21,
        25,
        False,  # draft: only organiser_demo sees it
        "Indexes, EXPLAIN and query plans.",
        "Abuja, Civic Centre",
    ),
    "Small Group Code Review": (
        10,
        3,  # nearly full: 2 of 3 seats taken
        True,
        "Bring a pull request, get feedback.",
        "Lagos, Yaba Tech Hub",
    ),
    "Docker Hands-on Lab": (
        5,
        2,  # full: 2 of 2 seats taken
        True,
        "Containerise a Django app step by step.",
        "Port Harcourt, Innovation Hub",
    ),
}

# (attendee, event title, status)
REGISTRATIONS = [
    ("attendee_amara", "Small Group Code Review", Registration.Status.CONFIRMED),
    ("attendee_ben", "Small Group Code Review", Registration.Status.CONFIRMED),
    ("attendee_amara", "Docker Hands-on Lab", Registration.Status.CONFIRMED),
    ("attendee_chioma", "Docker Hands-on Lab", Registration.Status.CONFIRMED),
    ("attendee_ben", "Intro to Django REST Framework", Registration.Status.CONFIRMED),
    ("attendee_chioma", "Intro to Django REST Framework", Registration.Status.CANCELLED),
]


class Command(BaseCommand):
    help = "Create demo users, events and registrations (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is False (e.g. on a staging server).",
        )

    def handle(self, *args, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError(
                "DEBUG is False, so this looks like production. "
                "Refusing to create demo accounts. Pass --force to run anyway."
            )
        password = os.environ.get("DEMO_PASSWORD", "")
        if not password:
            raise CommandError("Set DEMO_PASSWORD in the environment (or .env) first.")

        with transaction.atomic():
            organiser = self._user(ORGANISER, password, is_organiser=True)
            users = {name: self._user(name, password) for name in ATTENDEES}
            events = {title: self._event(title, organiser, *spec) for title, spec in EVENTS.items()}
            for username, title, status in REGISTRATIONS:
                self._registration(users[username], events[title], status)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: 1 organiser ({ORGANISER}), {len(ATTENDEES)} attendees "
                f"({', '.join(ATTENDEES)}), {len(EVENTS)} events, "
                f"{len(REGISTRATIONS)} registrations. Password: the DEMO_PASSWORD value."
            )
        )

    def _user(self, username, password, is_organiser=False):
        user, _ = User.objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com"}
        )
        user.is_organiser = is_organiser
        user.is_active = True
        user.set_password(password)  # follows DEMO_PASSWORD if it changes
        user.save()
        return user

    def _event(self, title, organiser, days, capacity, published, description, location):
        starts_at = timezone.now() + timedelta(days=days)
        event, _ = Event.objects.update_or_create(
            title=title,
            organiser=organiser,
            defaults={
                "description": description,
                "location": location,
                "starts_at": starts_at,
                "ends_at": starts_at + timedelta(hours=3),
                # Never below the current confirmed count, in case someone
                # registered through the API since the last run.
                "capacity": max(
                    capacity,
                    Registration.objects.filter(
                        event__title=title,
                        event__organiser=organiser,
                        status=Registration.Status.CONFIRMED,
                    ).count(),
                ),
                "is_published": published,
            },
        )
        return event

    def _registration(self, user, event, status):
        if Registration.objects.filter(user=user, event=event, status=status).exists():
            return  # already seeded
        if status == Registration.Status.CANCELLED:
            Registration.objects.create(
                user=user, event=event, status=status, cancelled_at=timezone.now()
            )
            return
        confirmed = Registration.objects.filter(event=event, status=Registration.Status.CONFIRMED)
        if confirmed.count() < event.capacity:  # never overbook, even in demo data
            Registration.objects.create(user=user, event=event, status=status)
