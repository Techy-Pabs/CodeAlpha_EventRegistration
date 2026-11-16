from django.contrib import admin

from .models import Event, Registration


class RegistrationInline(admin.TabularInline):
    model = Registration
    extra = 0
    fields = ("user", "status", "phone", "note", "created_at", "cancelled_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "location",
        "starts_at",
        "ends_at",
        "capacity",
        "organiser",
        "is_published",
    )
    list_filter = ("is_published", "starts_at", "organiser")
    search_fields = ("title", "description", "location", "organiser__username")
    date_hierarchy = "starts_at"
    autocomplete_fields = ("organiser",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [RegistrationInline]


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("user", "event", "status", "phone", "created_at", "cancelled_at")
    list_filter = ("status", "event", "created_at")
    search_fields = ("user__username", "user__email", "event__title", "phone")
    autocomplete_fields = ("user", "event")
    readonly_fields = ("created_at",)
