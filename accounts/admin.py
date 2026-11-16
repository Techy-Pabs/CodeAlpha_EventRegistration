from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_organiser",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_organiser", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = BaseUserAdmin.fieldsets + (("Organiser", {"fields": ("is_organiser",)}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("Organiser", {"fields": ("is_organiser",)}),)
