from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import Event, Registration


class OrganiserSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ["id", "username"]
        read_only_fields = fields


class EventSerializer(serializers.ModelSerializer):
    organiser = OrganiserSerializer(read_only=True)
    # Filled by the viewset's queryset annotation (one query for the whole
    # page), not by a per-event COUNT.
    seats_left = serializers.IntegerField(read_only=True)

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "description",
            "location",
            "starts_at",
            "ends_at",
            "capacity",
            "seats_left",
            "is_published",
            "organiser",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "seats_left", "organiser", "created_at", "updated_at"]
        # Mirrors the event_capacity_at_least_1 DB constraint: a 400, not a 500.
        extra_kwargs = {"capacity": {"min_value": 1}}

    def validate_starts_at(self, value):
        # New events must start in the future. On update the check applies
        # only if starts_at changes, so an organiser can still fix the title
        # of an event that has already happened.
        changed = self.instance is None or value != self.instance.starts_at
        if changed and value <= timezone.now():
            raise serializers.ValidationError("Start time must be in the future.")
        return value

    def validate_capacity(self, value):
        if self.instance is not None:
            confirmed = self.instance.registrations.filter(
                status=Registration.Status.CONFIRMED
            ).count()
            if value < confirmed:
                raise serializers.ValidationError(
                    f"Capacity cannot be lower than the {confirmed} confirmed registrations."
                )
        return value

    def validate(self, attrs):
        # On a PATCH only one of the two may be sent; compare with the saved one.
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({"ends_at": ["End time must be after start time."]})
        return attrs
