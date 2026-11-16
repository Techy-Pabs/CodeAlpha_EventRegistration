from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from events.models import Registration

from .conftest import client_for, confirm, make_event, make_user

pytestmark = pytest.mark.django_db

MY_REGISTRATIONS = reverse("events:registration-list")


def register_url(event):
    return reverse("events:event-register", args=[event.pk])


def attendees_url(event):
    return reverse("events:event-attendees", args=[event.pk])


def reg_url(registration):
    return reverse("events:registration-detail", args=[registration.pk])


def cancel_url(registration):
    return reverse("events:registration-cancel", args=[registration.pk])


def cancel(registration):
    registration.status = Registration.Status.CANCELLED
    registration.cancelled_at = timezone.now()
    registration.save()
    return registration


# --- register ---------------------------------------------------------------------


def test_register_creates_confirmed_registration(attendee, event):
    response = client_for(attendee).post(
        register_url(event), {"phone": "+234 801-234 5678", "note": "Vegetarian"}, format="json"
    )
    assert response.status_code == 201, response.data
    assert response.data["status"] == "confirmed"
    assert response.data["phone"] == "+234 801-234 5678"
    assert response.data["note"] == "Vegetarian"
    assert response.data["event"]["id"] == event.pk
    reg = Registration.objects.get(pk=response.data["id"])
    assert reg.user == attendee and reg.event == event


def test_register_with_empty_body(attendee, event):
    response = client_for(attendee).post(register_url(event), {}, format="json")
    assert response.status_code == 201
    assert response.data["phone"] == "" and response.data["note"] == ""


def test_register_requires_login(event):
    assert client_for().post(register_url(event), {}, format="json").status_code == 401


@pytest.mark.parametrize("phone", ["0801 234 abc", "(0801) 234", "080.123", "1" * 21])
def test_register_rejects_bad_phone(attendee, event, phone):
    response = client_for(attendee).post(register_url(event), {"phone": phone}, format="json")
    assert response.status_code == 400
    assert "phone" in response.data
    assert not Registration.objects.exists()


def test_register_accepts_20_char_phone(attendee, event):
    phone = "+" + "1" * 19
    response = client_for(attendee).post(register_url(event), {"phone": phone}, format="json")
    assert response.status_code == 201


def test_register_rejects_note_over_500(attendee, event):
    response = client_for(attendee).post(register_url(event), {"note": "x" * 501}, format="json")
    assert response.status_code == 400
    assert "note" in response.data


def test_register_accepts_500_char_note(attendee, event):
    response = client_for(attendee).post(register_url(event), {"note": "x" * 500}, format="json")
    assert response.status_code == 201


def test_register_unknown_event_404(attendee):
    response = client_for(attendee).post("/api/events/999999/register/", {}, format="json")
    assert response.status_code == 404


def test_register_unpublished_event_404(attendee, organiser):
    draft = make_event(organiser, is_published=False)
    assert client_for(attendee).post(register_url(draft), {}, format="json").status_code == 404


def test_organiser_cannot_register_for_own_draft_404(organiser):
    """Published is required even for the organiser, who can see the draft."""
    draft = make_event(organiser, is_published=False)
    assert client_for(organiser).post(register_url(draft), {}, format="json").status_code == 404


def test_register_started_event_400(attendee, organiser):
    started = make_event(organiser, starts_in=-timedelta(minutes=5))
    response = client_for(attendee).post(register_url(started), {}, format="json")
    assert response.status_code == 400
    assert "started" in response.data["detail"]


def test_organiser_cannot_register_for_own_event_400(organiser, event):
    response = client_for(organiser).post(register_url(event), {}, format="json")
    assert response.status_code == 400
    assert "own event" in response.data["detail"]


def test_other_organiser_can_register(other_organiser, event):
    assert (
        client_for(other_organiser).post(register_url(event), {}, format="json").status_code == 201
    )


def test_register_twice_409(attendee, event):
    client = client_for(attendee)
    assert client.post(register_url(event), {}, format="json").status_code == 201
    second = client.post(register_url(event), {}, format="json")
    assert second.status_code == 409
    assert "already registered" in second.data["detail"]
    assert Registration.objects.filter(user=attendee, event=event).count() == 1


def test_register_full_event_409(attendee, organiser):
    full = make_event(organiser, capacity=1)
    confirm(make_user("first"), full)
    response = client_for(attendee).post(register_url(full), {}, format="json")
    assert response.status_code == 409
    assert response.data["detail"] == "Event is full."


def test_cancelled_registrations_do_not_take_seats(attendee, organiser):
    event = make_event(organiser, capacity=1)
    cancel(confirm(make_user("first"), event))
    assert client_for(attendee).post(register_url(event), {}, format="json").status_code == 201


def test_check_order_started_before_organiser(organiser):
    """Checks run in the documented order: 'started' wins over 'own event'."""
    started = make_event(organiser, starts_in=-timedelta(minutes=5))
    response = client_for(organiser).post(register_url(started), {}, format="json")
    assert "started" in response.data["detail"]


def test_check_order_already_registered_before_full(attendee, organiser):
    event = make_event(organiser, capacity=1)
    confirm(attendee, event)
    response = client_for(attendee).post(register_url(event), {}, format="json")
    assert "already registered" in response.data["detail"]


def test_register_updates_seats_left(attendee, event):
    client_for(attendee).post(register_url(event), {}, format="json")
    detail = client_for().get(reverse("events:event-detail", args=[event.pk]))
    assert detail.data["seats_left"] == 9


# --- my registrations ---------------------------------------------------------------


@pytest.fixture
def my_regs(attendee, organiser):
    """Two of attendee's registrations (oldest first) and one of someone else's."""
    first = confirm(attendee, make_event(organiser, title="First"))
    second = cancel(confirm(attendee, make_event(organiser, title="Second")))
    others = confirm(make_user("bob"), make_event(organiser, title="Bob's"))
    return first, second, others


def test_list_shows_only_my_registrations_newest_first(attendee, my_regs):
    first, second, _ = my_regs
    response = client_for(attendee).get(MY_REGISTRATIONS)
    assert response.status_code == 200
    assert [r["id"] for r in response.data["results"]] == [second.pk, first.pk]
    item = response.data["results"][1]
    assert set(item["event"]) == {"id", "title", "starts_at"}
    assert item["event"]["title"] == "First"


def test_list_filter_by_status(attendee, my_regs):
    first, second, _ = my_regs
    confirmed = client_for(attendee).get(MY_REGISTRATIONS, {"status": "confirmed"})
    assert [r["id"] for r in confirmed.data["results"]] == [first.pk]
    cancelled = client_for(attendee).get(MY_REGISTRATIONS, {"status": "cancelled"})
    assert [r["id"] for r in cancelled.data["results"]] == [second.pk]


def test_list_filter_unknown_status_400(attendee, my_regs):
    response = client_for(attendee).get(MY_REGISTRATIONS, {"status": "pending"})
    assert response.status_code == 400
    assert "status" in response.data


def test_list_is_paginated(attendee, my_regs):
    assert {"count", "next", "previous", "results"} <= set(
        client_for(attendee).get(MY_REGISTRATIONS).data
    )


def test_detail_of_own_registration(attendee, my_regs):
    first, _, _ = my_regs
    response = client_for(attendee).get(reg_url(first))
    assert response.status_code == 200
    assert response.data["id"] == first.pk


def test_detail_of_someone_elses_registration_404(attendee, my_regs):
    _, _, others = my_regs
    assert client_for(attendee).get(reg_url(others)).status_code == 404


def test_registrations_require_login(my_regs):
    assert client_for().get(MY_REGISTRATIONS).status_code == 401
    assert client_for().get(reg_url(my_regs[0])).status_code == 401


def test_registrations_are_read_only(attendee, my_regs):
    client = client_for(attendee)
    assert client.post(MY_REGISTRATIONS, {}, format="json").status_code == 405
    assert client.delete(reg_url(my_regs[0])).status_code == 405


# --- cancel -------------------------------------------------------------------------


def test_cancel_sets_status_and_timestamp(attendee, event):
    reg = confirm(attendee, event)
    before = timezone.now()
    response = client_for(attendee).post(cancel_url(reg))
    assert response.status_code == 200
    assert response.data["status"] == "cancelled"
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED
    assert reg.cancelled_at is not None and reg.cancelled_at >= before


def test_cancel_twice_409(attendee, event):
    reg = confirm(attendee, event)
    client = client_for(attendee)
    assert client.post(cancel_url(reg)).status_code == 200
    second = client.post(cancel_url(reg))
    assert second.status_code == 409
    assert "already cancelled" in second.data["detail"]


def test_cancel_after_start_400(attendee, organiser):
    started = make_event(organiser, starts_in=-timedelta(minutes=1))
    reg = confirm(attendee, started)
    response = client_for(attendee).post(cancel_url(reg))
    assert response.status_code == 400
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CONFIRMED


def test_cancel_someone_elses_registration_404(attendee, event):
    reg = confirm(make_user("bob"), event)
    assert client_for(attendee).post(cancel_url(reg)).status_code == 404
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CONFIRMED


def test_cancel_requires_login(attendee, event):
    assert client_for().post(cancel_url(confirm(attendee, event))).status_code == 401


def test_reregister_after_cancel(attendee, event):
    client = client_for(attendee)
    first = client.post(register_url(event), {}, format="json")
    assert client.post(cancel_url(Registration.objects.get(pk=first.data["id"]))).status_code == 200
    again = client.post(register_url(event), {}, format="json")
    assert again.status_code == 201
    assert again.data["id"] != first.data["id"]
    assert Registration.objects.filter(user=attendee, event=event).count() == 2


def test_cancel_frees_a_seat(attendee, organiser):
    event = make_event(organiser, capacity=1)
    reg = confirm(attendee, event)
    bob = make_user("bob")
    assert client_for(bob).post(register_url(event), {}, format="json").status_code == 409
    client_for(attendee).post(cancel_url(reg))
    assert client_for(bob).post(register_url(event), {}, format="json").status_code == 201


# --- attendees ----------------------------------------------------------------------


def test_organiser_lists_confirmed_attendees(organiser, event):
    a = confirm(make_user("amy"), event, phone="0801", note="Hi")
    confirm(make_user("ben"), event)
    cancel(confirm(make_user("cat"), event))
    response = client_for(organiser).get(attendees_url(event))
    assert response.status_code == 200
    assert response.data["count"] == 2
    first = response.data["results"][0]
    assert set(first) == {"username", "email", "phone", "note", "created_at"}
    assert first["username"] == "amy"
    assert first["email"] == "amy@example.com"
    assert first["phone"] == "0801" and first["note"] == "Hi"
    assert first["created_at"] == a.created_at.isoformat().replace("+00:00", "Z")
    assert [r["username"] for r in response.data["results"]] == ["amy", "ben"]


def test_attendees_works_for_own_draft_and_past(organiser):
    for event in (
        make_event(organiser, is_published=False),
        make_event(organiser, starts_in=-timedelta(days=1)),
    ):
        assert client_for(organiser).get(attendees_url(event)).status_code == 200


@pytest.mark.parametrize("who", ["attendee", "other_organiser"])
def test_attendees_forbidden_for_others(request, who, event):
    assert client_for(request.getfixturevalue(who)).get(attendees_url(event)).status_code == 403


def test_attendees_of_hidden_event_404_for_others(other_organiser, organiser):
    draft = make_event(organiser, is_published=False)
    assert client_for(other_organiser).get(attendees_url(draft)).status_code == 404


def test_attendees_requires_login(event):
    assert client_for().get(attendees_url(event)).status_code == 401


def test_attendees_is_paginated(organiser):
    event = make_event(organiser, capacity=30)
    for i in range(23):
        confirm(make_user(f"u{i}"), event)
    response = client_for(organiser).get(attendees_url(event))
    assert response.data["count"] == 23
    assert len(response.data["results"]) == 20
    assert len(client_for(organiser).get(attendees_url(event), {"page": 2}).data["results"]) == 3
