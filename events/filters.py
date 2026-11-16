from datetime import datetime, time

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend


def parse_iso(value):
    """ISO date or datetime -> aware datetime, or None if not valid.

    A plain date means midnight UTC on that day. A datetime without an
    offset is read as UTC (TIME_ZONE).
    """
    try:
        parsed = parse_datetime(value)
        if parsed is None:
            day = parse_date(value)
            if day is None:
                return None
            parsed = datetime.combine(day, time.min)
    except ValueError:  # well-formed but impossible, e.g. 2026-02-30
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


class StartsAtRangeFilter(BaseFilterBackend):
    """?starts_after= (inclusive) and ?starts_before= (exclusive) on starts_at."""

    params = {"starts_after": "starts_at__gte", "starts_before": "starts_at__lt"}

    def filter_queryset(self, request, queryset, view):
        errors = {}
        lookups = {}
        for param, lookup in self.params.items():
            raw = request.query_params.get(param)
            if raw is None or raw == "":
                continue
            value = parse_iso(raw)
            if value is None:
                errors[param] = ["Enter a valid ISO 8601 date or datetime, e.g. 2026-12-01."]
            else:
                lookups[lookup] = value
        if errors:
            raise ValidationError(errors)
        return queryset.filter(**lookups)

    def get_schema_operation_parameters(self, view):
        # Read by drf-spectacular so Swagger lists the two query parameters.
        descriptions = {
            "starts_after": "Events starting at or after this ISO date/datetime (UTC if no offset)",
            "starts_before": "Events starting before this ISO date/datetime (UTC if no offset)",
        }
        return [
            {
                "name": name,
                "in": "query",
                "required": False,
                "description": text,
                "schema": {"type": "string", "format": "date-time"},
            }
            for name, text in descriptions.items()
        ]
