import pytest
from django.contrib.auth import get_user_model

from accounts.models import User


def test_custom_user_model_is_active():
    assert get_user_model() is User


@pytest.mark.django_db
def test_is_organiser_defaults_to_false():
    user = get_user_model().objects.create_user(username="alice", password="pw-12345!")
    assert user.is_organiser is False
