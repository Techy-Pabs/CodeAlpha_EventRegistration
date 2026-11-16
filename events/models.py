from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Length
from django.db.models.lookups import LessThanOrEqual


class Event(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    organiser = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organised_events",
    )
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="event_ends_after_starts",
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=1),
                name="event_capacity_at_least_1",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.starts_at:%Y-%m-%d %H:%M})"


class Registration(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    phone = models.CharField(max_length=20, blank=True)
    note = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event"],
                condition=Q(status="confirmed"),
                name="unique_confirmed_registration_per_user_event",
            ),
            # TextField max_length is only enforced by forms; enforce it in the DB too.
            models.CheckConstraint(
                condition=LessThanOrEqual(Length("note"), 500),
                name="registration_note_max_500",
            ),
        ]

    def __str__(self):
        return f"{self.user} -> {self.event.title} [{self.status}]"
