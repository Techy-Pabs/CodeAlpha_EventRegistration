from django.db import transaction
from django.db.models import Count, F, Q, Value
from django.db.models.functions import Greatest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .exceptions import BadRequest, Conflict
from .filters import StartsAtRangeFilter
from .models import Event, Registration
from .permissions import IsEventOrganiser, IsOrganiser
from .serializers import (
    AttendeeSerializer,
    EventSerializer,
    RegistrationCreateSerializer,
    RegistrationSerializer,
)

CONFIRMED = Registration.Status.CONFIRMED

NOT_FOUND = OpenApiResponse(description="Event not found or not visible to you.")


def visible_events_q(user):
    """Events this user may see. Everything else behaves as if it didn't exist."""
    visible = Q(is_published=True, starts_at__gt=timezone.now())
    if user.is_authenticated:
        visible |= Q(organiser=user)  # own drafts and past events too
    return visible


@extend_schema_view(
    list=extend_schema(
        summary="List upcoming published events (plus your own as organiser)",
        responses={200: EventSerializer(many=True), 400: OpenApiResponse(description="Bad date.")},
    ),
    retrieve=extend_schema(responses={200: EventSerializer, 404: NOT_FOUND}),
    create=extend_schema(
        responses={
            201: EventSerializer,
            400: OpenApiResponse(description="Validation error."),
            401: OpenApiResponse(description="Not logged in."),
            403: OpenApiResponse(description="Not an organiser."),
        }
    ),
    update=extend_schema(
        responses={
            200: EventSerializer,
            400: OpenApiResponse(description="Validation error."),
            403: OpenApiResponse(description="Not this event's organiser."),
            404: NOT_FOUND,
        }
    ),
    partial_update=extend_schema(
        responses={
            200: EventSerializer,
            400: OpenApiResponse(description="Validation error."),
            403: OpenApiResponse(description="Not this event's organiser."),
            404: NOT_FOUND,
        }
    ),
    destroy=extend_schema(
        responses={
            204: OpenApiResponse(description="Deleted."),
            403: OpenApiResponse(description="Not this event's organiser."),
            404: NOT_FOUND,
            409: OpenApiResponse(description="Has confirmed registrations; unpublish instead."),
        }
    ),
)
class EventViewSet(viewsets.ModelViewSet):
    """Events. Reading is public; organisers manage their own events."""

    serializer_class = EventSerializer
    queryset = Event.objects.all()
    lookup_value_regex = r"\d+"  # /api/events/abc/ is a plain 404
    filter_backends = [filters.SearchFilter, StartsAtRangeFilter, filters.OrderingFilter]
    search_fields = ["title", "description", "location"]
    ordering_fields = ["starts_at"]
    ordering = ["starts_at"]

    def get_queryset(self):
        confirmed = Count("registrations", filter=Q(registrations__status=CONFIRMED))
        return (
            Event.objects.filter(visible_events_q(self.request.user))
            .select_related("organiser")
            .annotate(seats_left=Greatest(F("capacity") - confirmed, Value(0)))
        )

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsAuthenticated(), IsOrganiser()]
        if self.action == "register":
            return [IsAuthenticated()]
        # update, partial_update, destroy, attendees: own events only.
        return [IsAuthenticated(), IsEventOrganiser()]

    def filter_queryset(self, queryset):
        # Search, date range and ordering apply to the list only, so a detail
        # URL with a stray ?search= never turns into a 404.
        if self.action != "list":
            return queryset
        return super().filter_queryset(queryset)

    def _reload(self, serializer):
        # Re-read through get_queryset so the response has a fresh seats_left.
        serializer.instance = self.get_queryset().get(pk=serializer.instance.pk)

    def perform_create(self, serializer):
        serializer.save(organiser=self.request.user)
        self._reload(serializer)

    def update(self, request, *args, **kwargs):
        # Lock the event row (the same lock registering takes) so nobody can
        # register between the capacity check and the save.
        with transaction.atomic():
            Event.objects.select_for_update().filter(pk=kwargs["pk"]).first()
            return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        serializer.save()
        self._reload(serializer)

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            Event.objects.select_for_update().filter(pk=kwargs["pk"]).first()
            return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance):
        if instance.registrations.filter(status=CONFIRMED).exists():
            raise Conflict(
                "This event has confirmed registrations, so it can't be deleted. "
                "Unpublish it instead (set is_published to false)."
            )
        instance.delete()

    @extend_schema(
        summary="Register the logged-in user for this event",
        request=RegistrationCreateSerializer,
        responses={
            201: RegistrationSerializer,
            400: OpenApiResponse(
                description="Bad phone/note, the event has started, or you are its organiser."
            ),
            401: OpenApiResponse(description="Not logged in."),
            404: OpenApiResponse(description="Event not found or not published."),
            409: OpenApiResponse(description="Already registered, or the event is full."),
        },
    )
    @action(detail=True, methods=["post"], serializer_class=RegistrationCreateSerializer)
    def register(self, request, pk=None):
        body = RegistrationCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        with transaction.atomic():
            # Row lock: a second register call for the same event waits here
            # until this transaction commits, so two people can't both take
            # the last seat. The lock is released at the end of the block.
            event = Event.objects.select_for_update().filter(pk=pk, is_published=True).first()
            if event is None:
                raise NotFound("Event not found.")
            if event.starts_at <= timezone.now():
                raise BadRequest("This event has already started.")
            if event.organiser_id == request.user.id:
                raise BadRequest("You can't register for your own event.")
            confirmed = event.registrations.filter(status=CONFIRMED)
            if confirmed.filter(user=request.user).exists():
                raise Conflict("You are already registered for this event.")
            if confirmed.count() >= event.capacity:
                raise Conflict("Event is full.")
            registration = Registration.objects.create(
                user=request.user, event=event, **body.validated_data
            )

        return Response(RegistrationSerializer(registration).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Confirmed attendees (this event's organiser only)",
        responses={
            200: AttendeeSerializer(many=True),
            401: OpenApiResponse(description="Not logged in."),
            403: OpenApiResponse(description="Not this event's organiser."),
            404: NOT_FOUND,
        },
    )
    @action(detail=True, methods=["get"], serializer_class=AttendeeSerializer, filter_backends=[])
    def attendees(self, request, pk=None):
        event = self.get_object()  # 404 if hidden, 403 if not the organiser
        attendees = (
            event.registrations.filter(status=CONFIRMED)
            .select_related("user")
            .order_by("created_at", "id")
        )
        page = self.paginate_queryset(attendees)
        return self.get_paginated_response(AttendeeSerializer(page, many=True).data)


STATUS_PARAM = OpenApiParameter(
    "status",
    OpenApiTypes.STR,
    enum=Registration.Status.values,
    description="Only registrations with this status.",
)


@extend_schema_view(
    list=extend_schema(
        summary="Your registrations, newest first",
        parameters=[STATUS_PARAM],
        responses={
            200: RegistrationSerializer(many=True),
            400: OpenApiResponse(description="Unknown status."),
            401: OpenApiResponse(description="Not logged in."),
        },
    ),
    retrieve=extend_schema(
        responses={
            200: RegistrationSerializer,
            401: OpenApiResponse(description="Not logged in."),
            404: OpenApiResponse(description="Not found or not yours."),
        }
    ),
)
class RegistrationViewSet(viewsets.ReadOnlyModelViewSet):
    """The logged-in user's own registrations. Other people's are a 404."""

    serializer_class = RegistrationSerializer
    queryset = Registration.objects.all()
    permission_classes = [IsAuthenticated]
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        queryset = (
            Registration.objects.filter(user=self.request.user)
            .select_related("event")
            .order_by("-created_at", "-id")
        )
        wanted = self.request.query_params.get("status")
        if self.action == "list" and wanted:
            if wanted not in Registration.Status.values:
                raise ValidationError(
                    {"status": [f"Must be one of: {', '.join(Registration.Status.values)}."]}
                )
            queryset = queryset.filter(status=wanted)
        return queryset

    @extend_schema(
        summary="Cancel one of your registrations",
        request=None,
        responses={
            200: RegistrationSerializer,
            400: OpenApiResponse(description="The event has already started."),
            401: OpenApiResponse(description="Not logged in."),
            404: OpenApiResponse(description="Not found or not yours."),
            409: OpenApiResponse(description="Already cancelled."),
        },
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            # Lock just this registration row (not the joined event) so two
            # cancel calls at once can't both succeed.
            registration = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)), pk=pk
            )
            if registration.status != CONFIRMED:
                raise Conflict("This registration is already cancelled.")
            if registration.event.starts_at <= timezone.now():
                raise BadRequest("This event has already started, so it can't be cancelled.")
            registration.status = Registration.Status.CANCELLED
            registration.cancelled_at = timezone.now()
            registration.save(update_fields=["status", "cancelled_at"])
        return Response(RegistrationSerializer(registration).data)
