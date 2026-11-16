"""Two people grab the last seat at the same instant: exactly one gets it.

transaction=True makes these real committed transactions on separate
connections (the normal test wrapper runs everything in one transaction,
where row locks between threads can't be observed).
"""

import threading

import pytest
from django.db import connection
from django.urls import reverse

from events.models import Registration

from .conftest import client_for, make_event, make_user


@pytest.mark.django_db(transaction=True)
def test_two_users_racing_for_last_seat():
    organiser = make_user("org", is_organiser=True)
    event = make_event(organiser, capacity=1)
    racers = [make_user("racer1"), make_user("racer2")]
    url = reverse("events:event-register", args=[event.pk])

    barrier = threading.Barrier(len(racers))
    results = {}
    errors = []

    def attempt(user):
        try:
            client = client_for(user)
            barrier.wait(timeout=10)  # release both threads together
            results[user.username] = client.post(url, {}, format="json")
        except Exception as exc:  # surface thread failures in the main thread
            errors.append(exc)
        finally:
            connection.close()  # each thread opened its own DB connection

    threads = [threading.Thread(target=attempt, args=(u,)) for u in racers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    codes = sorted(r.status_code for r in results.values())
    assert codes == [201, 409], codes
    loser = next(r for r in results.values() if r.status_code == 409)
    assert loser.data["detail"] == "Event is full."
    assert Registration.objects.filter(event=event, status="confirmed").count() == 1
