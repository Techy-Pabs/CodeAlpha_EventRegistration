from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Project user. Organisers can create and manage events."""

    is_organiser = models.BooleanField(default=False)

    def __str__(self):
        return self.username
