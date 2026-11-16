from django.db import transaction
from django.db.models import Count, F, Q, Value
from django.db.models.functions import Greatest
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import filters, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated

from .exceptions import Conflict
from .filters import StartsAtRangeFilter
from .models import Event, Registration
from .permissions import IsEventOrganiser, IsOrganiser
from .serializers import EventSerializer

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
