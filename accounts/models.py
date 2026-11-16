from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class User(AbstractUser):
    """Project user. Organisers can create and manage events."""

    is_organiser = models.BooleanField(default=False)

    class Meta(AbstractUser.Meta):
        constraints = [
            # Emails are unique ignoring case. Blank emails (e.g. a superuser
            # created without one) are left out so several can coexist.
            models.UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="user_email_ci_unique",
            ),
        ]

    def __str__(self):
        return self.username
