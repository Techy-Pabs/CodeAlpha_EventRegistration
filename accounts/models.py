from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

DUPLICATE_USERNAME = "A user with that username already exists."


class User(AbstractUser):
    """Project user. Organisers can create and manage events."""

    is_organiser = models.BooleanField(default=False)

    class Meta(AbstractUser.Meta):
        constraints = [
            # Usernames are unique ignoring case: "Alice" blocks "alice".
            # The username is still stored exactly as typed.
            models.UniqueConstraint(
                Lower("username"),
                name="user_username_ci_unique",
                violation_error_message=DUPLICATE_USERNAME,
            ),
            # Emails are unique ignoring case. Blank emails (e.g. a superuser
            # created without one) are left out so several can coexist.
            models.UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="user_email_ci_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        # Normalise here, not only in the API serializer, so users created in
        # the admin, the shell or a data migration are stored the same way.
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username
