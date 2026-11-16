from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from events.models import Event

from .conftest import client_for, confirm, make_event, make_user

pytestmark = pytest.mark.django_db

LIST = reverse("events:event-list")


def detail(event):
    return reverse("events:event-detail", args=[event.pk])


def ids(response):
    return [item["id"] for item in response.data["results"]]


def iso(dt):
    return dt.isoformat()


def new_event_payload(**overrides):
    start = timezone.now() + timedelta(days=3)
    data = {
        "title": "PyCon Lagos",
        "description": "Annual conference",
        "location": "Lagos",
        "starts_at": iso(start),
        "ends_at": iso(start + timedelta(hours=8)),
        "capacity": 100,
        "is_published": True,
    }
    data.update(overrides)
    return data


@pytest.fixture
def hidden_events(organiser):
    """Events an outsider must not see: a draft and one that already started."""
    return {
        "draft": make_event(organiser, title="Draft", is_published=False),
        "past": make_event(organiser, title="Past", starts_in=-timedelta(days=1)),
    }


# --- visibility -----------------------------------------------------------------


@pytest.mark.parametrize("who", ["anonymous", "attendee", "other_organiser"])
def test_outsiders_list_only_published_upcoming(request, who, event, hidden_events):
    user = None if who == "anonymous" else request.getfixturevalue(who)
    response = client_for(user).get(LIST)
    assert response.status_code == 200
    assert ids(response) == [event.pk]


@pytest.mark.parametrize("who", ["anonymous", "attendee", "other_organiser"])
@pytest.mark.parametrize("kind", ["draft", "past"])
def test_outsiders_get_404_for_hidden_event_detail(request, who, kind, hidden_events):
    user = None if who == "anonymous" else request.getfixturevalue(who)
    assert client_for(user).get(detail(hidden_events[kind])).status_code == 404


def test_organiser_sees_own_drafts_and_past_events(organiser, event, hidden_events):
    response = client_for(organiser).get(LIST)
    assert set(ids(response)) == {event.pk, hidden_events["draft"].pk, hidden_events["past"].pk}
    for hidden in hidden_events.values():
        assert client_for(organiser).get(detail(hidden)).status_code == 200


def test_organiser_does_not_see_other_organisers_drafts(organiser, other_organiser):
    draft = make_event(other_organiser, is_published=False)
    assert client_for(organiser).get(detail(draft)).status_code == 404


def test_detail_is_public(event):
    response = client_for().get(detail(event))
    assert response.status_code == 200
    assert response.data["organiser"] == {"id": event.organiser_id, "username": "org"}


def test_non_numeric_id_is_404(organiser):
    assert client_for(organiser).delete("/api/events/abc/").status_code == 404


# --- seats_left -----------------------------------------------------------------


def test_seats_left_counts_only_confirmed(event):
    for name in ("a", "b", "c"):
        confirm(make_user(name), event)
    cancelled = confirm(make_user("d"), event)
    cancelled.status = "cancelled"
    cancelled.save()
    response = client_for().get(detail(event))
    assert response.data["capacity"] == 10
    assert response.data["seats_left"] == 7


def test_seats_left_zero_when_full(organiser):
    full = make_event(organiser, capacity=1)
    confirm(make_user("a"), full)
    assert client_for().get(detail(full)).data["seats_left"] == 0


def test_list_query_count_does_not_grow_with_events(organiser):
    """Annotation + select_related: one query for the page plus one COUNT."""
    for i in range(5):
        e = make_event(organiser, title=f"E{i}")
        confirm(make_user(f"u{i}"), e)
    with CaptureQueriesContext(connection) as ctx:
        response = client_for().get(LIST)
    assert response.status_code == 200
    assert len(response.data["results"]) == 5
    assert all(item["seats_left"] == 9 for item in response.data["results"])
    assert len(ctx.captured_queries) == 2  # pagination COUNT + page SELECT


# --- filters, ordering, pagination ----------------------------------------------


@pytest.fixture
def three_events(organiser):
    return [
        make_event(organiser, title="Python Workshop", starts_in=timedelta(days=10)),
        make_event(
            organiser,
            title="Design Night",
            description="Figma and python",
            starts_in=timedelta(days=5),
        ),
        make_event(organiser, title="Hack Day", location="Abuja", starts_in=timedelta(days=20)),
    ]


def test_search_matches_title_description_and_location(three_events):
    workshop, design, hack = three_events
    assert set(ids(client_for().get(LIST, {"search": "PYTHON"}))) == {workshop.pk, design.pk}
    assert ids(client_for().get(LIST, {"search": "abuja"})) == [hack.pk]
    assert ids(client_for().get(LIST, {"search": "nothing-matches"})) == []


def test_default_ordering_is_soonest_first(three_events):
    workshop, design, hack = three_events
    assert ids(client_for().get(LIST)) == [design.pk, workshop.pk, hack.pk]


def test_ordering_descending(three_events):
    workshop, design, hack = three_events
    assert ids(client_for().get(LIST, {"ordering": "-starts_at"})) == [
        hack.pk,
        workshop.pk,
        design.pk,
    ]


def test_starts_after_and_before(three_events):
    workshop, design, hack = three_events
    after = (timezone.now() + timedelta(days=7)).date().isoformat()
    before = iso(timezone.now() + timedelta(days=15))
    assert ids(client_for().get(LIST, {"starts_after": after})) == [workshop.pk, hack.pk]
    assert ids(client_for().get(LIST, {"starts_before": before})) == [design.pk, workshop.pk]
    both = client_for().get(LIST, {"starts_after": after, "starts_before": before})
    assert ids(both) == [workshop.pk]


@pytest.mark.parametrize("bad", ["tomorrow", "2026-13-01", "2026-02-30", "12/01/2026"])
@pytest.mark.parametrize("param", ["starts_after", "starts_before"])
def test_bad_date_returns_400(param, bad, event):
    response = client_for().get(LIST, {param: bad})
    assert response.status_code == 400
    assert param in response.data


def test_list_is_paginated(organiser):
    for i in range(25):
        make_event(organiser, title=f"E{i}")
    first = client_for().get(LIST)
    assert first.data["count"] == 25
    assert len(first.data["results"]) == 20
    assert first.data["next"] is not None
    assert len(client_for().get(LIST, {"page": 2}).data["results"]) == 5


# --- create ---------------------------------------------------------------------


def test_organiser_creates_event_and_is_set_as_organiser(organiser, other_organiser):
    payload = new_event_payload(organiser=other_organiser.pk)  # ignored: read-only
    response = client_for(organiser).post(LIST, payload, format="json")
    assert response.status_code == 201, response.data
    assert response.data["organiser"]["id"] == organiser.pk
    assert response.data["seats_left"] == 100
    assert Event.objects.get(pk=response.data["id"]).organiser == organiser


def test_attendee_cannot_create_event(attendee):
    response = client_for(attendee).post(LIST, new_event_payload(), format="json")
    assert response.status_code == 403
    assert not Event.objects.exists()


def test_anonymous_cannot_create_event():
    assert client_for().post(LIST, new_event_payload(), format="json").status_code == 401


def test_create_rejects_end_before_start(organiser):
    start = timezone.now() + timedelta(days=3)
    payload = new_event_payload(starts_at=iso(start), ends_at=iso(start - timedelta(hours=1)))
    response = client_for(organiser).post(LIST, payload, format="json")
    assert response.status_code == 400
    assert "ends_at" in response.data


def test_create_rejects_end_equal_to_start(organiser):
    start = iso(timezone.now() + timedelta(days=3))
    payload = new_event_payload(starts_at=start, ends_at=start)
    assert client_for(organiser).post(LIST, payload, format="json").status_code == 400


def test_create_rejects_start_in_past(organiser):
    start = timezone.now() - timedelta(hours=1)
    payload = new_event_payload(starts_at=iso(start), ends_at=iso(start + timedelta(hours=3)))
    response = client_for(organiser).post(LIST, payload, format="json")
    assert response.status_code == 400
    assert "starts_at" in response.data


def test_create_rejects_zero_capacity(organiser):
    response = client_for(organiser).post(LIST, new_event_payload(capacity=0), format="json")
    assert response.status_code == 400
    assert "capacity" in response.data


# --- update -----------------------------------------------------------------------


def test_owner_can_patch_event(organiser, event):
    response = client_for(organiser).patch(detail(event), {"title": "Renamed"}, format="json")
    assert response.status_code == 200
    assert response.data["title"] == "Renamed"


def test_owner_can_put_event(organiser, event):
    response = client_for(organiser).put(detail(event), new_event_payload(), format="json")
    assert response.status_code == 200, response.data
    event.refresh_from_db()
    assert event.title == "PyCon Lagos"


@pytest.mark.parametrize("who", ["attendee", "other_organiser"])
def test_non_owner_cannot_update_visible_event(request, who, event):
    user = request.getfixturevalue(who)
    response = client_for(user).patch(detail(event), {"title": "Hijacked"}, format="json")
    assert response.status_code == 403
    event.refresh_from_db()
    assert event.title == "Django Meetup"


def test_non_owner_gets_404_for_hidden_event_update(other_organiser, organiser):
    draft = make_event(organiser, is_published=False)
    response = client_for(other_organiser).patch(detail(draft), {"title": "x"}, format="json")
    assert response.status_code == 404


def test_anonymous_cannot_update(event):
    assert client_for().patch(detail(event), {"title": "x"}, format="json").status_code == 401


def test_patch_ends_at_before_existing_start_rejected(organiser, event):
    response = client_for(organiser).patch(
        detail(event), {"ends_at": iso(event.starts_at - timedelta(minutes=1))}, format="json"
    )
    assert response.status_code == 400
    assert "ends_at" in response.data


def test_patch_starts_at_into_past_rejected(organiser, event):
    response = client_for(organiser).patch(
        detail(event), {"starts_at": iso(timezone.now() - timedelta(days=1))}, format="json"
    )
    assert response.status_code == 400
    assert "starts_at" in response.data


def test_owner_can_edit_title_of_past_event(organiser):
    past = make_event(organiser, starts_in=-timedelta(days=2))
    response = client_for(organiser).patch(detail(past), {"title": "Recap"}, format="json")
    assert response.status_code == 200


def test_capacity_cannot_drop_below_confirmed(organiser, event):
    for name in ("a", "b", "c"):
        confirm(make_user(name), event)
    response = client_for(organiser).patch(detail(event), {"capacity": 2}, format="json")
    assert response.status_code == 400
    assert "capacity" in response.data
    event.refresh_from_db()
    assert event.capacity == 10


def test_capacity_can_drop_to_confirmed_count(organiser, event):
    for name in ("a", "b", "c"):
        confirm(make_user(name), event)
    response = client_for(organiser).patch(detail(event), {"capacity": 3}, format="json")
    assert response.status_code == 200
    assert response.data["seats_left"] == 0  # fresh value, not the pre-update one


def test_organiser_is_read_only_on_update(organiser, other_organiser, event):
    client_for(organiser).patch(detail(event), {"organiser": other_organiser.pk}, format="json")
    event.refresh_from_db()
    assert event.organiser == organiser


# --- delete -----------------------------------------------------------------------


def test_owner_can_delete_event_without_confirmed_registrations(organiser, event):
    cancelled = confirm(make_user("a"), event)
    cancelled.status = "cancelled"
    cancelled.save()
    assert client_for(organiser).delete(detail(event)).status_code == 204
    assert not Event.objects.filter(pk=event.pk).exists()


def test_delete_with_confirmed_registrations_returns_409(organiser, event):
    confirm(make_user("a"), event)
    response = client_for(organiser).delete(detail(event))
    assert response.status_code == 409
    assert "unpublish" in response.data["detail"].lower()
    assert Event.objects.filter(pk=event.pk).exists()


@pytest.mark.parametrize("who", ["attendee", "other_organiser"])
def test_non_owner_cannot_delete(request, who, event):
    assert client_for(request.getfixturevalue(who)).delete(detail(event)).status_code == 403
    assert Event.objects.filter(pk=event.pk).exists()


def test_anonymous_cannot_delete(event):
    assert client_for().delete(detail(event)).status_code == 401
